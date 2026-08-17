"""PCAF 데이터 품질 후보(db/pcaf_quality.py) 골든 케이스.

PCAF Standard Part A Third Edition, Table 10.1-2(Annex p.192) 원문 옵션 체계
(1a/1b/2a/2b/3a/3b/3c)를 기준으로 검증한다.

핵심 검증축:
  - 분류 신뢰도(HITL)와 PCAF 품질점수는 완전히 분리된 축이다(§6.1, §6.4).
  - 활동자료 근거(생산량 vs 매출 환산)에 따라 다른 옵션이 매칭된다.
  - 완전성(completeness_pct)과 품질 후보(candidate_score)는 서로 다른 필드·다른 계산 경로다.
  - Scope 1과 Scope 2는 서로 다른 배출원(가스·경유 vs 전기)이라 독립적으로 집계·평가된다
    (PR #25 리뷰 CONFIRMED 수정 — 이전에는 한데 묶여 서로의 점수를 오염시켰다).
  - Scope 1·2와 Scope 3는 원문상 같은 옵션 체계를 공유하되(별도 표 없음), 이 프로젝트가
    Scope 3 데이터를 아직 만들지 않아 결과가 갈린다 — 0으로 합산되지 않는다.
  - status는 항상 "candidate" — 자동 승인되지 않는다(CLAUDE.md §9).
  - 판정 근거(basis)는 DB(candidate_quality_basis_json)에 영구 저장되고 GET으로 복원된다
    (PR #25 리뷰 CONFIRMED 수정 — 이전에는 evaluate 응답에만 실리고 저장되지 않았다).
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.init_db import seed_pcaf_quality_rules
from db.models import (
    Base,
    Classification,
    Company,
    FinancialInstitution,
    OrganizationalBoundary,
    Voucher,
)
from db.pcaf_quality import (
    aggregate_scope_emissions,
    assess_borrower_emission_quality,
    assess_inventory_completeness,
    classify_activity_data_method,
    scope_emission_detail,
)

YEAR = 2026


@pytest.fixture()
def db(tmp_path):
    # TestClient가 별도 스레드에서 같은 세션을 쓰므로(:memory:는 스레드 간 공유 불가)
    # 파일 DB로 연결을 공유한다 — tests/test_admin.py의 db 픽스처와 동일 패턴.
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_pcaf_quality_rules(session)
        # 도시가스+전기만 쓰고 경유는 안 쓰는 회사로 고정 — 안 그러면 약한 고리 원칙
        # 아래서 한 번도 안 쓴 경유 버킷의 12개월이 전부 "결손"으로 잡혀 모든 테스트가
        # 실측 데이터 품질과 무관하게 revenue(4등급)로 떨어진다(_selected_fuels 참고).
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            fuel_types_json={"city_gas": True, "electricity": True},
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_voucher(session, cid, month, item, *, quantity=None, scope=1, status="auto", fuel_type="도시가스"):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000,
        raw_json={"quantity": quantity} if quantity is not None else {},
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type=fuel_type,
        amount_krw=100000, emission_co2e=500.0, confidence=0.9,
        evidence="테스트", method="rule", status=status,
    ))
    session.commit()
    return v.id


# ── PCAF 시드 데이터 자체가 원문과 일치하는지 ────────────────────────────────
def test_seed_creates_seven_options_matching_table_10_1_2(db):
    """Table 10.1-2 원문의 7개 옵션(1a/1b/2a/2b/3a/3b/3c)이 정확한 점수로 적재된다."""
    from db.models import PcafQualityRule
    session, _ = db
    rules = {r.option_code: r for r in session.query(PcafQualityRule).all()}

    assert set(rules) == {"1a", "1b", "2a", "2b", "3a", "3b", "3c"}
    assert rules["1a"].quality_score == 1 and rules["1a"].activity_data_basis == "verified_emissions"
    assert rules["1b"].quality_score == 2 and rules["1b"].activity_data_basis == "unverified_emissions"
    assert rules["2a"].quality_score == 2 and rules["2a"].activity_data_basis == "energy_consumption"
    assert rules["2b"].quality_score == 3 and rules["2b"].activity_data_basis == "production"
    assert rules["3a"].quality_score == 4 and rules["3a"].activity_data_basis == "revenue"
    assert rules["3b"].quality_score == 5 and rules["3b"].activity_data_basis == "assets"
    assert rules["3c"].quality_score == 5 and rules["3c"].activity_data_basis == "asset_turnover_ratio"


def test_option_2a_does_not_apply_to_scope3(db):
    """원문 각주 208 — Option 2a(에너지 소비량)는 Scope 3에 적용 불가."""
    from db.models import PcafQualityRule
    session, _ = db
    rule_2a = session.query(PcafQualityRule).filter_by(option_code="2a").one()
    rule_2b = session.query(PcafQualityRule).filter_by(option_code="2b").one()
    assert rule_2a.applies_to_scope3 is False
    assert rule_2b.applies_to_scope3 is True


# ── classify_activity_data_method ───────────────────────────────────────────
def test_energy_consumption_basis_when_voucher_has_measured_quantity(db):
    """전표에 실측 수량이 있으면 energy_consumption(Option 2a) — 전기 kWh·가스 m³·경유 L는
    전부 에너지원별 소비량이지 생산 실적(2b)이 아니다(Table 10.1-2 원문 예시 대조)."""
    session, cid = db
    vid = _add_voucher(session, cid, 1, "도시가스", quantity=100)
    voucher = session.query(Voucher).filter_by(id=vid).one()
    classification = voucher.classification
    assert classify_activity_data_method(voucher, classification) == "energy_consumption"


def test_revenue_basis_when_voucher_has_no_quantity(db):
    """수량 없이 금액만 있으면 revenue(경제자료 환산) — 3등급 고정이 아니라 근거 라벨일 뿐."""
    session, cid = db
    vid = _add_voucher(session, cid, 1, "유류대금")
    voucher = session.query(Voucher).filter_by(id=vid).one()
    classification = voucher.classification
    assert classify_activity_data_method(voucher, classification) == "revenue"


# ── assess_inventory_completeness ───────────────────────────────────────────
def test_completeness_pct_separate_from_candidate_score(db):
    """완전성(§6.3)과 품질 후보(§6.4)는 서로 다른 필드·경로 — 완전성 계산이 품질점수에 직접 곱해지지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    completeness = assess_inventory_completeness(session, cid, YEAR, "scope_1")
    quality = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")

    assert completeness.completeness_pct == quality["completeness_pct"]
    assert "candidate_score" not in completeness.__dict__
    assert quality["candidate_score"] is not None


def test_missing_months_reported_by_fuel(db):
    """일부 월만 채워진 경우 결손월이 연료별로 정확히 집계된다.

    as_of를 연말로 고정한다 — YEAR(2026)가 실행 시점의 달력상 올해와 같을 때
    assess_inventory_completeness가 "아직 안 온 달"을 결손에서 빼는 로직(실측
    2026-08-17)에 걸려, 실행하는 달에 따라 기대값이 달라지는 걸 막기 위함."""
    session, cid = db
    for m in (1, 2, 3):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    completeness = assess_inventory_completeness(
        session, cid, YEAR, "scope_1", as_of=datetime(YEAR, 12, 31, tzinfo=timezone.utc)
    )
    assert completeness.missing_months["가스"] == list(range(4, 13))


def test_scope1_and_scope2_completeness_are_independent(db):
    """Scope 1(가스, 경유/유류)과 Scope 2(전기) 완전성은 서로 다른 슬롯 기준으로 독립
    집계된다(PR #25 리뷰 CONFIRMED — 이전에는 연료 구분 없이 한데 묶여 집계됐다).
    db 픽스처의 회사는 도시가스+전기만 선택했으므로(경유 미선택) Scope 1 슬롯은
    가스 하나뿐이다 — 도시가스 12개월을 다 채우면 100%, Scope 2(전기)는 데이터가
    아예 없어 0%다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)  # Scope 1(가스)만 채움

    scope1 = assess_inventory_completeness(session, cid, YEAR, "scope_1")
    scope2 = assess_inventory_completeness(session, cid, YEAR, "scope_2")

    assert scope1.completeness_pct == 100.0
    assert scope2.completeness_pct == 0.0
    assert scope1.activity_basis_breakdown
    assert not scope2.activity_basis_breakdown


def test_other_bucket_vouchers_excluded_from_both_completeness_and_basis(db):
    """어느 연료 버킷에도 안 잡히는(기타) 전표는 completeness와 activity_basis_breakdown
    양쪽에서 동일하게 제외된다 — 리포트에 안 보이는 전표가 옵션 코드 선택에는 영향을
    주는 근거-결과 불일치를 막는다(PR #25 리뷰)."""
    session, cid = db
    _add_voucher(session, cid, 1, "사무용품비", quantity=100, fuel_type="사무용품")  # 어느 버킷에도 안 잡힘

    completeness = assess_inventory_completeness(session, cid, YEAR, "scope_1")
    assert completeness.months_covered == 0
    assert not completeness.activity_basis_breakdown


def test_fuel_bucket_uses_classification_fuel_type_not_item_description_text(db):
    """실측(2026-08-17, 사장님 탄소리포트) — 전기요금 이메일 청구서 업로드 건이
    월별 추이 차트(db/pcaf.py, Classification.scope를 신뢰)엔 뜨는데 이 화면의
    Scope 카드엔 "활동자료 없음"으로 나오는 불일치가 발견됐다. 원인은 이 모듈이
    분류 엔진이 이미 확정한 Classification.fuel_type을 무시하고 Voucher.
    item_description 원문을 키워드로 재해석했던 것 — 원문 표현이 예상 밖이면
    (letter-spacing 등) 키워드가 하나도 안 걸려 조용히 "기타"로 빠졌다.
    item_description에 "전기" 관련 키워드가 전혀 없어도(letter-spacing 재현:
    "전 기 요 금"), Classification.fuel_type="전기"만 정확하면 scope_2로
    잡혀야 한다."""
    session, cid = db
    _add_voucher(session, cid, 7, "전 기 요 금 (산업용 을)", scope=2, fuel_type="전기")

    completeness = assess_inventory_completeness(session, cid, YEAR, "scope_2")
    assert completeness.months_covered == 1
    assert completeness.activity_basis_breakdown

    emissions = aggregate_scope_emissions(session, cid, YEAR, "scope_2")
    assert emissions["emission_tco2e"] is not None and emissions["emission_tco2e"] > 0


# ── assess_borrower_emission_quality — 활동자료 근거별 옵션 매칭 ─────────────
def test_energy_consumption_data_scores_higher_than_revenue_estimate(db):
    """에너지 소비량 기반(2a, Score 2)이 매출 환산(3a, Score 4)보다 높은 품질(작은 숫자)로 평가된다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    energy_result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")

    company2 = Company(name="타사", industry_code="C251")
    session.add(company2)
    session.commit()
    for m in range(1, 13):
        _add_voucher(session, company2.id, m, "유류대금", fuel_type="경유")
    revenue_result = assess_borrower_emission_quality(session, company2.id, YEAR, "scope_1")

    assert energy_result["candidate_score"] < revenue_result["candidate_score"]
    assert energy_result["option_code"] == "2a"
    assert energy_result["candidate_score"] == 2
    assert revenue_result["option_code"] == "3a"
    assert revenue_result["candidate_score"] == 4


def test_single_revenue_voucher_drags_whole_scope_down_weakest_link(db):
    """약한 고리 원칙 — 12개월 중 11개월이 실측(energy_consumption)이어도 단 1개월만
    수량 없는(revenue) 전표면 그 Scope 전체가 revenue(3a)로 떨어진다. 다수결이었다면
    2a가 나왔을 상황이라 이 회귀를 직접 검증한다."""
    session, cid = db
    for m in range(1, 12):  # 11개월 energy_consumption
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    _add_voucher(session, cid, 12, "도시가스")  # 1개월만 수량 없음(revenue)

    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")
    assert result["option_code"] == "3a"
    assert result["candidate_score"] == 4


def test_gap_alone_drags_scope_down_even_with_all_measured_data(db):
    """약한 고리 원칙 — 있는 데이터는 전부 실측(energy_consumption)이어도 결손월이
    있으면(9~12월 미연동) 전체 Scope가 revenue(3a) 수준으로 떨어진다. 완전성이
    16.7%여도 다수결로는 최고 등급이 나왔던 사례(구미정밀 실사용 중 발견)의 회귀
    테스트다.

    as_of를 연말로 고정한다 — 9~12월을 "아직 안 온 달이라 결손 아님"이 아니라
    "미연동 결손"으로 판정시키려면 연도가 이미 다 지난 시점이어야 한다(실측
    2026-08-17 로직 변경 참고, assess_inventory_completeness 참고)."""
    session, cid = db
    for m in range(1, 9):  # 8개월만 존재, 전부 실측 — 9~12월은 결손
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    result = assess_borrower_emission_quality(
        session, cid, YEAR, "scope_1", as_of=datetime(YEAR, 12, 31, tzinfo=timezone.utc)
    )
    assert result["option_code"] == "3a"
    assert result["candidate_score"] == 4
    assert any("약한 고리" in lim for lim in result["limitations"])


def test_scope1_basis_not_polluted_by_scope2_data(db):
    """Scope 2(전기)가 revenue 기반이어도 Scope 1(가스, energy_consumption 기반) 점수는
    영향받지 않는다 — PR #25 리뷰가 지적한 Scope 오염 버그의 회귀 테스트."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)  # Scope 1: energy_consumption
    for m in range(1, 13):
        _add_voucher(session, cid, m, "전기요금", scope=2, fuel_type="전기")  # Scope 2: revenue(수량 없음)

    scope1 = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")
    scope2 = assess_borrower_emission_quality(session, cid, YEAR, "scope_2")

    assert scope1["option_code"] == "2a"
    assert scope1["candidate_score"] == 2
    assert scope2["option_code"] == "3a"
    assert scope2["candidate_score"] == 4


# ── HITL 분리 (§6.1) ─────────────────────────────────────────────────────────
def test_hitl_review_required_does_not_change_quality_score(db):
    """분류 신뢰도(status=review_required)가 있어도 PCAF 품질점수 계산 로직은 이를 참조하지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, status="review_required")

    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")
    assert result["candidate_score"] is not None
    assert result["option_code"] == "2a"


# ── Scope 분리 ────────────────────────────────────────────────────────────────
def test_scope_1_2_and_scope_3_assessed_separately(db):
    """Scope 1·2와 Scope 3는 독립적으로 평가되며 서로 점수를 공유하지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    s1 = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")
    s3 = assess_borrower_emission_quality(session, cid, YEAR, "scope_3")

    assert s1["scope_group"] == "scope_1"
    assert s3["scope_group"] == "scope_3"
    assert s1["candidate_score"] is not None
    assert s3["candidate_score"] is None  # 이 프로젝트가 Scope 3 데이터를 만들지 않음


def test_scope3_not_calculated_not_treated_as_zero(db):
    """Scope 3 미산정은 candidate_score=None 으로만 표시되고 0으로 합산되지 않는다."""
    session, cid = db
    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_3")
    assert result["candidate_score"] is None
    assert result["candidate_score"] != 0
    assert result["limitations"]


# ── status 불변식 (CLAUDE.md §9) ─────────────────────────────────────────────
def test_status_always_candidate_never_auto_approved(db):
    """자동 산정 결과는 항상 candidate — 은행 담당자 승인 전에는 확정하지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    for scope_group in ("scope_1", "scope_2", "scope_3"):
        result = assess_borrower_emission_quality(session, cid, YEAR, scope_group)
        assert result["status"] == "candidate"
        assert result["bank_review_required"] is True


def test_no_activity_data_yields_no_candidate_with_limitation(db):
    """분류가 아예 없으면 candidate_score=None + 명확한 사유를 반환(추정으로 채우지 않음)."""
    session, cid = db
    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")
    assert result["candidate_score"] is None
    assert result["limitations"]


# ── aggregate_scope_emissions (v1 §4 "인벤토리 완전성 집계") ─────────────────
def test_aggregate_scope_emissions_sums_kg_to_tco2e(db):
    """전표별 classifications의 emission_co2e(kg) 합산 → tCO2e — 실제 배출량 산출.
    BorrowerEmissionInventory.emission_tco2e를 채우는 유일한 계산 경로다."""
    session, cid = db
    for m in range(1, 4):  # 3개월 × 500.0 kgCO2e = 1500 kg = 1.5 tCO2e
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    result = aggregate_scope_emissions(session, cid, YEAR, "scope_1")
    assert result["emission_tco2e"] == 1.5
    assert result["scope3_status"] is None


def test_aggregate_scope_emissions_excludes_rejected_classifications(db):
    """담당자가 반려한 건은 신뢰할 수 없는 분류라 집계에서 제외한다
    (db/pcaf.py::_after_measured와 동일 규칙)."""
    session, cid = db
    _add_voucher(session, cid, 1, "도시가스", quantity=100, status="auto")
    _add_voucher(session, cid, 2, "도시가스", quantity=100, status="rejected")

    result = aggregate_scope_emissions(session, cid, YEAR, "scope_1")
    assert result["emission_tco2e"] == 0.5  # 1건만 반영(500kg)


def test_aggregate_scope_emissions_scope1_and_scope2_are_independent(db):
    """Scope 1(가스)과 Scope 2(전기)는 서로 다른 값으로 독립 집계된다."""
    session, cid = db
    _add_voucher(session, cid, 1, "도시가스", quantity=100, scope=1)
    _add_voucher(session, cid, 1, "전기요금", scope=2, fuel_type="전기")
    _add_voucher(session, cid, 2, "전기요금", scope=2, fuel_type="전기")

    scope1 = aggregate_scope_emissions(session, cid, YEAR, "scope_1")
    scope2 = aggregate_scope_emissions(session, cid, YEAR, "scope_2")
    assert scope1["emission_tco2e"] == 0.5
    assert scope2["emission_tco2e"] == 1.0


def test_aggregate_scope_emissions_no_data_yields_null_not_zero(db):
    """해당 Scope 전표가 아예 없으면 emission_tco2e=None — 0으로 채우지 않는다(원칙9)."""
    session, cid = db
    result = aggregate_scope_emissions(session, cid, YEAR, "scope_1")
    assert result["emission_tco2e"] is None


def test_aggregate_scope_emissions_scope3_always_null_not_calculated(db):
    """Scope 3는 이 프로젝트가 데이터를 만들지 않으므로 항상 None + not_calculated."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    result = aggregate_scope_emissions(session, cid, YEAR, "scope_3")
    assert result["emission_tco2e"] is None
    assert result["scope3_status"] == "not_calculated"


# ── scope_emission_detail — 사장님 리포트 Scope 카드 상세보기 ───────────────────
def test_scope_emission_detail_sums_match_aggregate(db):
    """상세 목록의 emission_co2e 합(kg)이 aggregate_scope_emissions의 tCO2e 합계와
    일치한다 — 두 함수가 동일한 필터를 쓰므로 카드 숫자와 상세 목록이 항상 맞아야 함."""
    session, cid = db
    for m in range(1, 4):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    aggregate = aggregate_scope_emissions(session, cid, YEAR, "scope_1")
    detail = scope_emission_detail(session, cid, YEAR, "scope_1")

    assert len(detail) == 3
    detail_sum_tco2e = round(sum(item["emission_co2e"] for item in detail) / 1000.0, 2)
    assert detail_sum_tco2e == aggregate["emission_tco2e"]


def test_scope_emission_detail_excludes_rejected(db):
    """반려된 건은 카드 합계에서 빠지는 것과 마찬가지로 상세 목록에서도 빠진다."""
    session, cid = db
    _add_voucher(session, cid, 1, "도시가스", quantity=100, status="auto")
    _add_voucher(session, cid, 2, "도시가스", quantity=100, status="rejected")

    detail = scope_emission_detail(session, cid, YEAR, "scope_1")
    assert len(detail) == 1
    assert detail[0]["month"] == 1


def test_scope_emission_detail_scope1_and_scope2_are_independent(db):
    session, cid = db
    _add_voucher(session, cid, 1, "도시가스", quantity=100, scope=1)
    _add_voucher(session, cid, 1, "전기요금", scope=2, fuel_type="전기")

    scope1 = scope_emission_detail(session, cid, YEAR, "scope_1")
    scope2 = scope_emission_detail(session, cid, YEAR, "scope_2")
    assert [item["item_description"] for item in scope1] == ["도시가스"]
    assert [item["item_description"] for item in scope2] == ["전기요금"]


def test_scope_emission_detail_scope3_returns_empty_list(db):
    """Scope 3는 이 프로젝트가 데이터를 만들지 않으므로 빈 리스트."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    assert scope_emission_detail(session, cid, YEAR, "scope_3") == []


def test_scope_emission_detail_includes_voucher_fields_for_export_reuse(db):
    """추후 탄소 리포트 내보내기가 재사용할 필드(전표ID·품목·공급자·금액·상태)가 그대로 있다."""
    session, cid = db
    _add_voucher(session, cid, 5, "도시가스", quantity=100)

    detail = scope_emission_detail(session, cid, YEAR, "scope_1")
    assert len(detail) == 1
    item = detail[0]
    assert item["voucher_id"] is not None
    assert item["month"] == 5
    assert item["item_description"] == "도시가스"
    assert item["supply_amount_krw"] == 100000
    assert item["emission_co2e"] == 500.0
    assert item["status"] == "auto"


# ── build_quality_evidence ───────────────────────────────────────────────────
def test_quality_evidence_includes_rule_source_reference(db):
    """basis에 적용 옵션의 원문 근거(source_reference)가 포함된다 — 판정 근거 역추적 가능."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1")
    assert any("Table 10.1-2" in b for b in result["basis"])
    assert any("2a" in b for b in result["basis"])


# ── API 라우터 (evaluate 저장·버전 체인) ──────────────────────────────────────
@pytest.fixture()
def api_client(db):
    from fastapi.testclient import TestClient
    from api.db import get_session
    from api.main import app

    session, cid = db
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    boundary = OrganizationalBoundary(
        financial_institution_id=inst.id, company_id=cid, reporting_year=YEAR,
        boundary_type="operational_control", consolidation_scope="separate",
    )
    session.add(boundary)
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app), session, cid
    app.dependency_overrides.clear()


def test_evaluate_endpoint_persists_and_versions(api_client):
    """POST evaluate가 Scope 1·2 인벤토리 행을 저장하고, 재호출 시 버전이 증가한다."""
    client, session, cid = api_client

    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    res1 = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert res1.status_code == 200, res1.text
    assessments1 = res1.json()["assessments"]
    assert {a["scope_group"] for a in assessments1} == {"scope_1", "scope_2"}
    assert all(a["version"] == 1 for a in assessments1)
    assert all(a["status"] == "draft" for a in assessments1)

    res2 = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert res2.status_code == 200, res2.text
    assert all(a["version"] == 2 for a in res2.json()["assessments"])

    get_res = client.get(f"/borrowers/{cid}/quality-assessments/{YEAR}")
    assert get_res.status_code == 200
    assert all(a["version"] == 2 for a in get_res.json()["assessments"])


def test_evaluate_endpoint_persists_emission_tco2e(api_client):
    """evaluate가 candidate_quality_score뿐 아니라 실제 연간 Scope 배출량
    (emission_tco2e)도 함께 계산·저장한다 — v1 §4 "인벤토리 완전성 집계".
    전에는 emission_tco2e가 항상 null로 남아 있었다(docs/db-schema.md §17 노트)."""
    client, session, cid = api_client

    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)  # 12개월 × 500kg = 6.0 tCO2e

    res = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert res.status_code == 200, res.text
    scope1 = next(a for a in res.json()["assessments"] if a["scope_group"] == "scope_1")
    assert scope1["emission_tco2e"] == 6.0

    scope2 = next(a for a in res.json()["assessments"] if a["scope_group"] == "scope_2")
    assert scope2["emission_tco2e"] is None  # 전기 전표 없음 — 0이 아니라 null


def test_evaluate_basis_persisted_and_recoverable_via_get(api_client):
    """evaluate 응답의 basis(판정 근거)가 DB에 저장되고, 이후 GET으로도 동일하게
    조회된다 — PR #25 리뷰 CONFIRMED 수정(이전에는 응답에만 실리고 저장되지 않아
    GET이 항상 빈 배열을 반환했다)."""
    client, session, cid = api_client
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    post_res = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert post_res.status_code == 200, post_res.text
    scope1_post = next(a for a in post_res.json()["assessments"] if a["scope_group"] == "scope_1")
    assert scope1_post["basis"]  # POST 응답에 근거가 실림

    get_res = client.get(f"/borrowers/{cid}/quality-assessments/{YEAR}")
    assert get_res.status_code == 200
    scope1_get = next(a for a in get_res.json()["assessments"] if a["scope_group"] == "scope_1")
    assert scope1_get["basis"] == scope1_post["basis"]  # GET에서도 동일하게 복원됨(더 이상 빈 배열 아님)


def test_evaluate_saves_partial_scope_when_only_one_scope_has_data(api_client):
    """Scope 1만 데이터가 있어도 evaluate는 두 행을 모두 저장한다 — Scope 2는
    candidate_score=None + limitations로 결손 자체가 정보로 남는다(0으로 채우지 않음)."""
    client, session, cid = api_client
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)  # Scope 1만

    res = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert res.status_code == 200, res.text
    by_scope = {a["scope_group"]: a for a in res.json()["assessments"]}
    assert by_scope["scope_1"]["candidate_score"] is not None
    assert by_scope["scope_2"]["candidate_score"] is None
    assert by_scope["scope_2"]["limitations"]


def test_evaluate_without_boundary_fails_clearly(db):
    """조직경계 미등록 시 목업으로 채우지 않고 409로 명확히 실패한다."""
    from fastapi.testclient import TestClient
    from api.db import get_session
    from api.main import app

    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    try:
        res = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
        assert res.status_code == 409
    finally:
        app.dependency_overrides.clear()
