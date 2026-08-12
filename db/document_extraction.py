"""문서 추출(OCR) — 이번 주는 합성 mock, 함수 경계만 고정.

`extract_document()`가 이 파이프라인의 유일한 진입점이다. 지금은 실제 OCR을
부르지 않고 파일 내용 해시로 결정론적인 합성 값을 만들어 반환한다 — 마이데이터
mock과 같은 전략(CLAUDE.md "실패 가시성 원칙"과 별개로, 아직 붙이지 않은 실
연동을 붙인 것처럼 위장하지 않되, 데모 재현성은 유지). 실제 OCR이든 로컬 모델
(Qwen 등)이든 이 함수 내부만 교체하면 나머지 파이프라인(source_documents 적재→
voucher 생성)은 그대로 재사용된다 — 로컬 모델 전환은 별도 팀 합의 필요(CLAUDE.md
§3 LLM 스택 확정·변경 금지).
"""
import hashlib

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


def extract_document(file_bytes: bytes, document_type: DocumentType, *, year: int, month: int) -> dict:
    """문서유형별 합성 추출 결과. year/month는 업로드 화면에서 사용자가 지정한
    "몇 월 자료인지"를 그대로 신뢰한다 — 실제 OCR이 붙기 전까진 이미지에서
    날짜를 읽어내는 것처럼 위장하지 않는다."""
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
