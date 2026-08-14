"""업로드된 PDF에서 실제 텍스트를 뽑아 문서종류·날짜·금액·수량을 정규식으로 파싱한다.

`scripts/generate_upload_docs.py`가 만드는 문서는 스캔 이미지가 아니라 reportlab로
그린 텍스트 레이어 PDF다 — 그래서 OCR·비전 모델 없이 `pdfplumber`로 전체 내용이
그대로 읽힌다. (실 서비스에서 사장님이 사진으로 찍어 올리는 경우는 별개 — 그건
진짜 스캔 이미지라 여기 범위 밖이고, 그때 가서 이 모듈의 `extract_pdf_text()`
내부만 실 OCR/비전 호출로 교체하면 된다.)

파싱 실패(PDF가 아님·형식이 다름·"판독 불가" 표시)는 값을 지어내지 않고
`DocumentParseError`로 명확히 실패한다(실패 가시성 원칙, CLAUDE.md §6).
"""
import io
import re

import pdfplumber

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"

DOCUMENT_TYPE_LABEL = {
    "tax_invoice": "세금계산서",
    "electric_bill": "전기요금고지서",
    "gas_bill": "도시가스고지서",
}

_TITLE_TO_DOCUMENT_TYPE = {
    "전자세금계산서": "tax_invoice",
    "전기요금 고지서": "electric_bill",
    "도시가스 요금고지서": "gas_bill",
}


class DocumentParseError(ValueError):
    """PDF에서 필요한 정보를 읽어내지 못했을 때 — 값을 지어내지 않고 여기서 멈춘다."""


def extract_pdf_text(file_bytes: bytes) -> str | None:
    """PDF가 아니거나 텍스트 레이어가 없으면 None(실 사진·스캔본 등 — OCR 미도입 영역).
    호출부가 이 None을 어떻게 다룰지(합성 폴백 vs 실패) 결정한다."""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text()
    except Exception:
        return None
    return text or None


def detect_document_type(text: str) -> DocumentType | None:
    """첫 줄 제목으로 문서종류 판별 — 못 알아보면 None.

    db/document_extraction.py가 이 함수로 먼저 "아예 모르는 서식인지"를 갈라
    비전 폴백 여부를 정한다(모르는 서식만 비전 재시도, 아는 서식인데 슬롯이
    틀린 경우는 비전으로 재시도해도 답이 안 바뀌므로 그대로 실패시킴).
    """
    stripped = text.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip()
    return _TITLE_TO_DOCUMENT_TYPE.get(first_line)


def _parse_amount(raw: str, *, field_label: str) -> int:
    """콤마 섞인 숫자 문자열 → int. "▨"·"판독 불가" 표시가 있으면 명확히 실패시킨다
    (저품질 스캔 시나리오 — 값을 지어내는 대신 재업로드를 요청해야 하는 케이스)."""
    cleaned = raw.strip()
    if "▨" in cleaned or "판독 불가" in cleaned:
        raise DocumentParseError(
            f"{field_label}을(를) 읽을 수 없는 파일이에요(화질 불량 등) — 다시 스캔해서 올려 주세요"
        )
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        raise DocumentParseError(f"{field_label} 형식을 인식하지 못했어요: {raw!r}")
    return int(digits)


def _line_value(text: str, label_pattern: str, *, field_label: str) -> str:
    m = re.search(label_pattern + r"\s+(.+)", text)
    if not m:
        raise DocumentParseError(f"{field_label} 항목을 찾지 못했어요")
    return m.group(1).strip()


def parse_document_text(text: str, expected_document_type: DocumentType | None = None) -> dict:
    """텍스트에서 문서종류·날짜·공급자·금액·수량을 뽑는다.

    expected_document_type이 주어졌는데 실제 내용이 다르면(엉뚱한 카드에 업로드)
    값을 억지로 맞추지 않고 명확히 실패시킨다. 생략(None)하면 대조 없이 판별된
    종류를 그대로 신뢰한다("그냥 업로드" — 어느 칸인지 모르고 올릴 때).

    반환 dict에는 항상 "document_type"(실제 판별값)이 포함된다 — 호출부가
    사용자가 지정 안 한 경우에도 실제 종류를 알 수 있어야 하기 때문.
    """
    detected = detect_document_type(text)
    if detected is None:
        raise DocumentParseError("인식할 수 없는 문서 형식이에요")
    if expected_document_type is not None and detected != expected_document_type:
        raise DocumentParseError(
            f"업로드하신 파일은 {DOCUMENT_TYPE_LABEL[detected]}로 보여요 — "
            f"{DOCUMENT_TYPE_LABEL[expected_document_type]} 칸에 다시 올려 주세요"
        )

    if detected == "electric_bill":
        result = _parse_electric_bill(text)
    elif detected == "gas_bill":
        result = _parse_gas_bill(text)
    else:
        result = _parse_tax_invoice(text)
    return {**result, "document_type": detected}


def _parse_electric_bill(text: str) -> dict:
    date_m = re.search(r"청구월:\s*(\d{4})-(\d{2})", text)
    if not date_m:
        raise DocumentParseError("청구월을 찾지 못했어요")
    quantity = _parse_amount(
        _line_value(text, r"사용량\(kWh\)", field_label="사용량"), field_label="사용량"
    )
    amount = _parse_amount(
        _line_value(text, r"청구금액\(원\)", field_label="청구금액"), field_label="청구금액"
    )
    return {
        "supplier_name": "한국전력공사",
        "item_description": "전기요금 (산업용 을)",
        "supply_amount_krw": amount,
        "quantity": quantity,
        "quantity_unit": "kWh",
        "year": int(date_m.group(1)),
        "month": int(date_m.group(2)),
    }


def _parse_gas_bill(text: str) -> dict:
    date_m = re.search(r"사용월:\s*(\d{4})-(\d{2})", text)
    if not date_m:
        raise DocumentParseError("사용월을 찾지 못했어요")
    quantity = _parse_amount(
        _line_value(text, r"사용량\(m³\)", field_label="사용량"), field_label="사용량"
    )
    amount = _parse_amount(
        _line_value(text, r"청구금액\(원\)", field_label="청구금액"), field_label="청구금액"
    )
    return {
        "supplier_name": "도시가스",
        "item_description": "도시가스",
        "supply_amount_krw": amount,
        "quantity": quantity,
        "quantity_unit": "m3",
        "year": int(date_m.group(1)),
        "month": int(date_m.group(2)),
    }


def _parse_tax_invoice(text: str) -> dict:
    date_m = re.search(r"작성일자:\s*(\d{4})-(\d{2})-(\d{2})", text)
    if not date_m:
        raise DocumentParseError("작성일자를 찾지 못했어요")
    supplier_m = re.search(r"공급자:\s*(.+)", text)
    # 품목 행: "경유 L 301L 1,400 420,833" — 품목명, 규격, 수량+단위(예: "301L"), 단가(원),
    # 공급가액(원). 마지막 두 컬럼만 순수 숫자/콤마라 이 패턴으로 헤더 행("품목명 규격 ...
    # 공급가액(원)")과 구분된다(헤더는 괄호·한글이 섞여 있어 [\d,]+로 안 끝남).
    row_m = re.search(r"^(\S+)\s+\S+\s+(\S+)\s+[\d,]+\s+([\d,]+)\s*$", text, re.MULTILINE)
    if not row_m:
        raise DocumentParseError("품목·공급가액 행을 찾지 못했어요")
    result = {
        "supplier_name": supplier_m.group(1).strip() if supplier_m else "알 수 없음",
        "item_description": row_m.group(1).strip(),
        "supply_amount_krw": _parse_amount(row_m.group(3), field_label="공급가액"),
        "year": int(date_m.group(1)),
        "month": int(date_m.group(2)),
    }
    # 세금계산서는 물량이 안 찍힌 경우("-" 등)가 더 흔하다 — 이때는 quantity 필드
    # 자체를 안 넣어 기존 금액÷단가 환산 경로를 그대로 탄다.
    qty_m = re.match(r"^([\d,]+)(\D+)$", row_m.group(2))
    if qty_m:
        result["quantity"] = _parse_amount(qty_m.group(1), field_label="수량")
        result["quantity_unit"] = qty_m.group(2).strip()
    return result
