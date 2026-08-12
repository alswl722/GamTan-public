"""문서 추출(OCR) — 실제 텍스트 추출 우선, 안 되면 합성 mock으로 폴백.

`extract_document()`가 이 파이프라인의 유일한 진입점이다. 회계 담당이 만든
업로드 서류(`data/업로드서류/`, `scripts/generate_upload_docs.py`)는 스캔 이미지가
아니라 텍스트 레이어가 있는 PDF라, `db/document_text_extractor.py`가 실제 내용을
그대로 읽는다(OCR·비전 모델 불필요 — 실 사진·스캔본 OCR은 별도 범위, 그때 가서
`db/document_text_extractor.py::extract_pdf_text()` 내부만 교체하면 된다).

실 추출이 안 되는 파일(PDF가 아님·형식이 다름)은 year/month가 주어졌을 때만
과거처럼 해시 기반 합성값으로 폴백한다(임의 파일로 개발·테스트하는 용도).
year/month 없이 실추출도 실패하면 값을 지어내지 않고 DocumentParseError를 그대로
던진다(실패 가시성 원칙, CLAUDE.md §6) — 호출부(api/document_ingestion.py)가
422로 안내한다.
"""
import hashlib

from db.document_text_extractor import DocumentParseError, extract_pdf_text, parse_document_text

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"

_TAX_INVOICE_TEMPLATES = [
    {"supplier_name": "구미석유", "item_description": "경유", "base_amount": 600_000},
    {"supplier_name": "구미석유", "item_description": "경유 외 1종", "base_amount": 650_000},
    {"supplier_name": "구미주유소", "item_description": "휘발유", "base_amount": 420_000},
    {"supplier_name": "대성에너지", "item_description": "LPG 외 1종", "base_amount": 380_000},
]

_ELECTRIC_BILL_TEMPLATE = {
    "supplier_name": "한국전력공사",
    "item_description": "전기요금 (산업용 을)",
    "base_amount": 3_500_000,
    "quantity_unit": "kWh",
    "base_quantity": 15_000,
}

_GAS_BILL_TEMPLATE = {
    "supplier_name": "대성에너지",
    "item_description": "도시가스",
    "base_amount": 800_000,
    "quantity_unit": "m3",
    "base_quantity": 800,
}


def _seed(file_bytes: bytes) -> int:
    """파일 내용 해시 기반 시드 — 같은 파일을 다시 올려도 같은 합성값이 나오게(재현성)."""
    return int(hashlib.sha256(file_bytes).hexdigest()[:8], 16)


def _synthetic_extract(file_bytes: bytes, document_type: DocumentType, *, year: int, month: int) -> dict:
    """실 추출이 안 될 때의 폴백 — 파일 내용을 무시하고 결정론적 합성값을 만든다."""
    seed = _seed(file_bytes)

    if document_type == "electric_bill":
        t = _ELECTRIC_BILL_TEMPLATE
        variance = 0.85 + (seed % 30) / 100  # 0.85~1.14
        return {
            "supplier_name": t["supplier_name"],
            "item_description": t["item_description"],
            "supply_amount_krw": round(t["base_amount"] * variance),
            "quantity": round(t["base_quantity"] * variance),
            "quantity_unit": t["quantity_unit"],
            "year": year,
            "month": month,
        }

    if document_type == "gas_bill":
        t = _GAS_BILL_TEMPLATE
        variance = 0.8 + (seed % 40) / 100  # 0.8~1.19
        return {
            "supplier_name": t["supplier_name"],
            "item_description": t["item_description"],
            "supply_amount_krw": round(t["base_amount"] * variance),
            "quantity": round(t["base_quantity"] * variance),
            "quantity_unit": t["quantity_unit"],
            "year": year,
            "month": month,
        }

    # tax_invoice — 여러 연료 템플릿 중 하나를 해시로 선택
    t = _TAX_INVOICE_TEMPLATES[seed % len(_TAX_INVOICE_TEMPLATES)]
    variance = 0.85 + (seed % 30) / 100
    return {
        "supplier_name": t["supplier_name"],
        "item_description": t["item_description"],
        "supply_amount_krw": round(t["base_amount"] * variance),
        "year": year,
        "month": month,
    }


def extract_document(
    file_bytes: bytes, document_type: DocumentType, *, year: int | None = None, month: int | None = None,
) -> dict:
    """문서에서 실제로 날짜·금액을 읽어낸다 — year/month는 더 이상 사용자가 미리
    지정하지 않아도 된다(문서 자체가 몇 월 자료인지 알려준다).

    1. PDF 텍스트 추출 시도 → 성공하면 그 값을 그대로 신뢰한다(문서가 실제로
       말하는 날짜·금액이 사용자가 우연히 고른 달보다 항상 더 정확하다).
    2. 실패하면(PDF가 아니거나 알려진 형식이 아님) year/month가 주어졌을
       때만 과거 합성 mock으로 폴백한다.
    3. year/month도 없이 실패하면 DocumentParseError를 그대로 던진다 —
       값을 지어내지 않는다.
    """
    text = extract_pdf_text(file_bytes)
    if text is not None:
        try:
            return parse_document_text(text, document_type)
        except DocumentParseError:
            if year is None or month is None:
                raise

    if year is None or month is None:
        raise DocumentParseError(
            "문서에서 날짜를 읽어내지 못했어요 — PDF 형식의 자료를 올려 주세요"
        )
    return _synthetic_extract(file_bytes, document_type, year=year, month=month)
