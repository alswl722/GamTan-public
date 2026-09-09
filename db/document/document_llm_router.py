"""OCR·좌표 매칭까지 전부 실패했을 때만 붙는 최후 수단 — LLM(Gemini)이 "어느 셀이
어느 필드냐"만 판단(라우팅)하고, 실제 값은 항상 그 셀의 OCR 원문을 기존 결정론적
정규식(db/document_text_extractor.py)으로 재파싱한다.

LLM 응답 스키마에는 숫자·날짜 값을 담는 필드가 아예 없다 — date_cell_id/
amount_cell_id처럼 이번 문서의 OCR 셀 id를 가리키는 참조만 반환 가능하다. LLM이
값을 "다시 타이핑"할 방법이 구조적으로 없으므로, CLAUDE.md 원칙1(LLM 산수 금지)·
"환각이 숫자에 개입할 경로가 없다"는 방어 논리를 이 최후 수단 경로에서도 그대로
유지한다 — 서식·어휘가 처음 보는 것이어도 "이게 날짜 라벨이다"라는 의미 판단만
LLM이 돕고, 그 라벨 밑 실제 문자열을 숫자로 바꾸는 건 여전히 순수 함수다.

입력은 멀티모달(이미지 + OCR 셀 목록)이다 — OCR이 라벨 자체를 오독했을 때 이미지로
보정할 여지를 준다. 대신 출력은 셀 id 참조로만 제한하고(모델 스키마 enum 제약),
서버 쪽에서 그 id가 실제 이 문서에 존재하는지 다시 검증한다(이중 안전장치).

`api/agent/llm_classify.py`와 같은 재시도·캐시 패턴을 재사용한다(같은 SDK·모델).

개인정보/영업정보 최소화(docs/borrower-pcaf-data-plan.md §20.4): 셀 목록(텍스트)은
Gemini로 보내기 전에 사업자등록번호·고객번호를 마스킹한다(_mask_cells_for_llm) —
LLM이 필요한 건 "이 셀이 무슨 항목이냐"는 라벨 판단뿐이라 값 자체를 가려도
라우팅 정확도에 영향이 없다. 서버 쪽 재파싱(_resolve_fields)은 항상 마스킹 이전의
원본 cells를 쓴다. **한계**: 문서 이미지 자체(상호명·주소 등이 찍힌 원본 사진)는
라벨 오독 보정을 위해 여전히 그대로 전송된다 — 텍스트 마스킹으로는 이미지 속
정보까지 가릴 수 없다. 이 최후 수단 경로는 텍스트 레이어·OCR·좌표매칭이 전부
실패했을 때만 타므로 빈도는 낮다(CLAUDE.md §7).
"""
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.document.contract_type import normalize_contract_type_class
from db.document.document_ocr_extractor import rasterize_to_images
from db.document.document_text_extractor import (
    DOCUMENT_TYPE_LABEL,
    DocumentParseError,
    DocumentTypeMismatchError,
    OcrRow,
    find_supplier_name_best_effort,
    issue_date_str,
    month_end_issue_date_str,
    parse_amount_from_cell_text,
    parse_customer_number_from_cell_text,
    parse_year_month_from_cell_text,
)
from db.models import LlmCache

MODEL = "gemini-3.5-flash"

# 셀 선택 confidence가 이 미만이면 "가리키긴 했지만 확신 없음" — 채택하지 않고
# 실패 처리한다(예전 db/document_vision_extractor.py의 _MIN_CONFIDENCE와 동일 기준).
_MIN_CONFIDENCE = 0.5

_SYSTEM_PROMPT = """당신은 한국 중소기업이 올린 세금계산서·전기요금고지서·도시가스고지서 \
사진/PDF를 읽는 회계 보조 AI다. 이 문서는 이미 OCR(문자인식)을 거쳐 "셀 목록"으로 \
정리돼 있고, 이미지도 함께 제공된다.

당신의 역할은 딱 하나다 — 아래 셀 목록 중 어느 셀이 어떤 항목(작성일자/청구월/사용월, \
공급가액/청구금액, 품목명, 수량·사용량, 공급자)에 해당하는지 그 셀의 id만 골라서 \
반환하는 것이다. 값 자체를 다시 읽거나 타이핑하지 마라 — 셀 id만 있으면 된다. \
이미지는 셀 목록이 애매하거나 OCR이 잘못 읽었을 수 있는 라벨을 판단할 때 참고용으로만 \
써라.

한 문서에 비슷한 후보가 여러 개면(예: 작성일자 외에 유효기간·결제일 등) 라벨의 \
의미를 보고 실제로 요청받은 항목에 맞는 것만 골라라. 해당하는 셀이 없으면 그 \
필드는 null로 남겨라. 확신이 낮으면(후보가 애매하거나 라벨이 안 보이면) confidence를 \
낮게 보고하라 — 낮은 confidence는 사람이 다시 확인하므로 솔직하게 보고하는 것이 \
중요하다. 계산이나 값 변환은 하지 않는다."""


class LlmRouterError(DocumentParseError):
    """Gemini 호출 자체가 실패했을 때(키 없음·타임아웃·응답 파싱 실패, 재시도 후에도
    실패) — "호출은 됐지만 유효한 셀을 못 가리킴"(DocumentParseError)과 구분해
    db/quality_issues.py에 다른 사유로 기록하기 위한 서브클래스."""


# 알림톡류 문서(한전 사용량 알림 등)는 "예상 전기요금"/"예상 사용량"처럼 실제 청구
# 금액·날짜와 겉보기엔 비슷한 문구로 AI 예측치를 안내한다(실측 2026-08-17, 실제
# 한전 알림톡 캡처 확인 — "10일간 사용량: 182kWh" 옆에 "AI가 예측한 한달 전기사용량
# 376kWh (예상 전기요금 51,260원)"가 나란히 찍혀 있었음). LLM이 이 예측치가 담긴
# 셀을 실제 청구금액/청구월로 잘못 가리켜도, 그 값을 그대로 저장하면 CLAUDE.md
# 원칙1·7(추정치를 실측처럼 쓰지 않는다)을 어기게 된다 — 셀이 속한 행 텍스트에 이
# 접두어가 있으면 LLM의 선택 자체를 신뢰하지 않고 명확히 실패시킨다.
_FORECAST_KEYWORDS = ("예상", "예측", "추정")


def _flatten_cells(rows: list[OcrRow]) -> list[dict]:
    """행 단위 OCR 결과 → [{"id": i, "text": ..., "row_index": ...}] 평탄화.
    row_index는 예측치 방어(같은 행에 "예상" 등이 있는지 확인)에만 쓰고, id→텍스트
    매핑 자체는 이 모듈 안에서만 쓰고 밖으로 안 새어나간다(호출부는 최종 파싱값만
    받는다)."""
    cells = []
    for row_index, row in enumerate(rows):
        for _x0, _x1, text in row:
            cells.append({"id": len(cells), "text": text, "row_index": row_index})
    return cells


# ── Gemini 전송용 마스킹 (docs/borrower-pcaf-data-plan.md §20.4 "AI 데이터
# 최소화" — 사업자번호·고객번호 등 식별정보는 마스킹하고 원본 전체를 기본
# 전송하지 않는다) ──────────────────────────────────────────────────────
#
# LLM이 실제로 필요한 건 "이 셀이 날짜/금액/품목/공급자/고객번호 중 무엇이냐"는
# 라벨 판단뿐이다 — 셀 안의 실제 문자열 값은 그 판단에 필요 없다(_resolve_fields가
# 서버 쪽에서 원본 cells로 재파싱한다, LLM 응답엔 값 필드 자체가 없음 — 원칙1).
# 그래서 마스킹은 "Gemini에 보낼 사본"에만 적용하고, route_fields()는 서버 재파싱에
# 항상 원본 cells를 쓴다 — 마스킹이 라우팅 정확도(셀 위치 판단)를 방해하지 않는다.
_BIZ_REG_NUMBER_RE = re.compile(r"\b\d{3}-\d{2}-\d{5}\b")
# 고객번호는 라벨(문서 앞부분에 반드시 등장)이 있는 셀만 마스킹한다 — 순수 숫자·
# 하이픈 패턴만으로는 금액·수량·전화번호까지 오탐되므로, "고객번호"라는 표지가
# 실제로 있는 셀에서만 숫자열을 가린다(과잉 마스킹으로 라우팅 정확도를 깎지
# 않기 위한 좁은 범위).
_CUSTOMER_NUMBER_LABEL_RE = re.compile(r"(고객번호|고객\s*번호)\s*[:：]?\s*[\d-]+")


def _mask_identifiers(text: str) -> str:
    """사업자등록번호(000-00-00000)·고객번호(라벨 인접)를 마스킹 문자열로 치환."""
    text = _BIZ_REG_NUMBER_RE.sub("[사업자등록번호 마스킹됨]", text)
    text = _CUSTOMER_NUMBER_LABEL_RE.sub(lambda m: f"{m.group(1)}: [마스킹됨]", text)
    return text


def _mask_cells_for_llm(cells: list[dict]) -> list[dict]:
    """Gemini에 보낼 셀 사본만 마스킹한다 — id/row_index는 그대로 두고 text만 치환,
    원본 cells 리스트는 건드리지 않는다(서버 재파싱은 항상 원본을 쓴다)."""
    return [{**c, "text": _mask_identifiers(c["text"])} for c in cells]


def _row_texts(rows: list[OcrRow]) -> list[str]:
    return [" ".join(text for _x0, _x1, text in row) for row in rows]


def _build_schema(cell_ids: list[int]) -> dict:
    # enum을 이번 문서의 실제 셀 id로만 채운다 — 문서마다 셀이 다르므로 정적 스키마가
    # 아니라 호출마다 동적으로 만든다. 빈 문서(셀 0개)도 스키마 자체는 유효해야 하므로
    # 최소 하나의 자리표시자를 둔다(실제로 선택될 일은 없음 — cells가 비면 애초에
    # route_fields()가 값 해석 단계에서 전부 None 처리한다).
    id_enum = [str(i) for i in cell_ids] if cell_ids else ["__none__"]
    ref_field = {
        "type": "STRING",
        "nullable": True,
        "enum": id_enum,
        "description": "해당 필드에 맞는 셀의 id(문자열). 없으면 null.",
    }
    return {
        "type": "OBJECT",
        "properties": {
            "document_type": {
                "type": "STRING",
                # water_bill은 파싱 지원 전이지만 어휘에는 넣는다 — 선택지에 없으면
                # 모델이 수도고지서를 electric_bill로 밀어넣을 수 있고, 그러면 수도
                # 사용량이 kWh 자리에 섞여 감축률을 오염시킨다. 정답 칸을 주고
                # 파서 단계에서 "아직 지원 안 함"으로 명확히 실패시키는 쪽이 안전하다.
                "enum": ["tax_invoice", "electric_bill", "gas_bill", "water_bill", "unknown"],
                "description": "실제로 보이는 문서 종류. 어느 것도 아니면 unknown.",
            },
            "date_cell_id": ref_field,
            "amount_cell_id": ref_field,
            "item_cell_id": ref_field,
            "quantity_cell_id": ref_field,
            "supplier_cell_id": ref_field,
            # 전기고지서 전용 보조 필드 — 소상공인 판별 근거(data-plan §7.1). 다른 문서
            # 종류에선 null로 온다. 여기서도 LLM은 "어느 셀이냐"만 고르고, 값은 그 셀의
            # OCR 원문을 결정론적으로 재해석한다(원칙1 — 값을 지어낼 경로 없음).
            "contract_type_cell_id": ref_field,
            "customer_number_cell_id": ref_field,
            "confidence": {"type": "NUMBER", "description": "0.0~1.0, 셀 선택에 대한 확신도"},
            "evidence": {"type": "STRING", "description": "판단 근거 한 문장"},
        },
        "required": ["document_type", "confidence", "evidence"],
    }


def _build_contents(images, cells: list[dict], expected_document_type: str | None) -> list:
    label = DOCUMENT_TYPE_LABEL.get(expected_document_type, "미지정(그냥 업로드 — 종류부터 판별 필요)")
    prompt = (
        f"업로드 슬롯: {label}.\n"
        f"OCR 셀 목록(JSON, id와 원문 텍스트): {json.dumps(cells, ensure_ascii=False)}"
    )
    parts: list = []
    for image in images:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"))
    parts.append(prompt)
    return parts


def _call_gemini(images, cells: list[dict], expected_document_type: str | None) -> dict:
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=20_000),  # ms — 이미지 포함이라 텍스트보다 여유
    )
    cell_ids = [c["id"] for c in cells]
    resp = client.models.generate_content(
        model=MODEL,
        contents=_build_contents(images, cells, expected_document_type),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_build_schema(cell_ids),
        ),
    )
    return json.loads(resp.text)


def _hash_file(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _cache_get(session: Session, file_hash: str) -> dict | None:
    cached = session.execute(
        select(LlmCache).where(LlmCache.text_hash == file_hash)
    ).scalar_one_or_none()
    if cached is None:
        return None
    cached.hit_count = (cached.hit_count or 0) + 1
    cached.last_used_at = datetime.now(timezone.utc)
    session.commit()
    return cached.llm_response


def _cache_put(session: Session, file_hash: str, response: dict) -> None:
    from sqlalchemy.exc import IntegrityError

    session.add(LlmCache(text_hash=file_hash, item_description="[문서 이미지 — LLM 필드 라우팅]", llm_response=response))
    try:
        session.commit()
    except IntegrityError:
        # 동일 file_hash 가 이미 존재(동시 업로드 등) — 기존 캐시를 신뢰하고 이번 건은 버림
        session.rollback()


def _resolve_cell_id(raw_id, valid_ids: set) -> int | None:
    """LLM이 반환한 셀 id 문자열을 검증한다 — enum 제약을 모델이 어겨도(드묾)
    실제 이 문서의 셀 id 목록에 없으면 무시한다(서버 쪽 이중 검증)."""
    if raw_id is None:
        return None
    try:
        cid = int(raw_id)
    except (TypeError, ValueError):
        return None
    return cid if cid in valid_ids else None


def _resolve_fields(result: dict, cells: list[dict], row_texts: list[str], document_type: str | None) -> dict:
    """LLM이 가리킨 셀 id → 실제 셀 원문 → 기존 결정론적 파서로 값 추출.

    result(LLM 응답)에서는 *_cell_id만 읽는다 — 값 자체(금액·날짜 등)를 담는 키가
    스키마에 없으므로 여기서 읽을 수도 없다. 값은 전부 cells(OCR 원문)에서
    parse_amount_from_cell_text/parse_year_month_from_cell_text로 다시 얻는다.

    document_type은 issue_date 폴백 규칙을 가르기 위해서만 쓴다 — 세금계산서는
    셀에서 일자를 못 찾으면 issue_date를 비워 상위 호출부가 실패시키고(계산에
    실질적인 필드라 대충 채우지 않음), 전기·도시가스는 말일로 채운다(그 달
    청구서라는 개념만 있는 문서, 2026-08-19 사용자 확인 — db/document_text_
    extractor.py::_month_end_issue_date_str와 동일 원칙).
    """
    by_id = {c["id"]: c for c in cells}
    valid_ids = set(by_id)
    parsed: dict = {}

    def _is_forecast_cell(cell_id: int) -> bool:
        row_index = by_id[cell_id]["row_index"]
        row_text = row_texts[row_index] if 0 <= row_index < len(row_texts) else ""
        return any(kw in row_text for kw in _FORECAST_KEYWORDS)

    date_id = _resolve_cell_id(result.get("date_cell_id"), valid_ids)
    if date_id is not None:
        if _is_forecast_cell(date_id):
            raise DocumentParseError(
                "실제 청구월이 아니라 예상·추정치로 보여요 — 정식 청구서로 다시 올려 주세요"
            )
        ymd = parse_year_month_from_cell_text(by_id[date_id]["text"])
        if ymd is not None:
            year, month, day = ymd
            parsed["year"], parsed["month"] = year, month
            if day is not None:
                parsed["issue_date"] = issue_date_str(year, month, day)
            elif document_type in ("electric_bill", "gas_bill"):
                parsed["issue_date"] = month_end_issue_date_str(year, month)

    amount_id = _resolve_cell_id(result.get("amount_cell_id"), valid_ids)
    if amount_id is not None:
        if _is_forecast_cell(amount_id):
            raise DocumentParseError(
                "실제 청구금액이 아니라 예상·추정치로 보여요 — 정식 청구서로 다시 올려 주세요"
            )
        amount = parse_amount_from_cell_text(by_id[amount_id]["text"])
        if amount is not None:
            parsed["supply_amount_krw"] = amount

    item_id = _resolve_cell_id(result.get("item_cell_id"), valid_ids)
    if item_id is not None:
        parsed["item_description"] = by_id[item_id]["text"].strip()

    # 수량은 세금계산서 등에서 안 찍힌 경우가 흔하다 — 단위까지는 안 뽑고 숫자만
    # 채운다(기존 관례와 동일: quantity_unit 없으면 다운스트림이 금액÷단가로 환산).
    qty_id = _resolve_cell_id(result.get("quantity_cell_id"), valid_ids)
    if qty_id is not None:
        qty = parse_amount_from_cell_text(by_id[qty_id]["text"])
        if qty is not None:
            parsed["quantity"] = qty

    supplier_id = _resolve_cell_id(result.get("supplier_cell_id"), valid_ids)
    if supplier_id is not None:
        parsed["supplier_name"] = by_id[supplier_id]["text"].strip()

    # 계약종별·고객번호 — 소상공인 판별 근거(data-plan §7.1). LLM이 고른 셀의 원문을
    # 텍스트 레이어 경로와 **같은 함수**로 정규화한다(구조화 로직 공유 원칙).
    contract_id = _resolve_cell_id(result.get("contract_type_cell_id"), valid_ids)
    if contract_id is not None:
        contract_type = by_id[contract_id]["text"].strip()
        if contract_type:
            parsed["contract_type"] = contract_type
            parsed["contract_type_class"] = normalize_contract_type_class(contract_type)

    customer_id = _resolve_cell_id(result.get("customer_number_cell_id"), valid_ids)
    if customer_id is not None:
        customer_number = parse_customer_number_from_cell_text(by_id[customer_id]["text"])
        if customer_number is not None:
            parsed["customer_number"] = customer_number

    return parsed


def route_fields(
    session: Session,
    file_bytes: bytes,
    rows: list[OcrRow] | None,
    expected_document_type: str | None,
) -> tuple[dict, float]:
    """OCR·좌표 매칭이 전부 실패했을 때만 부르는 최후 수단.

    rows가 None/빈 리스트면(PaddleOCR이 아예 글자를 못 찾은 경우) 셀 목록 없이
    이미지만으로 시도한다 — 필드를 못 가리킬 가능성이 높지만 문서 종류 판별 정도는
    가능할 수 있어 시도 자체는 막지 않는다.

    반환은 (parsed_dict, confidence). 실패하면(호출 실패·신뢰도 낮음·필수 필드
    없음) DocumentParseError. 슬롯과 실제 판별이 다르면 DocumentTypeMismatchError.
    """
    file_hash = _hash_file(file_bytes)
    cells = _flatten_cells(rows or [])
    # Gemini에는 마스킹된 사본만 보낸다 — 서버 재파싱(_resolve_fields 등)은 이
    # 함수 끝까지 원본 cells를 그대로 쓴다(§20.4 AI 데이터 최소화).
    masked_cells = _mask_cells_for_llm(cells)

    cached = _cache_get(session, file_hash)
    if cached is not None:
        result = cached
    else:
        images = rasterize_to_images(file_bytes)
        last_error = "unknown"
        result = None
        for _attempt in range(2):  # 최초 시도 + 1회 재시도 (llm_classify.py와 동일 패턴)
            try:
                result = _call_gemini(images, masked_cells, expected_document_type)
                break
            except (json.JSONDecodeError, ValueError) as e:
                last_error = f"응답 형식 오류: {e}"
                continue
            except Exception as e:  # noqa: BLE001 — API 오류(레이트리밋·타임아웃 등)도 동일 처리
                last_error = f"API 호출 실패: {e}"
                continue
        if result is None:
            raise LlmRouterError(f"이미지를 읽지 못했어요(AI 호출 오류) — {last_error}")
        _cache_put(session, file_hash, result)

    detected_type = result.get("document_type")
    if expected_document_type is not None and detected_type not in (expected_document_type, "unknown", None):
        detected_label = DOCUMENT_TYPE_LABEL.get(detected_type, "알 수 없는 문서")
        expected_label = DOCUMENT_TYPE_LABEL.get(expected_document_type, expected_document_type)
        raise DocumentTypeMismatchError(
            f"업로드하신 파일은 {detected_label}로 보여요 — {expected_label} 칸에 다시 올려 주세요"
        )

    confidence = result.get("confidence") or 0.0
    if confidence < _MIN_CONFIDENCE:
        raise DocumentParseError("문서를 정확히 읽지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")

    resolved_type = expected_document_type or (detected_type if detected_type != "unknown" else None)
    if resolved_type is None:
        raise DocumentParseError("문서 종류를 판별하지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")

    parsed = _resolve_fields(result, cells, _row_texts(rows or []), resolved_type)
    if parsed.get("year") is None or parsed.get("month") is None:
        raise DocumentParseError("문서에서 날짜를 읽어내지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")
    if parsed.get("supply_amount_krw") is None:
        raise DocumentParseError("금액을 읽어내지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")

    # item_description은 voucher.item_description으로 그대로 저장되고, 나중에
    # 분류 단계(api/agent/tools.py::classify_vouchers)가 이 값을 해시·매칭 키로
    # 쓴다 — None으로 새 나가면 그때 가서야 크래시(hash_item이 None.encode() 호출)
    # 한다(실측 확인). 전기·도시가스는 청구서마다 품목명이 달라질 이유가 없어
    # db/document_text_extractor.py의 결정론적 파서와 동일한 고정 문구로 채운다.
    # 세금계산서는 품목이 Scope·연료 분류에 직접 쓰이는 실질 정보라 대충 채우지
    # 않고 못 찾으면 명확히 실패시킨다.
    if not parsed.get("item_description"):
        if resolved_type == "electric_bill":
            parsed["item_description"] = "전기요금 (산업용 을)"
        elif resolved_type == "gas_bill":
            parsed["item_description"] = "도시가스"
        else:
            raise DocumentParseError("품목명을 읽어내지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")

    if not parsed.get("supplier_name"):
        parsed["supplier_name"] = find_supplier_name_best_effort("\n".join(c["text"] for c in cells))

    parsed["document_type"] = resolved_type
    return parsed, confidence
