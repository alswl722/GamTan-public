"""우대금리 상품 매칭(db/rate_products.py) 골든 케이스.

핵심 검증축:
  - candidate_score가 상품의 min_data_quality_score를 충족하면 "eligible" — 구체적
    상품명·우대폭이 나온다(이전엔 "이미 최고 등급"을 표현할 데이터 자체가 없었다).
  - 충족 못 하면(4등급) 기존 quality_upgrade_candidate를 재사용해 "upgrade_needed" —
    benefit 문구에 목표 등급에서 자격을 얻을 상품명이 덧붙는다.
  - 활동자료 자체가 없으면(candidate_score=None) 카드 자체가 없다(기존과 동일).
  - 시드는 지어낸 금리가 아니라 iM뱅크 실제 상품(ESG Grow-Up 특별대출)을 참고한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.init_db import seed_pcaf_quality_rules, seed_rate_products
from db.models import Base, Classification, Company, RateProduct, Voucher
from db.rate_products import rate_product_status_for_company, rate_product_status_for_scope

YEAR = 2026


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_pcaf_quality_rules(session)
        seed_rate_products(session)
        # 도시가스+전기만 쓰는 회사로 고정 — 약한 고리 원칙 아래서 안 쓰는 연료 버킷이
        # 결손으로 잡히는 걸 피한다(db/pcaf_quality.py::_selected_fuels 참고).
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            fuel_types_json={"city_gas": True, "electricity": True},
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_voucher(session, cid, month, item, *, quantity=None, scope=1):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000,
        raw_json={"quantity": quantity} if quantity is not None else {},
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=500.0, confidence=0.9,
        evidence="테스트", method="rule", status="auto",
    ))
    session.commit()
    return v.id


def test_seed_creates_esg_growup_product_referencing_real_bank_product(db):
    """지어낸 금리가 아니라 iM뱅크 실제 상품을 참고했는지 — 상품명·출처 URL 확인."""
    session, _ = db
    product = session.query(RateProduct).one()
    assert product.product_name == "ESG Grow-Up 특별대출"
    assert product.provider_name == "iM뱅크"
    assert product.min_data_quality_score == 2
    assert "imbank.co.kr" in product.source_reference


def test_full_year_measured_data_is_eligible(db):
    """12개월 전부 실측(energy_consumption, 2등급)이면 이미 상품 자격을 충족한다 —
    다수결로도, 약한 고리 원칙으로도 2등급이 나오는 가장 단순한 사례."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    status = rate_product_status_for_scope(session, cid, YEAR, "scope_1")
    assert status["status"] == "eligible"
    assert status["candidate_score"] == 2
    assert len(status["products"]) == 1
    assert status["products"][0]["product_name"] == "ESG Grow-Up 특별대출"
    assert status["products"][0]["rate_discount_pct"] == 0.30


def test_revenue_dominant_scope_needs_upgrade(db):
    """수량 없는(revenue, 4등급) 전표만 있으면 아직 상품 자격이 없다 — 기존
    quality_upgrade_candidate를 재사용한 upgrade_needed 상태, benefit에 상품명이 붙는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=None)

    status = rate_product_status_for_scope(session, cid, YEAR, "scope_1")
    assert status["status"] == "upgrade_needed"
    assert status["current_grade"] == 4
    assert status["target_grade"] == 2
    assert "ESG Grow-Up 특별대출" in status["benefit"]


def test_no_activity_data_yields_no_status(db):
    """활동자료 자체가 없으면 카드가 아예 없다(None) — 추정으로 채우지 않는다."""
    session, cid = db
    assert rate_product_status_for_scope(session, cid, YEAR, "scope_1") is None


def test_status_for_company_returns_up_to_two_scopes(db):
    """Scope1(실측)·Scope2(수량 없음) 둘 다 활동자료가 있으면 각각 독립 판정돼 2건 나온다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1)
        _add_voucher(session, cid, m, "전기요금", quantity=None, scope=2)

    results = rate_product_status_for_company(session, cid, YEAR)
    by_scope = {r["scope_group"]: r for r in results}
    assert len(results) == 2
    assert by_scope["scope_1"]["status"] == "eligible"
    assert by_scope["scope_2"]["status"] == "upgrade_needed"


def test_no_matching_product_falls_back_to_upgrade_path_even_at_score_2(db):
    """seed_rate_products가 비어 있으면(상품 참조 테이블 자체가 없는 상태) 2등급이어도
    eligible이 될 수 없다 — quality_upgrade_candidate도 등급 4가 아니라 None을 반환하므로
    결국 카드 자체가 없다(추정으로 채우지 않는다)."""
    session, cid = db
    session.query(RateProduct).delete()
    session.commit()
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    assert rate_product_status_for_scope(session, cid, YEAR, "scope_1") is None
