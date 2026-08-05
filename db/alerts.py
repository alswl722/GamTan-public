"""이상 신호 알림 — 여신 리스크 조기 경보(EWS)용 결정론적 감지 함수.

은행권 여신 조기경보 실무의 두 축을 코드로 옮긴다:
  1. 추세 이탈 — 최근 3개월 이동평균 대비 최신월 배출량 급등/급감
     (단일월 대비 전월 비교는 계절성에 취약해 오탐이 많다 — orchestrator.py의
      _check_anomalies 와 같은 결로 "평월 대비 배수"를 쓴다)
  2. 데이터 공백 — 연속 미연동 자체가 조업 중단·이탈 조짐일 수 있는 신호

급등은 리스크(예: 이상 사용·불성실 신고 가능성), 급감은 가동률 하락 의심으로
해석이 갈리므로 severity/message 를 다르게 낸다. 판단은 여기서 끝내지 않고
문구로만 안내 — 여신 결정은 하지 않는다(CLAUDE.md §9).
"""
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Classification, Company, Voucher

SPIKE_RATIO = 1.5      # 최신월 ≥ 이동평균 × 1.5 → 급등(high)
DROP_RATIO = 0.5       # 최신월 ≤ 이동평균 × 0.5 → 급감(medium)
TREND_WINDOW = 3        # 이동평균 산정에 쓸 직전 개월 수
GAP_MONTHS_THRESHOLD = 3  # 이 개월 수 이상 연속 공백이면 알림


def _monthly_totals(session: Session, company_id: int) -> dict[int, float]:
    """기업의 월별 Scope 1+2 배출량 합계(kg) — 확정된(auto/confirmed) 건만, 존재하는 월만.

    review_required(HITL 미확정)는 사람이 아직 판정을 마감하지 않은 값이라
    제외한다 — 저신뢰 분류 하나가 은행 담당자에게 확정된 "급등"으로 잘못
    보이면 안 된다(보조수단성 원칙, CLAUDE.md §5-5).
    """
    rows = session.execute(
        select(Voucher.month, Classification.emission_co2e)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            Classification.scope.in_((1, 2)),
            Classification.status.in_(("auto", "confirmed")),
        )
    ).all()
    totals: dict[int, float] = {}
    for month, emission in rows:
        totals[int(month)] = totals.get(int(month), 0.0) + float(emission or 0)
    return totals


def _trend_signal(totals: dict[int, float]) -> dict | None:
    """최신월 vs 직전 TREND_WINDOW개월 이동평균 — 급등/급감 하나만 반환(둘 다 걸리지 않음).

    "직전 3개월"은 존재하는 데이터가 아니라 **달력상 연속된** latest-1~latest-3
    이어야 한다 — 그렇지 않으면 결손월(예: 3~5월 가스 공백)을 건너뛰고 훨씬
    이전 달과 비교해놓고 "최근 3개월 평균"이라 잘못 표시하게 된다. 그런
    경우는 이동평균 기준을 세울 수 없으므로 판단을 보류한다(공백 자체는
    _gap_signal이 별도로 잡는다).
    """
    months = sorted(totals)
    if not months:
        return None

    latest = months[-1]
    baseline_months = [latest - i for i in range(1, TREND_WINDOW + 1)]
    if not all(m in totals for m in baseline_months):
        return None  # 직전 3개월이 달력상 연속으로 채워져 있지 않으면 판단 보류

    baseline = mean(totals[m] for m in baseline_months)
    if baseline <= 0:
        return None

    latest_value = totals[latest]
    ratio = latest_value / baseline

    if ratio >= SPIKE_RATIO:
        return {
            "type": "spike",
            "severity": "high",
            "month": latest,
            "ratio": round(ratio, 2),
            "message": f"{latest}월 배출량이 최근 {TREND_WINDOW}개월 평균의 {ratio:.1f}배로 급등",
        }
    if ratio <= DROP_RATIO:
        return {
            "type": "drop",
            "severity": "medium",
            "month": latest,
            "ratio": round(ratio, 2),
            "message": f"{latest}월 배출량이 최근 {TREND_WINDOW}개월 평균의 {ratio:.1f}배로 급감 — 가동률 하락 의심",
        }
    return None


def _gap_signal(totals: dict[int, float]) -> dict | None:
    """최신 데이터 이후 연속 공백 개월 수가 임계치 이상이면 알림.

    1~12월 전체를 훑어 "데이터가 있던 마지막 달 이후" 몇 달이 비었는지 본다 —
    아예 연동을 시작 안 한 기업(공백 0건)은 이 신호가 아니라 별도 커버리지
    로직(get_coverage)의 몫이라 여기서는 제외한다.
    """
    if not totals:
        return None
    last_reported = max(totals)
    missing = [m for m in range(last_reported + 1, 13)]
    if len(missing) >= GAP_MONTHS_THRESHOLD:
        return {
            "type": "gap",
            "severity": "medium",
            "month": last_reported,
            "missing_months": missing,
            "message": f"{last_reported}월 이후 {len(missing)}개월 연속 전표 미연동 — 데이터 공백",
        }
    return None


def detect_alerts(session: Session, company_id: int | None = None) -> list[dict]:
    """이상 신호 알림 목록 생성 — severity 내림차순, 그다음 기업명.

    company_id 를 주면 해당 기업만 스캔한다 — 은행 담당자용 전체 포트폴리오
    조회(GET /admin/alerts)와 사장님용 자기 기업 알림(GET /owner/alerts/{id})이
    같은 판정 로직을 공유하도록 한다("은행이 먼저 알고 사장은 모른다" 구도 방지,
    CLAUDE.md §9 — 알림은 항상 사장에게 먼저).
    """
    stmt = select(Company).order_by(Company.id)
    if company_id is not None:
        stmt = stmt.where(Company.id == company_id)
    companies = session.execute(stmt).scalars().all()

    alerts = []
    for co in companies:
        totals = _monthly_totals(session, co.id)
        for signal in (_trend_signal(totals), _gap_signal(totals)):
            if signal is None:
                continue
            alerts.append({
                "company_id": co.id,
                "company_name": co.name,
                "severity": signal["severity"],
                "message": signal["message"],
                "type": signal["type"],
                "month": signal["month"],
            })

    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (order[a["severity"]], a["company_name"]))
    return alerts
