"""사장님 목표 설정 — 5단계 위저드 완료 후 홈 화면 박스가 목표 카드로 바뀔 때 쓰는 서비스 레이어.

goal_type 2종:
  - emission_reduction: 배출량 N% 감축 목표. 기준값은 목표 설정월**까지의 최근** 12개월
    Scope1+2 총 배출량(null인 Scope는 합산 제외, 원칙7과 같은 결). 달력년도를 안 쓰는
    이유: 8월에 목표를 세우면 달력년도 기준값은 8개월치인데 그걸 다음 해 12개월치와
    비교하면 월수가 안 맞는다(사용자 지적, 2026-08-19). 그 12개월이 미래가 아니라
    과거인 이유: 미래 구간은 설정 시점에 데이터가 이번 달 하나뿐이라 "연간 기준값"이
    사실상 한 달치가 돼버렸다(2026-08-25, 실측 11배 오차 — 0033에서 기존 행 재계산).
    시작월은 사용자가 고르지 않고 설정 시점(지금)을 자동으로 쓴다("입력 제로" 원칙).
  - grade_upgrade: PCAF 데이터 품질 등급 상승 목표. 내부적으로 우대금리 상품 매칭과
    완전히 같은 엔진(rate_products.py::rate_product_status_for_scope)을 쓴다 — 목표
    등급이 실제 상품 조건과 맞아떨어지면 target_product_name에 남는다. 등급 상승과
    "혜택 조건 채우기"를 별도 탭으로 나누지 않고 한 흐름으로 다루기로 한 기획 결정.
    이쪽은 % 감축이 아니라 데이터 완전성/등급 기준이라 롤링 윈도우 대상이 아니고
    달력년도(default_reporting_year) 그대로 쓴다.

기업당 활성(status='active') 목표는 항상 최대 1개다 — 새 목표를 만들면 기존 활성
목표는 덮어쓰지 않고 superseded로 전환한다(원칙8과 같은 결).

진행률·체크리스트는 CompanyGoal에 저장하지 않고 조회할 때마다 다시 계산한다
(quality-report·progress 엔드포인트와 같은 이 프로젝트의 관례) — CompanyGoal 행
자체는 "무엇을 목표로 했는지"의 스냅숏만 갖는다(기준값·목표값 2개. 그래서 기준
구간 정의가 바뀌면 코드만 고쳐선 안 되고 기존 행도 함께 재계산해야 한다 — 0033).

배출량 감축 목표의 진행률은 **동월 대비**로 잰다: 목표 시작월부터 이번 달까지를
"정확히 같은 달들, 1년 전"과 비교한다(2026-08-25). 첫 달부터 값이 있고, 같은 달끼리만
비교하므로 계절성에 안전하며, 12개월이 지나면 "최근 12개월 vs 직전 12개월"과 정확히
같아진다. 다만 "목표 달성"(status→achieved) 판정은 경과 12개월이 다 찬 뒤에만 한다 —
석 달 잘한 걸로 연간 감축 달성 배지를 주지 않는다(가짜 진행률 금지, 실패 가시성 원칙과
같은 결). 근거와 대안 검토는 _emission_reduction_progress 주석에 자세히 적어뒀다.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Classification, Company, CompanyGoal, Voucher
from db.pcaf_engine.pcaf import monthly_by_fuel
from db.pcaf_engine.pcaf_quality import (
    FUEL_BUCKET_SCOPE,
    assess_inventory_completeness,
    default_reporting_year,
    fuel_bucket,
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


def _now_year_month() -> tuple[int, int]:
    """지금이 몇 년 몇 월인지 — 이름 붙은 함수로 분리해 테스트가
    default_reporting_year와 같은 방식으로 monkeypatch할 수 있게 한다."""
    now = datetime.now(timezone.utc)
    return now.year, now.month


def _window_months(start_year: int, start_month: int, *, offset: int = 0, count: int = 12) -> list[tuple[int, int]]:
    """(start_year, start_month)부터 count개월치 (연, 월) 리스트 — 달력년도가 아니라
    목표 설정월을 시작으로 삼는 롤링 윈도우(2026-08-19, 사용자 지적: 8월에 목표를
    세우면 기준값이 8개월치인데 다음 달력년도 12개월치와 비교돼 월수가 안 맞았다).
    offset=12를 주면 바로 다음 윈도우(비교 구간)를 얻는다."""
    base_index = start_year * 12 + (start_month - 1) + offset
    return [(idx // 12, idx % 12 + 1) for idx in range(base_index, base_index + count)]


def _trailing_months(end_year: int, end_month: int, *, count: int = 12) -> list[tuple[int, int]]:
    """(end_year, end_month)을 **마지막 칸**으로 하는 직전 count개월 (연, 월) 리스트 —
    "최근 1년치"를 뜻한다. 지금이 2026년 8월이면 2025년 9월~2026년 8월.

    _window_months가 시작월을 받아 앞을 보는 것과 방향만 반대다. 홈 목표 카드의 월별
    차트가 쓴다 — 목표 윈도우는 설정월부터 미래 12개월이라 차트에 쓰면 아직 오지 않은
    달이 빈칸으로 대부분을 차지한다(2026-08-25 사용자 지적). 차트는 "최근 활동 현황"이
    목적이므로 목표 기간과 분리해 항상 뒤를 돌아본다.

    반환 순서는 과거→현재(시간순)라 그대로 x축 순서가 된다. 정확히 count개월 연속
    구간이므로 count<=12일 때 각 항목의 month(1~12)는 중복되지 않는다 —
    monthly_by_fuel이 month 번호로 버킷을 잡는 전제와 맞다."""
    end_index = end_year * 12 + (end_month - 1)
    return [(idx // 12, idx % 12 + 1) for idx in range(end_index - count + 1, end_index + 1)]


def _emission_in_months(session: Session, company_id: int, months: list[tuple[int, int]]) -> float | None:
    """Scope1+2 총 배출량 — 달력년도가 아니라 정확히 months에 준 (연, 월)들만 집계한다.
    연속 구간일 필요도 없다(동월 대비 비교가 "작년 같은 달들"이라는 띄어진 구간을 쓴다).

    aggregate_scope_emissions + _total_emission과 정확히 같은 판정 규칙(원칙7: Scope
    하나라도 매칭되는 전표가 있으면 있는 것으로 취급, 반려·미산정 건은 0으로 더함 —
    "전표가 아예 없는 Scope"만 None)을 임의 월 집합에 적용한다.
    aggregate_scope_emissions는 연도 전체만 필터할 수 있어 재사용 불가, 같은
    fuel_bucket/FUEL_BUCKET_SCOPE 매핑(pcaf_quality.py에서 공개, 2026-08-19)으로
    독립 집계한다.

    Scope별로 먼저 round(2)한 뒤 더하는 순서를 지킨다 — aggregate_scope_emissions가
    Scope 카드에 그렇게 표시하므로, 합계만 따로 반올림하면 화면의 Scope1+Scope2와
    총량이 1의 자리에서 안 맞는 일이 생긴다."""
    if not months:
        return None
    month_indexes = [y * 12 + m for y, m in months]
    rows = session.execute(
        select(Classification.fuel_type, Classification.status, Classification.emission_co2e)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            (Voucher.year * 12 + Voucher.month).in_(month_indexes),
        )
    ).all()

    totals_kg = {"scope_1": 0.0, "scope_2": 0.0}
    has_any = {"scope_1": False, "scope_2": False}
    for fuel_type, status, emission in rows:
        scope_group = FUEL_BUCKET_SCOPE.get(fuel_bucket(fuel_type))
        if scope_group not in totals_kg:
            continue
        has_any[scope_group] = True
        if status == "rejected" or not emission:
            continue
        totals_kg[scope_group] += float(emission)

    e1 = round(totals_kg["scope_1"] / 1000.0, 2) if has_any["scope_1"] else None
    e2 = round(totals_kg["scope_2"] / 1000.0, 2) if has_any["scope_2"] else None
    if e1 is None and e2 is None:
        return None
    return round((e1 or 0) + (e2 or 0), 2)


def _applicable_months(year: int) -> int:
    """assess_inventory_completeness와 같은 규칙(pcaf_quality.py) — 달력상 올해면 아직
    안 온 달은 제외, 과거 연도는 12개월 전부. 홈 화면 월별 막대의 x축 길이를 이 값으로
    맞춘다(미래 달까지 빈 막대로 늘어놓지 않기 위함)."""
    today = datetime.now(timezone.utc)
    return today.month if year == today.year else 12


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
    """이 기업의 "현재" 목표(활성 중이거나, 이미 달성해서 배지로 남아있는 것)를
    superseded로 돌린다. status == "active"만 보면 이미 achieved로 넘어간 목표는
    안 걸려서 그대로 남는데, get_active_goal이 achieved도 "현재 목표"로 취급하는
    이상(아래) 새 목표를 만들 때 그것도 같이 정리해야 "현재 목표는 항상 1개"
    불변식이 유지된다."""
    current = session.execute(
        select(CompanyGoal).where(
            CompanyGoal.company_id == company_id,
            CompanyGoal.status.in_(("active", "achieved")),
        )
    ).scalars().first()
    if current is not None:
        current.status = "superseded"


def create_emission_reduction_goal(
    session: Session, company_id: int, *, target_reduction_pct: float
) -> CompanyGoal:
    """배출량 N% 감축 목표를 확정한다. 기준값(baseline_value)은 **지금까지의 최근
    12개월**(_trailing_months) Scope1+2 총 배출량 — 분류가 아직 안 끝나 배출량 자체가
    없으면 세울 수 없다. 시작월은 목표 설정 시점(지금)을 자동으로 쓴다 — 사용자가
    고르게 하지 않는다("입력 제로" 원칙, CLAUDE.md).

    기준 구간이 "앞으로 12개월"이 아니라 "지난 12개월"인 이유(2026-08-25, 사용자
    지적으로 발견): 예전엔 설정월부터 **미래** 12개월을 기준 구간으로 삼았는데, 목표를
    세우는 순간 그 구간에 존재할 수 있는 데이터는 이번 달 하나뿐이라 기준값이 사실상
    "이번 달 한 달치"가 됐다. 실측(대경부품): 2026-08에 세운 목표의 기준값이 1.5tCO2e로
    잡혔는데 이는 8월 한 달(1.506)이고, 실제 최근 1년 총량은 17.37tCO2e였다 —
    "연간 목표 배출량"이라 표시되는 값이 한 달치의 90%라 11배 이상 틀렸다. 감축 목표는
    본질적으로 "과거 1년보다 덜 쓰기"이므로 기준은 이미 확정된 과거여야 한다.

    baseline_reporting_year/baseline_start_month의 의미는 그대로 "목표 시작월"이다
    (기준 구간의 시작월이 아님 — 기준 구간은 거기서 거꾸로 12개월). 컬럼 의미가
    안 바뀌므로 스키마 변경은 없고, 이미 저장된 기준값만 0033에서 재계산한다."""
    company = session.get(Company, company_id)
    if company is None:
        raise CompanyNotFoundError(f"company_id={company_id} 없음")
    if not (0 < target_reduction_pct < 100):
        raise ValueError(f"target_reduction_pct는 0~100 사이여야 함(전달값: {target_reduction_pct})")

    start_year, start_month = _now_year_month()
    baseline = _emission_in_months(session, company_id, _trailing_months(start_year, start_month))
    if baseline is None:
        raise NoEmissionDataError(f"company_id={company_id} 배출량 기준값 없음 — 분류 실행 필요")

    _supersede_active_goal(session, company_id)
    goal = CompanyGoal(
        company_id=company_id,
        goal_type="emission_reduction",
        baseline_reporting_year=start_year,
        baseline_start_month=start_month,
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

    year = default_reporting_year(session, company_id)  # 등급 목표는 롤링 윈도우 대상 아님 — 달력년도 그대로
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
        # baseline_start_month은 emission_reduction 전용 개념이라 여기선 안 씀 —
        # 컬럼 기본값(1)이 그대로 채워진다(db/models.py::CompanyGoal 주석 참고).
        baseline_value=current_grade,
        target_value=target_grade,
        target_product_name=target_product_name,
    )
    session.add(goal)
    session.commit()
    return goal


def get_active_goal(session: Session, company_id: int) -> CompanyGoal | None:
    """홈 화면에 지금 보여줄 목표 — active(진행 중)뿐 아니라 achieved(달성, 배지로
    남아있어야 함)도 포함한다. status == "active"만 보면 get_active_goal_progress가
    달성 판정과 동시에 status를 achieved로 바꾸는 순간부터 이 함수가 그 목표를
    영영 못 찾게 되어, 카드가 "달성 배지 유지" 대신 목표 설정 프롬프트로 되돌아가
    "목표가 사라졌다"로 보였다(실측 확인, 2026-08-19). 새 목표 생성 시
    _supersede_active_goal이 achieved도 같이 정리하므로 이 둘 중 하나만 항상
    최대 1건이다."""
    return session.execute(
        select(CompanyGoal).where(
            CompanyGoal.company_id == company_id,
            CompanyGoal.status.in_(("active", "achieved")),
        )
    ).scalars().first()


def _emission_reduction_progress(session: Session, goal: CompanyGoal) -> dict:
    """진행률을 **동월 대비**로 잰다 — 목표 시작월부터 이번 달까지(경과 구간)의 배출량을
    "정확히 같은 달들, 1년 전"과 비교한다(2026-08-25 결정).

    왜 동월 대비인가. 예전 방식은 기준 12개월이 다 지나야(=12개월 뒤) 비로소 비교가
    성립해서, 그전까지 링이 12개월 내내 0%로 죽어 있었다(measured=False). 사용자가
    "목표 진행률 링으로 바꾸고 싶다"고 한 게 이 죽은 링 얘기다. 대안으로 검토한 것들:
      - 누적 예산 소진율(pace): 즉시 움직이지만 계절성을 무시해 난방 달에 억울하게
        빨개진다. 계절 가중을 넣으려면 근거 없는 숫자를 만들어야 해서 탈락.
      - 데이터 완전성(등급 목표가 쓰는 방식): 매달 움직이지만 배출량이 **늘어도** 링이
        가득 차서 감축 목표에는 거짓말이 된다. 탈락.
    동월 대비는 (a) 첫 달부터 값이 있고, (b) 같은 달끼리만 비교하므로 계절성에 안전하고,
    (c) 12개월이 지나면 "최근 12개월 vs 직전 12개월"과 **정확히 같아진다** — 그래서
    중간에 기준이 바뀌는 불연속이 없다.

    12개월이 다 찼을 때 카드의 모든 숫자가 한 점에서 만난다:
      비교 구간 합 == baseline_value(=목표 설정 시점의 최근 12개월)
      경과 구간 합 == current_value(=지금 기준 최근 12개월)
      achieved ⟺ 감축률 >= 목표% ⟺ current_value <= target_value
    즉 "링 100%"와 "최근 1년 배출량 <= 목표 배출량"이 항상 같은 뜻이 된다.

    achieved는 경과 12개월이 다 차야만 True다 — 3개월 잘했다고 "연간 10% 감축 달성"
    배지를 주면 거짓이다(가짜 진행률 금지와 같은 결). 링은 그 사이에도 차오른다.
    """
    start_year, start_month = goal.baseline_reporting_year, goal.baseline_start_month
    now_year, now_month = _now_year_month()

    # 홈 박스의 월별 차트는 목표 구간과 상관없이 "지금 기준 최근 1년"을 그린다
    # (_trailing_months — 이번 달이 오른쪽 끝). 리포트 화면(ScenePcaf.tsx)의 "월별
    # 배출 추이"와 완전히 같은 차트(MonthlyTrendChart.tsx)를 재사용하기로 해
    # (사용자 요청, 2026-08-18) 같은 재료 함수(monthly_by_fuel)를 그대로 쓴다.
    #
    # 예전엔 목표 윈도우(설정월부터 12개월)를 그대로 썼는데, 그 윈도우가 미래를
    # 향하다 보니 8월에 목표를 세우면 x축이 "8,9,…,7"로 깔리고 8월 한 칸만 막대가
    # 있고 나머지 11칸은 아직 오지 않은 달이라 텅 비어 보였다(사용자 지적,
    # 2026-08-25 — "왜 8월부터 나오지"). 차트의 목적은 목표 기간 표시가 아니라
    # "최근 활동 현황"이므로 목표 구간과 분리해 항상 뒤를 돌아보게 한다.
    trailing_year_months = _trailing_months(now_year, now_month)
    monthly_emission_detail = monthly_by_fuel(session, goal.company_id, months=trailing_year_months)

    # "최근 1년 배출량" — 목표 진행과 무관하게 항상 지금 기준 최근 12개월 총량이다.
    # 카드의 목표 배출량(연간 총량)과 같은 단위·같은 길이라 그대로 나란히 비교된다.
    current_value = _emission_in_months(session, goal.company_id, trailing_year_months)

    # 경과 개월(시작월 포함, 최대 12). 목표 시작월이 미래면(시계 문제 등) 0 이하가 된다.
    elapsed_months = (now_year * 12 + now_month) - (start_year * 12 + start_month) + 1
    elapsed_months = min(12, elapsed_months)

    unmeasured = {
        "achieved": False, "measured": False, "current_value": current_value,
        "progress_pct": 0.0, "reduction_pct": None, "elapsed_months": max(0, elapsed_months),
        "monthly_emission_detail": monthly_emission_detail,
    }
    if elapsed_months < 1:
        return unmeasured

    measure_months = _window_months(start_year, start_month, count=elapsed_months)
    # 같은 달들의 1년 전 — start_year를 1 줄이면 (연,월) 쌍이 정확히 12개월 앞으로
    # 밀린다(_window_months가 year*12 산식이라 12월 경계에서도 어긋나지 않는다).
    compare_months = _window_months(start_year - 1, start_month, count=elapsed_months)

    measure_total = _emission_in_months(session, goal.company_id, measure_months)
    compare_total = _emission_in_months(session, goal.company_id, compare_months)
    # 비교 기준(작년 동월)이 없거나 0이면 감축률을 만들 수 없다 — 0으로 나누거나
    # 없는 값을 지어내지 않고 "아직 비교 불가"로 내려보낸다(원칙7).
    if measure_total is None or not compare_total:
        return unmeasured

    reduction_pct = (1 - measure_total / compare_total) * 100
    target_pct = goal.target_reduction_pct or 0
    progress_pct = (
        0.0 if target_pct <= 0
        else max(0.0, min(100.0, reduction_pct / target_pct * 100))
    )
    return {
        "achieved": elapsed_months >= 12 and reduction_pct >= target_pct,
        "measured": True,
        "current_value": current_value,
        "progress_pct": round(progress_pct, 1),
        # 배출량이 늘었으면 음수로 그대로 내려간다 — 링은 0%로 눌리지만 화면이
        # "지난해 같은 달보다 늘었어요"라고 사실대로 말할 수 있어야 한다.
        "reduction_pct": round(reduction_pct, 1),
        "elapsed_months": elapsed_months,
        "monthly_emission_detail": monthly_emission_detail,
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
