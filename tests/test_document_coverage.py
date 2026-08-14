"""db/document_coverage.py::upload_streak 골든 케이스.

핵심 검증축:
  - 이번 달 직전부터 거꾸로 세어, 필수 문서가 전부 채워진 연속 개월 수를 반환한다.
  - 이번 달은 진행 중이라 세지 않는다(미완료를 완료로 세지 않음).
  - 중간에 빠진 달이 있으면 거기서 스트릭이 끊긴다.
  - electric_bill은 연료 체크 여부와 무관하게 항상 필수라, 체크 전이어도 스트릭이 성립한다.
  - 필수 아닌 문서종류(예: 도시가스 미선택)는 스트릭 판정에서 제외된다.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.document_coverage import upload_streak
from db.models import Base, Company, FinancialInstitution, InstitutionBorrower, SourceDocument


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            fuel_types_json={"city_gas": True, "electricity": True},
        )
        session.add(company)
        session.commit()
        inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
        session.add(inst)
        session.commit()
        session.add(InstitutionBorrower(
            financial_institution_id=inst.id, company_id=company.id,
            external_customer_id="cust-1", consent_status="active",
        ))
        session.commit()
        yield session, company.id, inst.id


def _add_doc(session, cid, inst_id, document_type, year, month):
    session.add(SourceDocument(
        financial_institution_id=inst_id, company_id=cid, document_type=document_type,
        source_system="upload:ocr", year=year, month=month,
    ))
    session.commit()


def test_streak_counts_consecutive_complete_months_before_this_month(db):
    session, cid, inst_id = db
    now = datetime.now(timezone.utc)
    for delta in (-1, -2, -3):
        y, m = _shift(now.year, now.month, delta)
        _add_doc(session, cid, inst_id, "gas_bill", y, m)
        _add_doc(session, cid, inst_id, "electric_bill", y, m)

    result = upload_streak(session, cid)
    assert result["streak_months"] == 3


def test_streak_excludes_this_month_even_if_filled(db):
    """이번 달은 아직 안 끝났으니 채워져 있어도 스트릭에 안 잡힌다."""
    session, cid, inst_id = db
    now = datetime.now(timezone.utc)
    _add_doc(session, cid, inst_id, "gas_bill", now.year, now.month)
    _add_doc(session, cid, inst_id, "electric_bill", now.year, now.month)
    y, m = _shift(now.year, now.month, -1)
    _add_doc(session, cid, inst_id, "gas_bill", y, m)
    _add_doc(session, cid, inst_id, "electric_bill", y, m)

    result = upload_streak(session, cid)
    assert result["streak_months"] == 1


def test_streak_breaks_at_first_gap(db):
    session, cid, inst_id = db
    now = datetime.now(timezone.utc)
    y1, m1 = _shift(now.year, now.month, -1)
    _add_doc(session, cid, inst_id, "gas_bill", y1, m1)
    _add_doc(session, cid, inst_id, "electric_bill", y1, m1)
    # -2월은 통째로 결손, -3월은 다시 채움 — 스트릭은 -2월에서 끊겨야 한다.
    y3, m3 = _shift(now.year, now.month, -3)
    _add_doc(session, cid, inst_id, "gas_bill", y3, m3)
    _add_doc(session, cid, inst_id, "electric_bill", y3, m3)

    result = upload_streak(session, cid)
    assert result["streak_months"] == 1


def test_streak_requires_all_required_types_not_just_one(db):
    """도시가스만 올리고 전기고지서를 안 올리면 그 달은 '완료'로 안 친다."""
    session, cid, inst_id = db
    now = datetime.now(timezone.utc)
    y, m = _shift(now.year, now.month, -1)
    _add_doc(session, cid, inst_id, "gas_bill", y, m)

    result = upload_streak(session, cid)
    assert result["streak_months"] == 0


def test_streak_counts_electric_bill_even_before_fuel_check(db):
    """electric_bill은 연료 체크 여부와 무관하게 항상 필수라(required_documents),
    연료를 아직 안 골랐어도 전기고지서만 채워져 있으면 스트릭이 성립한다."""
    session, cid, inst_id = db
    company = session.get(Company, cid)
    company.fuel_types_json = None
    session.commit()
    now = datetime.now(timezone.utc)
    y, m = _shift(now.year, now.month, -1)
    _add_doc(session, cid, inst_id, "electric_bill", y, m)

    result = upload_streak(session, cid)
    assert result["streak_months"] == 1


def test_streak_ignores_not_applicable_document_types(db):
    """도시가스를 안 쓰는 기업은 gas_bill이 not_applicable이라 스트릭 판정에서
    빠진다 — electric_bill만 채우면 충분하다."""
    session, cid, inst_id = db
    company = session.get(Company, cid)
    company.fuel_types_json = {"city_gas": False, "electricity": True}
    session.commit()
    now = datetime.now(timezone.utc)
    y, m = _shift(now.year, now.month, -1)
    _add_doc(session, cid, inst_id, "electric_bill", y, m)

    result = upload_streak(session, cid)
    assert result["streak_months"] == 1
