"""업로드 문서 — Gemini 멀티모달 비전 폴백 (실 사진·스캔본, 서식이 다른 진짜 문서).

`db/document_text_extractor.py`(pdfplumber, 결정론적 정규식)가 텍스트 레이어가
없거나(사진·스캔본) 알려진 서식이 아니라서(예: 국세청 표준 세금계산서) 실패했을
때만 호출된다 — 잘 읽히는 데모 PDF에는 이 모듈이 전혀 관여하지 않는다(비용·속도
유지). `api/agent/llm_classify.py`와 같은 클라이언트·재시도 패턴을 재사용한다.

CLAUDE.md 원칙1(LLM 산수 금지)과 같은 결: Gemini는 이미지에서 값을 "읽기"만 한다
— 물량 환산·탄소량 계산은 이 모듈보다 훨씬 뒤(db/calc_engine.py)에서 결정론적
코드가 수행한다.
"""
import json
import os

from google import genai
from google.genai import types

from db.document_text_extractor import DocumentParseError

MODEL = "gemini-3.5-flash"

# confidence가 이 미만이면 "읽긴 읽었지만 신뢰할 수 없음" — 값을 지어내지 않고
# 실패로 취급한다(실패 가시성 원칙, CLAUDE.md §6).
_MIN_CONFIDENCE = 0.5

DOCUMENT_TYPE_LABEL = {
    "tax_invoice": "세금계산서",
    "electric_bill": "전기요금고지서",
    "gas_bill": "도시가스고지서",
}

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "document_type": {
            "type": "STRING",
            "enum": ["tax_invoice", "electric_bill", "gas_bill", "unknown"],
            "description": "실제로 보이는 문서 종류. 셋 중 어느 것도 아니면 unknown.",
        },
        "year": {"type": "INTEGER", "nullable": True},
        "month": {"type": "INTEGER", "nullable": True},
        "supplier_name": {"type": "STRING", "nullable": True},
        "item_description": {"type": "STRING", "nullable": True},
        "supply_amount_krw": {"type": "INTEGER", "nullable": True, "description": "공급가액(부가세 제외), 원 단위"},
        "quantity": {"type": "NUMBER", "nullable": True, "description": "사용량·수량 — 안 찍혀 있으면 null"},
        "quantity_unit": {"type": "STRING", "nullable": True, "description": "kWh | m3 | L 등, quantity 없으면 null"},
        "confidence": {"type": "NUMBER", "description": "0.0~1.0, 읽은 값에 대한 확신도"},
    },
    "required": ["document_type", "confidence"],
}

_SYSTEM_PROMPT = """당신은 한국 중소기업이 올린 세금계산서·전기요금고지서·도시가스고지서 \
사진 또는 스캔본을 읽는 회계 보조 AI다.

이미지에서 다음을 읽어 JSON으로 반환하라: 문서 종류, 작성일자(연/월), 공급자(발행처) \
상호명, 품목명(세금계산서만), 공급가액(부가세 제외 금액, 원), 사용량·수량(전기/도시가스 \
고지서의 kWh·m³ 등, 세금계산서는 대개 없음).

중요: 흐릿하거나 잘려서 안 보이는 값은 절대 지어내지 마라 — null로 남기고 confidence를 \
낮게 보고하라. 낮은 confidence는 사람이 다시 확인하므로 솔직하게 보고하는 것이 중요하다. \
물량 환산이나 탄소 배출량 계산은 하지 않는다(그 계산은 별도의 결정론적 코드가 수행한다)."""


class VisionExtractionError(DocumentParseError):
    """Gemini 호출 자체가 실패했을 때(키 없음·타임아웃·응답 파싱 실패, 재시도 후에도 실패).

    "호출은 됐지만 문서를 읽을 수 없음"(DocumentParseError, 형식 불일치·저화질)과
    구분해 db/quality_issues.py에 다른 사유로 기록하기 위한 서브클래스.
    """


def _detect_mime_type(file_bytes: bytes) -> str:
    if file_bytes[:4] == b"%PDF":
        return "application/pdf"
    if file_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if file_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    raise DocumentParseError(
        "문서에서 텍스트를 읽어내지 못했어요 — 사진(JPG/PNG) 또는 PDF 형식의 자료를 올려 주세요"
    )


def _build_prompt(expected_document_type: str) -> str:
    label = DOCUMENT_TYPE_LABEL.get(expected_document_type, expected_document_type)
    return f'사장님이 "{label}" 칸에 업로드한 이미지다. 위 시스템 안내에 따라 JSON으로 읽어내라.'


def _call_gemini_vision(file_bytes: bytes, mime_type: str, prompt: str) -> dict:
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=20_000),  # ms — 이미지라 텍스트보다 여유
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt],
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )
    return json.loads(resp.text)


def extract_via_vision(file_bytes: bytes, expected_document_type: str) -> dict:
    """실 추출(pdfplumber+정규식)이 실패했을 때만 호출되는 마지막 폴백.

    document_type 불일치·낮은 confidence는 DocumentParseError(형식 불일치와
    동급 실패). Gemini 호출 자체의 반복 실패는 VisionExtractionError.
    """
    mime_type = _detect_mime_type(file_bytes)
    prompt = _build_prompt(expected_document_type)

    last_error = "unknown"
    result: dict | None = None
    for _attempt in range(2):  # 최초 시도 + 1회 재시도 (llm_classify.py와 동일 패턴)
        try:
            result = _call_gemini_vision(file_bytes, mime_type, prompt)
            break
        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"응답 형식 오류: {e}"
            continue
        except Exception as e:  # noqa: BLE001 — API 오류(레이트리밋·타임아웃 등)도 동일 처리
            last_error = f"API 호출 실패: {e}"
            continue

    if result is None:
        raise VisionExtractionError(f"이미지를 읽지 못했어요(AI 호출 오류) — {last_error}")

    detected_type = result.get("document_type")
    if detected_type != expected_document_type:
        detected_label = DOCUMENT_TYPE_LABEL.get(detected_type, "알 수 없는 문서")
        expected_label = DOCUMENT_TYPE_LABEL.get(expected_document_type, expected_document_type)
        raise DocumentParseError(
            f"업로드하신 파일은 {detected_label}로 보여요 — {expected_label} 칸에 다시 올려 주세요"
        )

    confidence = result.get("confidence") or 0.0
    if confidence < _MIN_CONFIDENCE:
        raise DocumentParseError(
            "문서를 정확히 읽지 못했어요 — 더 선명한 사진으로 다시 올려 주세요"
        )

    if result.get("year") is None or result.get("month") is None:
        raise DocumentParseError("문서에서 날짜를 읽어내지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")
    if result.get("supply_amount_krw") is None:
        raise DocumentParseError("공급가액을 읽어내지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")

    parsed = {
        "supplier_name": result.get("supplier_name"),
        "item_description": result.get("item_description"),
        "supply_amount_krw": result.get("supply_amount_krw"),
        "year": result["year"],
        "month": result["month"],
    }
    if result.get("quantity") is not None and result.get("quantity_unit"):
        parsed["quantity"] = result["quantity"]
        parsed["quantity_unit"] = result["quantity_unit"]
    return parsed
