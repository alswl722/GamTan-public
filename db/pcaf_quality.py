"""PCAF 데이터 품질 후보 — Business Loans and Unlisted Equity 자산군 (읽기 전용 평가).

기존 db/pcaf.py(Classification 기반 임시 1~5등급)는 건드리지 않는다. 이 모듈은
PCAF Standard Part A Third Edition, Table 10.1-2(Annex p.192) 원문 옵션 체계
(1a/1b/2a/2b/3a/3b/3c)를 새 스키마(BorrowerEmissionInventory, PcafQualityRule)
기준으로 병행 구현한다.

⚠️ 이 모듈이 고치는 db/pcaf.py의 임시안 문제 (회계 검토로 확인됨):
  - "전표 실측 수량 = 2등급 고정"은 원문과 다르다. 원문 Option 2a(에너지 소비량,
    Score 2)와 2b(생산량, Score 3)는 별개 옵션이고, 애초에 "수량이 있다"는 사실
    만으로는 어느 옵션인지 정할 수 없다 — 이 프로젝트는 수량 단위를 구분하지
    않으므로 보수적으로 2b(생산량 기반, Score 3)로 취급한다(아래 설명 참고).
  - "금액→물량 환산 = 3등급 고정"도 원문과 다르다. 원문 Option 3a(매출 기반,
    Score 4)가 가장 가깝고, 3등급(Score 3)은 물리적 활동자료(2b) 몫이다.
  - "status='review_required' = 4등급"은 명백한 오류 — 분류 신뢰도(HITL)와 PCAF
    데이터 품질은 서로 다른 축이다(§6.1). 이 모듈의 함수들은
    Classification.confidence/status 를 입력으로 받지 않는다.
  - 원문은 Scope 1·2와 Scope 3에 별도 품질표를 두지 않는다. 옵션 체계는 공통이고
    Option 2a만 Scope 3 적용 불가(각주 208)하다 — "Scope 3 규칙은 완전히 별도"라는
    가정 자체가 이전 구현의 오류였다.

핵심 불변식:
  - status는 이 모듈에서 항상 "candidate" — 은행 담당자 승인 전에는 확정하지 않는다(CLAUDE.md §9).
  - Scope 3는 이 프로젝트가 실제로 데이터를 만들지 않으므로 candidate_score=None으로
    반환한다(0 합산 금지) — 이는 PCAF 옵션 체계의 제약이 아니라 이 프로젝트의 데이터
    가용성 한계다.
  - LLM 미호출 — PcafQualityRule 매칭과 completeness_pct 계산은 전부 결정론적 코드.

PR #25 리뷰 반영 (2026-08-12): 최초 버전은 연료 버킷(전기/가스/경유·유류) 구분 없이
회사·연도 전표를 전부 한데 묶어 activity_basis_breakdown을 집계했고, 그 결과 Scope 1과
Scope 2가 같은 dominant_basis/option_code를 받는 버그가 있었다(예: 경유 11개월 + 전기
1개월이 섞이면 전기 행이 경유 데이터에 좌우됨). _FUEL_BUCKET_SCOPE로 연료→Scope를
매핑해 Scope 1(가스·경유/유류)과 Scope 2(전기)를 분리 집계하도록 고쳤다.

v1 §4 "인벤토리 완전성 집계" (2026-08-12): aggregate_scope_emissions 추가 —
BorrowerEmissionInventory.emission_tco2e를 실제로 채우는 유일한 계산 경로. 전에는
candidate_quality_score(품질 후보 점수)만 채우고 emission_tco2e는 항상 null로
남아 있었다(docs/db-schema.md §17 노트).
"""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import BorrowerEmissionInventory, Classification, OrganizationalBoundary, PcafQualityRule, Voucher

_FUEL_BUCKET_SCOPE = {"전기": "scope_2", "가스": "scope_1", "경유/유류": "scope_1"}


def classify_activity_data_method(voucher: Voucher, classification: Classification) -> str:
    """전표 1건의 활동자료 근거(PcafQualityRule.activity_data_basis 값)를 판정.

    이 프로젝트가 실제로 구분 가능한 신호는 "전표에 실측 수량이 있는가"뿐이다.
    원문 Option 2a(energy_consumption)와 2b(production)는 에너지원 소비량인지
    생산량인지로 갈리는데, 이 프로젝트의 quantity 필드는 그 구분을 담지 않으므로
    더 보수적인(Score가 큰) 2b=production으로 취급한다. 수량이 없으면 금액을
    환산단가로 나눈 값이라 물리적 활동자료가 아니라 경제자료(매출 대용) 성격에
    가까워 3a=revenue로 취급한다.
    verified_emissions/unverified_emissions(1a/1b, 차주 직접 보고+검증)와
    assets/asset_turnover_ratio(3b/3c)는 이 프로젝트가 아직 만들지 않는 입력
    경로이므로 반환하지 않는다 — 없는 값을 만들어내지 않는다.

    참고(PR #25 리뷰): 이 함수의 반환값(production/revenue)은 Classification 모델의
    기존 activity_data_method 필드(0005 마이그레이션, reported_quantity 등)와 다른
    어휘로 같은 개념을 표현한다. 기존 필드는 현재 다른 코드에서 쓰이지 않아 급하지
    않지만, 두 체계를 나중에 통합할 필요가 있다.
    """
    raw = voucher.raw_json or {}
    if raw.get("quantity") is not None:
        return "production"
    return "revenue"


@dataclass
class CompletenessAssessment:
    """§6.3 차주 인벤토리 완전성 — PCAF 품질 후보와 분리해서 반환한다.

    scope_group 단위(scope_1|scope_2)로 산정한다 — Scope 1(가스·경유/유류)과
    Scope 2(전기)를 한데 묶어 집계하면 서로 다른 배출원의 activity_basis가
    섞여 품질 후보 점수가 오염된다(PR #25 리뷰 CONFIRMED).
    """

    reporting_year: int
    scope_group: str
    months_covered: int
    missing_months: dict[str, list[int]] = field(default_factory=dict)
    activity_basis_breakdown: dict[str, int] = field(default_factory=dict)
    completeness_pct: float = 0.0


def assess_inventory_completeness(
    session: Session, company_id: int, reporting_year: int, scope_group: str
) -> CompletenessAssessment:
    """해당 기업·보고연도·Scope의 12개월 충족 여부, 결손월, 활동자료 근거 구성비를 집계.

    scope_group: "scope_1"(가스, 경유/유류) | "scope_2"(전기). _FUEL_BUCKET_SCOPE로
    연료 버킷을 Scope에 매핑해 해당 Scope의 연료만 대상으로 집계한다.

    completeness_pct는 "12개월 × 해당 Scope 연료 개수" 슬롯 중 결손 없는 슬롯의 비율이다
    — 배출량 가중이 아니라 시간·배출원 커버리지 기준(§6.3). 품질 후보 점수(candidate_score)
    산정에는 이 값을 참고자료로만 넘기고 직접 곱하지 않는다(완전성과 품질 후보는 분리, §6.3).

    "기타"(어느 연료 버킷에도 속하지 않는) 전표는 completeness matrix에 안 잡히는 것과
    동일하게 activity_basis_breakdown 집계에서도 제외한다 — 리포트에 안 보이는 전표가
    옵션 코드 선택에는 영향을 주는 근거-결과 불일치를 막기 위함(PR #25 리뷰).
    """
    fuels = [f for f, s in _FUEL_BUCKET_SCOPE.items() if s == scope_group]
    rows = session.execute(
        select(Voucher, Classification)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id, Voucher.year == reporting_year)
    ).all()

    matrix = {f: {m: False for m in range(1, 13)} for f in fuels}
    basis_counts: dict[str, int] = {}
    covered_months: set[int] = set()
    for voucher, classification in rows:
        bucket = _fuel_bucket(voucher.item_description)
        if bucket not in matrix:
            continue
        matrix[bucket][voucher.month] = True
        covered_months.add(voucher.month)
        basis = classify_activity_data_method(voucher, classification)
        basis_counts[basis] = basis_counts.get(basis, 0) + 1

    missing: dict[str, list[int]] = {}
    covered_slots = 0
    total_slots = len(fuels) * 12
    for fuel in fuels:
        gaps = [m for m in range(1, 13) if not matrix[fuel][m]]
        if gaps:
            missing[fuel] = gaps
        covered_slots += 12 - len(gaps)

    return CompletenessAssessment(
        reporting_year=reporting_year,
        scope_group=scope_group,
        months_covered=len(covered_months),
        missing_months=missing,
        activity_basis_breakdown=basis_counts,
        completeness_pct=round(covered_slots / total_slots * 100, 1) if total_slots else 0.0,
    )


def aggregate_scope_emissions(
    session: Session, company_id: int, reporting_year: int, scope_group: str
) -> dict:
    """전표별 classifications → 연간 Scope 배출량 합산 (v1 §4 "인벤토리 완전성 집계").

    BorrowerEmissionInventory.emission_tco2e를 채우는 유일한 계산 경로다. 기존
    db/pcaf.py::_after_measured가 같은 합산을 하지만 Scope 1·2 통합·연도 필터
    없이 전체 기간을 다루는(v0.1 사장님 리포트용) 다른 용도라 재사용하지 않고,
    assess_inventory_completeness와 같은 연도·scope_group 필터로 새로 집계한다
    (이 파일이 이미 연도별 Scope 분리 집계를 하고 있어 일관성 유지).

    Scope 3는 이 프로젝트가 데이터를 만들지 않으므로 emission_tco2e=None,
    scope3_status="not_calculated"로 반환한다 — 0으로 합산하지 않는다(원칙9).
    담당자가 반려한 건(status='rejected')은 분류를 신뢰할 수 없다는 판정이므로
    제외한다(db/pcaf.py::_after_measured와 동일 규칙).
    """
    if scope_group == "scope_3":
        return {"emission_tco2e": None, "scope3_status": "not_calculated", "verified": False}

    fuels = [f for f, s in _FUEL_BUCKET_SCOPE.items() if s == scope_group]
    rows = session.execute(
        select(Voucher, Classification)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id, Voucher.year == reporting_year)
    ).all()

    total_kg = 0.0
    has_any = False
    for voucher, classification in rows:
        if _fuel_bucket(voucher.item_description) not in fuels:
            continue
        has_any = True
        if classification.status == "rejected" or not classification.emission_co2e:
            continue
        total_kg += float(classification.emission_co2e)

    if not has_any:
        return {"emission_tco2e": None, "scope3_status": None, "verified": False}
    return {"emission_tco2e": round(total_kg / 1000.0, 2), "scope3_status": None, "verified": False}


def _fuel_bucket(item: str | None) -> str:
    """api/queries.py::_fuel_class 와 동일 판정(중복 정의 — db/pcaf.py 계열과
    독립적으로 유지하기 위해 이 모듈 안에서 완결시킨다)."""
    t = item or ""
    if any(k in t for k in ("전기", "전력", "한전", "한국전력", "kWh")):
        return "전기"
    if "가스" in t or "LNG" in t:
        return "가스"
    if any(k in t for k in ("경유", "유류", "난방유", "휘발유", "지게차", "디젤", "주유")):
        return "경유/유류"
    return "기타"


def _select_quality_rule(
    session: Session, activity_basis: str, *, scope3: bool
) -> PcafQualityRule | None:
    """구성비에서 가장 많이 쓰인 활동자료 근거에 맞는 PCAF 옵션 규칙을 선택.

    scope3=True 면 Option 2a(energy_consumption)는 원문 각주 208에 의해 제외한다.
    이 프로젝트는 activity_data_basis 로 revenue/production 두 가지만 만들어내므로
    실질적으로 이 필터는 향후 energy_consumption 판정이 추가될 때를 대비한 것이다.
    """
    stmt = select(PcafQualityRule).where(
        PcafQualityRule.asset_class == "business_loans_and_unlisted_equity",
        PcafQualityRule.activity_data_basis == activity_basis,
    )
    if scope3:
        stmt = stmt.where(PcafQualityRule.applies_to_scope3.is_(True))
    return session.execute(stmt).scalars().first()


def assess_borrower_emission_quality(
    session: Session, company_id: int, reporting_year: int, scope_group: str
) -> dict:
    """PCAF 데이터 품질 후보 산정 — 원문 Table 10.1-2 옵션 체계를 그대로 적용.

    scope_group: "scope_1" | "scope_2" | "scope_3". 옵션 체계 자체는 Scope 1·2·3에
    공통이지만(원문에 별도 표 없음), 이 프로젝트는 Scope 3 활동자료를 아직 만들지
    않으므로 candidate_score=None 으로 반환한다 — PCAF 옵션 제약이 아니라 이
    프로젝트의 데이터 가용성 한계임을 limitations 에 명시한다.

    Scope 1과 Scope 2는 각각 별도로 completeness/activity_basis_breakdown을
    집계한다(PR #25 리뷰 CONFIRMED — 이전에는 두 Scope를 한데 묶어 집계해서
    서로 다른 배출원의 activity_basis가 서로의 점수를 오염시켰다).
    """
    if scope_group == "scope_3":
        return {
            "standard": "PCAF Part A Third Edition",
            "asset_class": "business_loans_and_unlisted_equity",
            "scope_group": "scope_3",
            "candidate_score": None,
            "status": "candidate",
            "option_code": None,
            "basis": [],
            "limitations": [
                "Scope 3 활동자료 미확보 — PCAF 옵션 체계 자체는 Scope 1·2와 공통이나 "
                "이 프로젝트가 아직 Scope 3 데이터를 산정하지 않음(not_calculated)"
            ],
            "completeness_pct": None,
            "bank_review_required": True,
        }

    completeness = assess_inventory_completeness(session, company_id, reporting_year, scope_group)
    if not completeness.activity_basis_breakdown:
        return {
            "standard": "PCAF Part A Third Edition",
            "asset_class": "business_loans_and_unlisted_equity",
            "scope_group": scope_group,
            "candidate_score": None,
            "status": "candidate",
            "option_code": None,
            "basis": [],
            "limitations": ["해당 보고연도 활동자료 없음 — 분류 실행 필요"],
            "completeness_pct": completeness.completeness_pct,
            "bank_review_required": True,
        }

    dominant_basis = max(
        completeness.activity_basis_breakdown, key=completeness.activity_basis_breakdown.get
    )
    rule = _select_quality_rule(session, dominant_basis, scope3=False)
    evidence = build_quality_evidence(rule, dominant_basis, completeness)

    return {
        "standard": "PCAF Part A Third Edition",
        "asset_class": "business_loans_and_unlisted_equity",
        "scope_group": scope_group,
        "candidate_score": rule.quality_score if rule else None,
        "status": "candidate",
        "option_code": rule.option_code if rule else None,
        "basis": evidence["basis"],
        "limitations": evidence["limitations"],
        "completeness_pct": completeness.completeness_pct,
        "bank_review_required": True,
    }


def build_quality_evidence(
    rule: PcafQualityRule | None, activity_basis: str, completeness: CompletenessAssessment
) -> dict:
    """basis/limitations 문구 조립 — 결정론적 문자열 템플릿(LLM 미사용)."""
    basis = []
    limitations = []

    if rule is None:
        limitations.append("매칭되는 PCAF 품질규칙 없음 — pcaf_quality_rules 시드 확인 필요")
        return {"basis": basis, "limitations": limitations}

    basis.append(rule.description)
    basis.append(f"적용 옵션: {rule.option_code} ({rule.source_reference})")

    limitations.append("제3자 검증 없음")
    if completeness.missing_months:
        gap_fuels = ", ".join(completeness.missing_months)
        limitations.append(f"일부 배출원 결손월 존재: {gap_fuels}")
    if activity_basis == "revenue":
        limitations.append("실측 수량이 아닌 금액 환산 추정치 포함")

    return {"basis": basis, "limitations": limitations}


def save_quality_assessment_version(
    session: Session,
    company_id: int,
    boundary: OrganizationalBoundary,
    reporting_year: int,
    scope_group: str,
) -> BorrowerEmissionInventory:
    """한 Scope의 품질 후보·배출량을 평가해 새 버전으로 저장(커밋은 호출부 책임).

    은행 담당자용 evaluate 엔드포인트(api/routers/quality.py)와 사장님용 리포트
    래퍼(api/routers/owner_quality.py)가 이 함수를 공유한다 — 저장 로직을 두 곳에
    복제하지 않는다. 승인된(status='approved') 인벤토리도 덮어쓰지 않고 새 버전을
    만든다(CLAUDE.md "승인된 결과는 덮어쓰지 않고 새 버전으로 재산정").
    """
    assessment = assess_borrower_emission_quality(session, company_id, reporting_year, scope_group)

    rule_id = None
    if assessment["option_code"]:
        rule = session.execute(
            select(PcafQualityRule).where(PcafQualityRule.option_code == assessment["option_code"])
        ).scalar_one_or_none()
        rule_id = rule.id if rule else None

    previous = session.execute(
        select(BorrowerEmissionInventory)
        .where(
            BorrowerEmissionInventory.company_id == company_id,
            BorrowerEmissionInventory.reporting_year == reporting_year,
            BorrowerEmissionInventory.scope_group == scope_group,
        )
        .order_by(BorrowerEmissionInventory.version.desc())
    ).scalars().first()

    emissions = aggregate_scope_emissions(session, company_id, reporting_year, scope_group)

    inventory = BorrowerEmissionInventory(
        financial_institution_id=boundary.financial_institution_id,
        company_id=company_id,
        reporting_year=reporting_year,
        organizational_boundary_id=boundary.id,
        scope_group=scope_group,
        emission_tco2e=emissions["emission_tco2e"],
        scope3_status=emissions["scope3_status"],
        verified=emissions["verified"],
        completeness_pct=assessment["completeness_pct"],
        candidate_quality_score=assessment["candidate_score"],
        candidate_quality_rule_id=rule_id,
        candidate_quality_basis_json=assessment["basis"],
        limitations_json=assessment["limitations"],
        status="draft",
        version=(previous.version + 1) if previous else 1,
        supersedes_inventory_id=previous.id if previous else None,
    )
    session.add(inventory)
    return inventory
