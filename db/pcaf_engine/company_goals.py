"""사장님 목표 설정 — 5단계 위저드 완료 후 홈 화면 박스가 목표 카드로 바뀔 때 쓰는 서비스 레이어.

goal_type 2종:
  - emission_reduction: 배출량 N% 감축 목표. 기준값은 목표 설정 시점 Scope1+2 총
    배출량(null인 Scope는 합산 제외, 원칙7과 같은 결) — db/routers/owner_quality.py의
    총 배출량 계산과 같은 방식(aggregate_scope_emissions 재사용).
  - grade_upgrade: PCAF 데이터 품질 등급 상승 목표. 내부적으로 우대금리 상품 매칭과
    완전히 같은 엔진(rate_products.py::rate_product_status_for_scope)을 쓴다 — 목표
    등급이 실제 상품 조건과 맞아떨어지면 target_product_name에 남는다. 등급 상승과
    "혜택 조건 채우기"를 별도 탭으로 나누지 않고 한 흐름으로 다루기로 한 기획 결정.

기업당 활성(status='active') 목표는 항상 최대 1개다 — 새 목표를 만들면 기존 활성
목표는 덮어쓰지 않고 superseded로 전환한다(원칙8과 같은 결).

진행률·체크리스트는 CompanyGoal에 저장하지 않고 조회할 때마다 다시 계산한다
(quality-report·progress 엔드포인트와 같은 이 프로젝트의 관례) — CompanyGoal 행
자체는 "무엇을 목표로 했는지"의 스냅숏만 갖는다. 배출량 감축 목표는 같은 보고연도
안에서는 비교 대상이 없다(결손월이 채워질수록 총량은 늘어나는 게 정상이라 "감축"
판단 근거가 못 된다) — 보고연도가 넘어가 다음 해 데이터가 잡힐 때부터 실제로
비교한다(가짜 진행률을 보여주지 않는다, 실패 가시성 원칙과 같은 결).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Company, CompanyGoal
from db.pcaf_engine.pcaf_quality import (
    aggregate_scope_emissions,
    assess_inventory_completeness,
    default_reporting_year,
    scope_emission_detail,
)
from db.pcaf_engine.rate_products import rate_product_status_for_scope

DISCLAIMER_TEXT = (
    "등급·혜택 목표는 데이터 완전성 개선을 제안할 뿐 PCAF 등급 상승이나 우대금리 자격을 "
    "보장하지 않습니다. 최종 승인은 은행 담당자가 별도 심사를 거쳐 결정합니다."
)

_SCOPES = ("scope_1", "scope_2")


class CompanyNotFoundError(Exception):
    """company_id에 해당하는 기업이 없을 때."""


class GoalNotFoundError(Exception):
    """goal_id가 없거나 다른 기업 소유일 때(테넌트 경계, 원칙9와 같은 결)."""


class NoEmissionDataError(Exception):
    """감축 목표를 세울 배출량 기준값 자체가 없을 때(분류 실행 전 등)."""


class NoActivityDataError(Exception):
    """등급 목표를 세울 활동자료(전표) 자체가 없을 때."""


class InvalidTargetGradeError(Exception):
    """목표 등급이 현재 등급보다 나쁘거나(숫자가 같거나 크거나) 1~5 범위를 벗어날 때."""


def _total_emission(session: Session, company_id: int, year: int) -> float | None:
    """Scope1+2 총 배출량 — null인 Scope는 합산에서 제외한다(원칙7, owner_quality.py 라우터의
    벤치마크 계산과 동일 규칙: 둘 다 null이면 None, 하나라도 있으면 나머지는 0으로 취급)."""
    e1 = aggregate_scope_emissions(session, company_id, year, "scope_1")["emission_tco2e"]
    e2 = aggregate_scope_emissions(session, company_id, year, "scope_2")["emission_tco2e"]
    if e1 is None and e2 is None:
        return None
    return round((e1 or 0) + (e2 or 0), 2)


def _applicable_months(year: int) -> int:
    """assess_inventory_completeness와 같은 규칙(pcaf_quality.py) — 달력상 올해면 아직
    안 온 달은 제외, 과거 연도는 12개월 전부. 홈 화면 월별 막대의 x축 길이를 이 값으로
    맞춘다(미래 달까지 빈 막대로 늘어놓지 않기 위함)."""
    today = datetime.now(timezone.utc)
    return today.month if year == today.year else 12


def _monthly_emissions(session: Session, company_id: int, year: int) -> list[dict]:
    """월별 배출량 막대 차트 데이터 — Scope1+2 합산, scope_emission_detail(전표별
    상세)을 월 단위로 다시 묶는다. 데이터 없는 달도 0으로 채워 x축이 끊기지 않게 한다."""
    totals = {m: 0.0 for m in range(1, _applicable_months(year) + 1)}
    for scope in _SCOPES:
        for item in scope_emission_detail(session, company_id, year, scope):
            if item["month"] in totals:
                totals[item["month"]] += item["emission_co2e"]
    return [
        {"month": m, "emission_tco2e": round(kg / 1000.0, 3)}
        for m, kg in sorted(totals.items())
    ]


def _monthly_coverage(session: Session, company_id: int, year: int, scope_group: str) -> list[dict]:
    """등급 목표 링·막대가 쓰는 월별 커버리지 — 그 Scope의 선택된 연료가 전부 채워진
    달만 covered=True(약한 고리 원칙과 같은 기준, missing_months에 하나라도 걸리면
    그 달은 결손)."""
    completeness = assess_inventory_completeness(session, company_id, year, scope_group)
    gapped_months = {m for months in completeness.missing_months.values() for m in months}
    return [
        {"month": m, "covered": m not in gapped_months}
        for m in range(1, _applicable_months(year) + 1)
    ]


def _supersede_active_goal(session: Session, company_id: int) -> None:
    active = session.execute(
        select(CompanyGoal).where(CompanyGoal.company_id == company_id, CompanyGoal.status == "active")
    ).scalars().first()
    if active is not None:
        active.status = "superseded"


def create_emission_reduction_goal(
    session: Session, company_id: int, *, target_reduction_pct: float
) -> CompanyGoal:
    """배출량 N% 감축 목표를 확정한다. 기준값(baseline_value)은 지금 이 보고연도의
    Scope1+2 총 배출량 — 분류가 아직 안 끝나 배출량 자체가 없으면 세울 수 없다."""
    company = session.get(Company, company_id)
    if company is None:
        raise CompanyNotFoundError(f"company_id={company_id} 없음")
    if not (0 < target_reduction_pct < 100):
        raise ValueError(f"target_reduction_pct는 0~100 사이여야 함(전달값: {target_reduction_pct})")

    year = default_reporting_year(session, company_id)
    baseline = _total_emission(session, company_id, year)
    if baseline is None:
        raise NoEmissionDataError(f"company_id={company_id} 배출량 기준값 없음 — 분류 실행 필요")

    _supersede_active_goal(session, company_id)
    goal = CompanyGoal(
        company_id=company_id,
        goal_type="emission_reduction",
        baseline_reporting_year=year,
        baseline_value=baseline,
        target_value=round(baseline * (1 - target_reduction_pct / 100), 2),
        target_reduction_pct=target_reduction_pct,
    )
    session.add(goal)
    session.commit()
    return goal


def create_grade_upgrade_goal(
    session: Session, company_id: int, *, scope_group: str, target_grade: int | None = None
) -> CompanyGoal:
    """등급 상승(＋혜택 조건 충족) 목표를 확정한다.

    target_grade를 생략하면 rate_product_status_for_scope가 계산한 추천 목표를
    쓴다 — eligible 상태면 이미 도달한 등급 그대로(즉시 "달성" 상태로 시작하는 것도
    허용, 축하 문구로 처리), upgrade_needed면 그 Scope가 실제 도달 가능한 다음
    등급이다. 사용자가 추천과 다른 등급을 직접 고르면(target_grade 지정) 그 등급이
    실제로 어떤 상품 조건과 맞아떨어지는지 이 함수는 보장할 수 없으므로
    target_product_name은 비워둔다 — 지어낸 매칭을 보여주지 않는다.
    """
    if scope_group not in _SCOPES:
        raise ValueError(f"scope_group은 scope_1|scope_2여야 함(전달값: {scope_group!r})")
    company = session.get(Company, company_id)
    if company is None:
        raise CompanyNotFoundError(f"company_id={company_id} 없음")

    year = default_reporting_year(session, company_id)
    status = rate_product_status_for_scope(session, company_id, year, scope_group)
    if status is None:
        raise NoActivityDataError(
            f"company_id={company_id} scope_group={scope_group} 활동자료 없음 — 목표 설정 근거 없음"
        )

    current_grade = status["candidate_score"]
    if status["status"] == "eligible":
        recommended_target = current_grade
        recommended_product_name = ", ".join(p["product_name"] for p in status["products"]) or None
    else:
        recommended_target = status["target_grade"]
        recommended_product_name = (
            ", ".join(p["product_name"] for p in status.get("target_products", [])) or None
        )

    if target_grade is None:
        target_grade = recommended_target
    elif not (1 <= target_grade <= 5) or target_grade > current_grade:
        raise InvalidTargetGradeError(
            f"target_grade={target_grade}는 현재 등급({current_grade})보다 나쁘거나 범위(1~5)를 벗어남"
        )

    target_product_name = recommended_product_name if target_grade == recommended_target else None

    _supersede_active_goal(session, company_id)
    goal = CompanyGoal(
        company_id=company_id,
        goal_type="grade_upgrade",
        scope_group=scope_group,
        baseline_reporting_year=year,
        baseline_value=current_grade,
        target_value=target_grade,
        target_product_name=target_product_name,
    )
    session.add(goal)
    session.commit()
    return goal


def get_active_goal(session: Session, company_id: int) -> CompanyGoal | None:
    return session.execute(
        select(CompanyGoal).where(CompanyGoal.company_id == company_id, CompanyGoal.status == "active")
    ).scalars().first()


def _emission_reduction_progress(session: Session, goal: CompanyGoal) -> dict:
    current_year = default_reporting_year(session, goal.company_id)
    # 홈 박스의 월별 막대는 "비교가 성립하는지"와 무관하게 항상 최근 활동 현황을
    # 보여준다 — 같은 보고연도 안이면 올해 쌓이는 데이터, 넘어갔으면 비교 대상 연도.
    monthly_emission = _monthly_emissions(session, goal.company_id, current_year)

    if current_year == goal.baseline_reporting_year:
        return {
            "achieved": False, "measured": False, "current_value": None,
            "progress_pct": 0.0, "monthly_emission": monthly_emission,
        }

    current_value = _total_emission(session, goal.company_id, current_year)
    if current_value is None:
        return {
            "achieved": False, "measured": False, "current_value": None,
            "progress_pct": 0.0, "monthly_emission": monthly_emission,
        }

    reduction_needed = goal.baseline_value - goal.target_value
    achieved_reduction = goal.baseline_value - current_value
    progress_pct = (
        0.0 if reduction_needed <= 0
        else max(0.0, min(100.0, achieved_reduction / reduction_needed * 100))
    )
    return {
        "achieved": current_value <= goal.target_value,
        "measured": True,
        "current_value": current_value,
        "progress_pct": round(progress_pct, 1),
        "monthly_emission": monthly_emission,
    }


def _grade_upgrade_progress(session: Session, goal: CompanyGoal) -> dict:
    status = rate_product_status_for_scope(
        session, goal.company_id, goal.baseline_reporting_year, goal.scope_group
    )
    if status is None:
        return {
            "achieved": False, "measured": False, "current_value": None,
            "progress_pct": 0.0, "missing_items": [], "disclaimer_text": DISCLAIMER_TEXT,
            "monthly_coverage": [],
        }

    current_grade = status["candidate_score"]
    achieved = current_grade <= goal.target_value
    missing_items = [] if status["status"] == "eligible" else status.get("missing_items", [])
    monthly_coverage = _monthly_coverage(
        session, goal.company_id, goal.baseline_reporting_year, goal.scope_group
    )

    # 링 채움은 등급 격차가 아니라 "월별 데이터 완전성"으로 계산한다 — 이 프로젝트에서
    # 실제 도달 가능한 등급 전환은 4등급→2등급 하나뿐이라(quality_upgrade_candidate
    # 문서 참고) 등급 격차 기준으로는 마지막 달을 채우기 전까지 계속 0%로 보여 걸음수
    # 앱처럼 매달 조금씩 차오르는 느낌을 낼 수 없다. completeness_pct는 서류 하나
    # 올릴 때마다 실제로 올라가고, "약한 고리 원칙" 특성상 achieved 시점엔 항상
    # 100%와 일치한다(달성=결손 없음=completeness 100%).
    progress_pct = (
        100.0 if achieved
        else (round(len([m for m in monthly_coverage if m["covered"]]) / len(monthly_coverage) * 100, 1)
              if monthly_coverage else 0.0)
    )
    return {
        "achieved": achieved,
        "measured": True,
        "current_value": current_grade,
        "progress_pct": progress_pct,
        "missing_items": missing_items,
        "disclaimer_text": DISCLAIMER_TEXT,
        "monthly_coverage": monthly_coverage,
    }


def get_active_goal_progress(session: Session, company_id: int) -> dict | None:
    """홈 화면 목표 카드가 그대로 쓰는 응답 — 활성 목표가 없으면 None.

    달성 조건을 만족하면 이 호출에서 바로 status를 'achieved'로 전환하고 커밋한다
    (승인된 인벤토리처럼 "확정"이 아니라 그냥 목표 달성 시점 기록 — 다음 조회부터
    achieved 배지가 계속 유지된다)."""
    goal = get_active_goal(session, company_id)
    if goal is None:
        return None

    payload = (
        _emission_reduction_progress(session, goal)
        if goal.goal_type == "emission_reduction"
        else _grade_upgrade_progress(session, goal)
    )

    if payload["achieved"] and goal.status == "active":
        goal.status = "achieved"
        goal.achieved_at = datetime.now(timezone.utc)
        session.commit()

    return {
        "id": goal.id,
        "goal_type": goal.goal_type,
        "scope_group": goal.scope_group,
        "baseline_reporting_year": goal.baseline_reporting_year,
        "baseline_value": goal.baseline_value,
        "target_value": goal.target_value,
        "target_reduction_pct": goal.target_reduction_pct,
        "target_product_name": goal.target_product_name,
        "status": goal.status,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        **payload,
    }


def cancel_goal(session: Session, company_id: int, goal_id: int) -> CompanyGoal:
    goal = session.get(CompanyGoal, goal_id)
    if goal is None or goal.company_id != company_id:
        raise GoalNotFoundError(f"goal_id={goal_id} company_id={company_id} 없음")
    if goal.status not in ("active", "achieved"):
        raise ValueError(f"goal_id={goal_id}는 이미 {goal.status} 상태라 취소할 수 없음")
    goal.status = "cancelled"
    session.commit()
    return goal
