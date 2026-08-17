"""K택소노미·설비투자 리드 (v1 §6 2주차) 골든 케이스.

핵심 검증축:
  - 회계 매핑(k_taxonomy_mapping)이 기존 룰(R051~R058, R031, R032)과 linked_rule_id로
    정확히 연결된다 — 새 키워드 매칭 로직 없이 참조만 한다.
  - K택소노미 매칭 대상이 아닌 rule_id(예: 일반 도시가스 R011)는 전부 None/False다.
  - classify_vouchers()가 실제로 Classification에 K택소노미 필드를 채운다.
  - 배출량 계산(activity_amount/emission_co2e)은 K택소노미 필드와 무관하게 그대로 동작한다
    (원문: "배출량 계산 대상 아니나 녹색여신 참고" — 계산 파이프라인을 건드리지 않았는지 확인).
  - finance_lead_type이 채워져도 그 자체로 여신 결정이 아니다(상태는 그대로 룰의
    auto_action에 따른 status만 반영 — CLAUDE.md §9).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.agent.tools import classify_vouchers
from db.excel_loader import load_classification_rules, load_k_taxonomy_mapping
from db.init_db import seed_emission_factors, seed_industry_distributions, seed_unit_prices
from db.pcaf_engine.k_taxonomy import k_taxonomy_fields_for_rule, k_taxonomy_leads, k_taxonomy_leads_for_company
from db.models import Base, Classification, Company, Voucher

RULES = load_classification_rules()
MAPPING = load_k_taxonomy_mapping()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_voucher(session, cid, item, *, month=1):
    v = Voucher(
        company_id=cid, source="hometax", year=2025, month=month,
        supplier_name="테스트", item_description=item, supply_amount_krw=1_000_000,
    )
    session.add(v)
    session.commit()
    return v.id


# ── 매핑표 자체 무결성 ────────────────────────────────────────────────────────
def test_every_mapping_links_to_existing_rule():
    """k_taxonomy_mapping.linked_rule_id가 전부 실제 존재하는 rule_id를 가리킨다
    — 매핑표와 룰표가 어긋나면(회계 갱신 누락 등) 여기서 바로 드러난다."""
    rule_ids = {r["rule_id"] for r in RULES}
    for m in MAPPING:
        assert m["linked_rule_id"] in rule_ids, f"{m['kt_rule_id']}이 존재하지 않는 rule_id({m['linked_rule_id']})를 가리킴"


def test_mapping_covers_nine_kt_rules():
    """회계가 준비한 9개 KT 매핑(KT001~KT009)이 그대로 로드된다."""
    kt_ids = {m["kt_rule_id"] for m in MAPPING}
    assert kt_ids == {f"KT{i:03d}" for i in range(1, 10)}


# ── db/k_taxonomy.py 순수 로직 ───────────────────────────────────────────────
def test_k_taxonomy_fields_for_solar_rule():
    fields = k_taxonomy_fields_for_rule("R051")
    assert fields["k_taxonomy_candidate_type"] == "재생에너지 설비"
    assert fields["k_taxonomy_facility_type"] == "태양광 설비"
    assert fields["finance_lead_type"] == "녹색여신 후보"
    assert fields["k_taxonomy_hitl_required"] is True


def test_k_taxonomy_fields_for_cnc_rule_hitl_not_required():
    """R032(CNC 장비구매)는 매핑표에서 hitl_required=False로 명시돼 있다 —
    "최종판정 아님" 주석이 있지만 이 필드 자체는 회계가 정한 값을 그대로 반영한다."""
    fields = k_taxonomy_fields_for_rule("R032")
    assert fields["finance_lead_type"] == "설비금융 후보"
    assert fields["k_taxonomy_hitl_required"] is False


def test_k_taxonomy_fields_empty_for_unrelated_rule():
    """일반 도시가스 룰(K택소노미 매핑에 없는 rule_id)은 전부 None/False다 —
    절대다수의 배출량 계산 전표가 이 경로를 탄다."""
    fields = k_taxonomy_fields_for_rule("R011")
    assert fields["k_taxonomy_candidate_type"] is None
    assert fields["k_taxonomy_facility_type"] is None
    assert fields["finance_lead_type"] is None
    assert fields["k_taxonomy_hitl_required"] is False


def test_k_taxonomy_fields_empty_for_none_rule_id():
    """rule_id 자체가 없으면(LLM 경로) 안전하게 빈 필드를 반환한다."""
    fields = k_taxonomy_fields_for_rule(None)
    assert fields["finance_lead_type"] is None


# ── classify_vouchers() 통합 — 실제 Classification에 필드가 채워지는지 ─────────
def test_classify_vouchers_fills_k_taxonomy_fields_for_solar_panel(db):
    session, cid = db
    vid = _add_voucher(session, cid, "태양광 설비 설치")

    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=vid).one()
    assert c.k_taxonomy_candidate_type == "재생에너지 설비"
    assert c.k_taxonomy_facility_type == "태양광 설비"
    assert c.finance_lead_type == "녹색여신 후보"
    assert c.k_taxonomy_hitl_required is True
    assert c.category == "감축투자 후보"


def test_classify_vouchers_leaves_k_taxonomy_fields_empty_for_normal_fuel(db):
    """일반 연료 전표(도시가스)는 K택소노미 필드가 전부 비어 있다 — 회귀 방지."""
    session, cid = db
    vid = _add_voucher(session, cid, "도시가스 요금")

    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=vid).one()
    assert c.k_taxonomy_candidate_type is None
    assert c.finance_lead_type is None
    assert c.k_taxonomy_hitl_required is False


def test_classify_vouchers_calc_engine_unaffected_by_k_taxonomy(db):
    """K택소노미 매칭 전표(태양광 등)는 배출량 계산 대상이 아니므로 R051이
    scope=None으로 매칭되고, activity_amount/emission_co2e도 그에 맞게 비어 있다
    — 계산 파이프라인(도구③)이 K택소노미 필드 추가로 깨지지 않았는지 확인."""
    session, cid = db
    vid = _add_voucher(session, cid, "태양광 설비 설치")

    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=vid).one()
    assert c.scope is None
    assert c.emission_co2e in (None, 0, 0.0)


def test_classify_vouchers_normal_fuel_calc_engine_still_works(db):
    """일반 연료 전표(도시가스, 수량 있음)는 기존과 동일하게 배출량이 계산된다 —
    K택소노미 필드 추가가 기존 계산 로직을 깨지 않는다(v1-plan §6 완료조건)."""
    session, cid = db
    v = Voucher(
        company_id=cid, source="hometax", year=2025, month=1,
        supplier_name="테스트", item_description="도시가스",
        supply_amount_krw=1_000_000, raw_json={"quantity": 500},
    )
    session.add(v)
    session.commit()

    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=v.id).one()
    assert c.scope == 1
    assert c.emission_co2e is not None and c.emission_co2e > 0


# ── k_taxonomy_leads() / k_taxonomy_leads_for_company() — 사장님 리포트용 조회 ──────
def test_k_taxonomy_leads_filters_by_company_id(db):
    """company_id를 주면 그 기업의 리드만 반환한다 — 관리자용 전체 조회(company_id
    생략)는 기존 그대로 동작해야 한다(하위호환)."""
    session, cid = db
    _add_voucher(session, cid, "태양광 설비 설치")

    other = Company(name="타사", industry_code="C251")
    session.add(other)
    session.commit()
    _add_voucher(session, other.id, "ESS 구매")

    classify_vouchers(session, cid)
    classify_vouchers(session, other.id)

    all_leads = k_taxonomy_leads(session)
    assert {lead["company_id"] for lead in all_leads} == {cid, other.id}

    only_cid = k_taxonomy_leads(session, company_id=cid)
    assert {lead["company_id"] for lead in only_cid} == {cid}


def test_k_taxonomy_leads_for_company_groups_same_facility_across_months(db):
    """같은 설비가 여러 달 전표로 나뉘어 잡혀도 사장님 화면엔 한 건으로 묶인다."""
    session, cid = db
    _add_voucher(session, cid, "태양광 설비 설치 1차", month=3)
    _add_voucher(session, cid, "태양광 설비 설치 2차", month=5)
    _add_voucher(session, cid, "태양광 설비 설치 3차", month=7)

    classify_vouchers(session, cid)

    leads = k_taxonomy_leads_for_company(session, cid)
    assert len(leads) == 1
    lead = leads[0]
    assert lead["k_taxonomy_facility_type"] == "태양광 설비"
    assert lead["occurrence_count"] == 3
    assert lead["voucher_month"] == 7  # 가장 최근 달이 대표값
    assert lead["item_description"] == "태양광 설비 설치 3차"


def test_k_taxonomy_leads_for_company_hint_is_plain_language(db):
    """finance_lead_type이 은행 내부 어휘 그대로가 아니라 사장님 눈높이 문구(hint)로
    번역돼 나온다. 은행 내부 신호(hitl_required 등)는 반환 dict에 없어야 한다."""
    session, cid = db
    _add_voucher(session, cid, "태양광 설비 설치")

    classify_vouchers(session, cid)

    leads = k_taxonomy_leads_for_company(session, cid)
    assert len(leads) == 1
    lead = leads[0]
    assert lead["finance_lead_type"] == "녹색여신 후보"
    assert "녹색여신" in lead["hint"]
    assert "k_taxonomy_hitl_required" not in lead
    assert "gap_count" not in lead
    assert "company_id" not in lead


def test_k_taxonomy_leads_for_company_empty_for_normal_fuel(db):
    """K택소노미 매칭이 없는 기업은 빈 리스트 — 대다수 기업의 정상 상태."""
    session, cid = db
    _add_voucher(session, cid, "도시가스 요금")

    classify_vouchers(session, cid)

    assert k_taxonomy_leads_for_company(session, cid) == []
