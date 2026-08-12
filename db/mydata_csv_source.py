"""회계 담당이 올려준 마이데이터 연동자료 CSV — 데모 기업 6곳(C001~C006, db/seed_mock.py
의 EXTRA_COMPANIES)이 실제로 어떤 문서를 수집했는지의 정본.

data/마이데이터_연동자료_전체기업.csv (docs/upload-scenarios.md 참고). 이 CSV는 문서
메타데이터(발급기관·문서명·수집상태·용도·한계)만 담고 있고 사업자등록번호 같은
필드값 자체는 없다 — 그 값은 여전히 api/mydata_kyb_mock.py의 합성 함수가 채우고,
여기서는 그 위에 "실제로 회계가 관리하는 문서 메타데이터"를 얹기만 한다.

원본이 없거나(로컬에서 아직 안 받은 경우) 해당 기업·문서 조합이 없으면 None을
반환한다 — 호출부(api/mydata_kyb_mock.py)는 항상 합성 폴백을 유지한다(실패 가시성
원칙과 같은 결: 없는 데이터를 있는 척하지 않는다).
"""
import csv
import os

_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "마이데이터_연동자료_전체기업.csv"
)

DOCUMENT_NAME_TO_SOURCE = {
    "사업자등록증명": "business-registration",
    "부가가치세과세표준증명": "vat-tax-base",
    "표준재무제표증명": "financial-statement",
    "중소기업확인서": "sme-certificate",
    "전기요금 납부내역": "kepco-payment-history",
}


def _load_all() -> list[dict]:
    if not os.path.exists(_CSV_PATH):
        return []
    with open(_CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_mydata_record(external_company_id: str, source: str) -> dict | None:
    """external_company_id(예: "C001")·source(예: "business-registration") 조합에
    해당하는 CSV 행 1건. {provider, document_name, collected_status, used_for,
    limitation} 형태. 없으면 None."""
    for row in _load_all():
        if (
            row.get("company_id") == external_company_id
            and DOCUMENT_NAME_TO_SOURCE.get(row.get("document_name")) == source
        ):
            return {
                "provider": row.get("provider"),
                "document_name": row.get("document_name"),
                "collected_status": row.get("collected_status"),
                "used_for": row.get("used_for"),
                "limitation": row.get("limitation"),
            }
    return None
