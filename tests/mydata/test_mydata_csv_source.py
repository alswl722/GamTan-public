"""db/mydata_csv_source.py — 회계 담당 마이데이터 연동자료 CSV 리더 검증."""
from db.mydata_csv_source import load_mydata_record


def test_finds_real_row_for_known_company_and_source():
    record = load_mydata_record("C001", "business-registration")
    assert record is not None
    assert record["provider"] == "국세청"
    assert record["document_name"] == "사업자등록증명"


def test_returns_none_for_unknown_company():
    assert load_mydata_record("C999", "business-registration") is None


def test_returns_none_for_known_company_unknown_source():
    assert load_mydata_record("C001", "not-a-real-source") is None
