"""우대금리 상품 매칭(db/rate_products.py) 골든 케이스.

핵심 검증축:
  - candidate_score가 상품의 min_data_quality_score를 충족하면 "eligible" — 구체적
    상품명·우대폭이 나온다(이전엔 "이미 최고 등급"을 표현할 데이터 자체가 없었다).
  - 충족 못 하면(4등급) 기존 quality_upgrade_candidate를 재사용해 "upgrade_needed" —
    benefit 문구에 목표 등급에서 자격을 얻을 상품명이 덧붙는다.
  - 활동자료 자체가 없으면(candidate_score=None) 카드 자체가 없다(기존과 동일).
  - 시드는 지어낸 금리가 아니라 iM뱅크 실제 상품(ESG Grow-Up 특별대출, K-택소노미
    그린 SME 대출) 2건을 참고한다.
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


def _add_voucher(session, cid, month, item, *, quantity=None, scope=1, k_taxonomy_lead=False, fuel_type="도시가스"):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000,
        raw_json={"quantity": quantity} if quantity is not None else {},
    )
    session.add(v)
    session.flush()
    # k_taxonomy_lead=True면 db/k_taxonomy.py::k_taxonomy_leads()가 찾는 필드
    # (finance_lead_type)를 직접 채운다 — 실제 룰 매칭 파이프라인을 안 태우고도
    # "이 회사는 K택소노미 설비 증거가 있다"를 가볍게 재현(이 테스트 파일의 기존
    # 관례처럼 Classification을 직접 구성).
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type=fuel_type,
        amount_krw=100000, emission_co2e=500.0, confidence=0.9,
        evidence="테스트", method="rule", status="auto",
        finance_lead_type="녹색여신 후보" if k_taxonomy_lead else None,
        k_taxonomy_facility_type="태양광 설비" if k_taxonomy_lead else None,
    ))
    session.commit()
    return v.id


def test_seed_creates_esg_growup_product_referencing_real_bank_product(db):
    """지어낸 금리가 아니라 iM뱅크 실제 상품을 참고했는지 — 상품명·출처 URL 확인."""
    session, _ = db
    product = session.query(RateProduct).filter_by(product_name="ESG Grow-Up 특별대출").one()
    assert product.provider_name == "iM뱅크"
    assert product.min_data_quality_score == 2
    assert "imbank.co.kr" in product.source_reference


def test_seed_creates_green_sme_loan_referencing_real_bond_issuance(db):
    """K-택소노미 그린 SME 대출도 iM뱅크가 실제 발행한 한국형 녹색채권(2025.9,
    1,100억원)을 참고했는지 — 상품명·출처 확인."""
    session, _ = db
    product = session.query(RateProduct).filter_by(product_name="K-택소노미 그린 SME 대출").one()
    assert product.provider_name == "iM뱅크"
    assert product.min_data_quality_score == 2
    assert "녹색채권" in product.source_reference


def test_full_year_measured_data_is_eligible(db):
    """12개월 전부 실측(energy_consumption, 2등급)이면 ESG Grow-Up 자격을 충족한다 —
    다수결로도, 약한 고리 원칙으로도 2등급이 나오는 가장 단순한 사례. K-택소노미
    그린 SME 대출은 PCAF 등급만으로는 안 뜬다 — 이 회사는 K택소노미 설비 증거가
    없어서(requires_k_taxonomy_leads=True) 매칭에서 빠진다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    status = rate_product_status_for_scope(session, cid, YEAR, "scope_1")
    assert status["status"] == "eligible"
    assert status["candidate_score"] == 2
    product_names = {p["product_name"] for p in status["products"]}
    assert product_names == {"ESG Grow-Up 특별대출"}


def test_green_sme_loan_appears_only_with_k_taxonomy_evidence(db):
    """같은 2등급이어도 전표에 K택소노미 설비 증거(태양광 등)가 있어야 K-택소노미
    그린 SME 대출까지 같이 뜬다 — 두 상품이 항상 세트로 뜨던 문제(2026-08-15) 수정
    확인용."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    _add_voucher(session, cid, 1, "태양광 설비 설치", quantity=100, k_taxonomy_lead=True)

    status = rate_product_status_for_scope(session, cid, YEAR, "scope_1")
    assert status["status"] == "eligible"
    product_names = {p["product_name"] for p in status["products"]}
    assert product_names == {"ESG Grow-Up 특별대출", "K-택소노미 그린 SME 대출"}


def test_upgrade_needed_target_products_also_respect_k_taxonomy_gate(db):
    """upgrade_needed 상태의 target_products(목표 등급에서 자격을 얻을 상품)도
    같은 규칙을 따른다 — K택소노미 증거 없으면 ESG Grow-Up만 목표로 안내한다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=None)  # revenue, 4등급

    status = rate_product_status_for_scope(session, cid, YEAR, "scope_1")
    assert status["status"] == "upgrade_needed"
    target_names = {p["product_name"] for p in status["target_products"]}
    assert target_names == {"ESG Grow-Up 특별대출"}


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


def test_upgrade_needed_includes_structured_missing_items(db):
    """결손월은 프론트가 /owner/uploads 그리드로 바로 딥링크할 수 있게 문서종류·월
    단위로도 구조화돼 나온다(missing 문장과 별개, web/app/owner/benefits 소비 대상)."""
    session, cid = db
    for m in (1, 2, 3):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    status = rate_product_status_for_scope(session, cid, YEAR, "scope_1")
    assert status["status"] == "upgrade_needed"
    assert status["missing_items"] == [
        {"document_type": "gas_bill", "fuel_label": "가스", "months": list(range(4, 13))}
    ]


def test_no_activity_data_yields_no_status(db):
    """활동자료 자체가 없으면 카드가 아예 없다(None) — 추정으로 채우지 않는다."""
    session, cid = db
    assert rate_product_status_for_scope(session, cid, YEAR, "scope_1") is None


def test_status_for_company_returns_up_to_two_scopes(db):
    """Scope1(실측)·Scope2(수량 없음) 둘 다 활동자료가 있으면 각각 독립 판정돼 2건 나온다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1)
        _add_voucher(session, cid, m, "전기요금", quantity=None, scope=2, fuel_type="전기")

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
