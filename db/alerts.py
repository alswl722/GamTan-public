"""이상 신호 알림 — 여신 리스크 조기 경보(EWS)용 결정론적 감지 함수.

은행권 여신 조기경보 실무의 두 축을 코드로 옮긴다:
  1. 추세 이탈 — 최근 3개월 이동평균 대비 최신월 배출량 급등/급감
  2. 데이터 공백 — 연속 미연동 자체가 조업 중단·이탈 조짐일 수 있는 신호

사장님 탄소리포트에는 위 EWS와 함께 에이전트가 이미 감지해 Classification에
영속화한 월×연료 이상치도 보여준다. 판단은 여기서 끝내지 않고 문구로만 안내하며,
여신 결정에는 사용하지 않는다(CLAUDE.md §9).
"""
from datetime import datetime, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Classification, Company, Voucher

SPIKE_RATIO = 1.5
DROP_RATIO = 0.5
TREND_WINDOW = 3
GAP_MONTHS_THRESHOLD = 3

_ANOMALY_STATE_PRIORITY = {
    "disputed": 0,
    "unknown": 1,
    "pending": 2,
    "confirmed_normal": 3,
}
_ANOMALY_STATE_SEVERITY = {
    "disputed": "high",
    "unknown": "medium",
    "pending": "high",
    "confirmed_normal": "low",
}
_ANOMALY_STATE_SUFFIX = {
    "disputed": "확인이 필요한 건으로 표시됐어요.",
    "unknown": "확인이 어려워 담당자 검토로 넘겼어요.",
    "pending": "아직 확인 전이에요.",
    "confirmed_normal": "정상 사용으로 확인됐어요.",
}


def _monthly_totals(
    session: Session, company_id: int, *, year: int | None = None,
) -> dict[int, float]:
    """기업의 월별 Scope 1+2 배출량 합계(kg) — 확정된 건만, 존재하는 월만."""
    return _monthly_totals_by_company(session, company_id=company_id, year=year).get(company_id, {})


def _monthly_totals_by_company(
    session: Session,
    company_id: int | None = None,
    *,
    year: int | None = None,
) -> dict[int, dict[int, float]]:
    """월별 배출량 합계를 기업 단위로 한 번에 묶어 반환한다.

    ``year``를 주면 해당 보고연도만 집계한다. 관리자 포트폴리오 호출은 기존처럼
    year=None으로 전 기업을 한 번에 가져와 N+1을 피한다.
    """
    stmt = (
        select(Voucher.company_id, Voucher.month, Classification.emission_co2e)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(
            Classification.scope.in_((1, 2)),
            Classification.status.in_(("auto", "confirmed")),
        )
    )
    if company_id is not None:
        stmt = stmt.where(Voucher.company_id == company_id)
    if year is not None:
        stmt = stmt.where(Voucher.year == year)
    rows = session.execute(stmt).all()

    by_company: dict[int, dict[int, float]] = {}
    for cid, month, emission in rows:
        totals = by_company.setdefault(int(cid), {})
        totals[int(month)] = totals.get(int(month), 0.0) + float(emission or 0)
    return by_company


def _trend_signal(totals: dict[int, float]) -> dict | None:
    """최신월과 달력상 직전 3개월 이동평균을 비교해 급등·급감 하나만 반환한다."""
    months = sorted(totals)
    if not months:
        return None

    latest = months[-1]
    baseline_months = [latest - i for i in range(1, TREND_WINDOW + 1)]
    if not all(m in totals for m in baseline_months):
        return None

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
            "message": f"{latest}월 배출량이 최근 {TREND_WINDOW}개월 평균보다 {ratio:.1f}배 늘었어요",
        }
    if ratio <= DROP_RATIO:
        return {
            "type": "drop",
            "severity": "medium",
            "month": latest,
            "ratio": round(ratio, 2),
            "message": (
                f"{latest}월 배출량이 최근 {TREND_WINDOW}개월 평균보다 "
                f"{ratio:.1f}배 줄었어요. 가동률이 낮아진 건 아닌지 확인해보세요"
            ),
        }
    return None


def _gap_signal(totals: dict[int, float], *, as_of: datetime | None = None) -> dict | None:
    """최신 데이터 이후 올해 안에서 3개월 이상 연속 공백이면 알림을 반환한다."""
    if not totals:
        return None
    last_reported = max(totals)
    current_month = (as_of or datetime.now(timezone.utc)).month
    missing = [m for m in range(last_reported + 1, current_month + 1)]
    if len(missing) >= GAP_MONTHS_THRESHOLD:
        return {
            "type": "gap",
            "severity": "medium",
            "month": last_reported,
            "missing_months": missing,
            "message": f"{last_reported}월 이후 {len(missing)}개월째 전표가 연동되지 않았어요",
        }
    return None


def detect_alerts(
    session: Session,
    company_id: int | None = None,
    *,
    year: int | None = None,
) -> list[dict]:
    """EWS 이상 신호 목록 — severity 내림차순, 그다음 기업명 순."""
    stmt = select(Company).order_by(Company.id)
    if company_id is not None:
        stmt = stmt.where(Company.id == company_id)
    companies = session.execute(stmt).scalars().all()

    totals_by_company = _monthly_totals_by_company(
        session, company_id=company_id, year=year,
    )

    alerts = []
    for company in companies:
        totals = totals_by_company.get(company.id, {})
        for signal in (_trend_signal(totals), _gap_signal(totals)):
            if signal is None:
                continue
            alert = {
                "company_id": company.id,
                "company_name": company.name,
                "severity": signal["severity"],
                "message": signal["message"],
                "type": signal["type"],
                "month": signal["month"],
            }
            if year is not None:
                alert["year"] = year
            alerts.append(alert)

    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda alert: (order[alert["severity"]], alert["company_name"]))
    return alerts


def _persisted_anomaly_alerts(
    session: Session,
    company_id: int,
    *,
    year: int | None = None,
) -> list[dict]:
    """Classification에 저장된 이상치를 연도×월×연료별 한 알림으로 투영한다.

    과거 단건 답변으로 한 그룹의 상태가 섞였을 수 있어 가장 보수적인 상태
    (disputed > unknown > pending > confirmed_normal)를 대표 상태로 사용한다.
    일반 Classification.status와 무관하게 읽는다. disputed/unknown 답변은 그 status를
    review_required로 바꾸므로 owner-visible 필터를 다시 적용하면 중요한 알림이
    답변 직후 사라지기 때문이다.
    """
    company = session.get(Company, company_id)
    if company is None:
        return []

    stmt = (
        select(
            Voucher.year,
            Voucher.month,
            Classification.fuel_type,
            Classification.anomaly_check_status,
            Classification.anomaly_ratio,
        )
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            Classification.anomaly_check_status.is_not(None),
        )
    )
    if year is not None:
        stmt = stmt.where(Voucher.year == year)

    grouped: dict[tuple[int, int, str], dict] = {}
    for item_year, month, fuel, status, ratio in session.execute(stmt).all():
        if status not in _ANOMALY_STATE_PRIORITY:
            continue
        key = (int(item_year), int(month), str(fuel or "해당 연료"))
        current = grouped.get(key)
        ratio_value = float(ratio) if ratio is not None else None
        if current is None:
            grouped[key] = {"status": status, "ratio": ratio_value}
            continue
        if _ANOMALY_STATE_PRIORITY[status] < _ANOMALY_STATE_PRIORITY[current["status"]]:
            current["status"] = status
        if ratio_value is not None:
            current["ratio"] = max(current["ratio"] or ratio_value, ratio_value)

    alerts = []
    for (item_year, month, fuel), item in grouped.items():
        status = item["status"]
        ratio = item["ratio"]
        if ratio is None:
            lead = f"{item_year}년 {month}월 {fuel} 사용량에서 이상 신호가 감지됐어요."
        else:
            lead = f"{item_year}년 {month}월 {fuel} 사용량이 평소보다 {ratio:.1f}배 많아요."
        message = lead if status == "pending" else f"{lead} {_ANOMALY_STATE_SUFFIX[status]}"
        alerts.append({
            "company_id": company.id,
            "company_name": company.name,
            "severity": _ANOMALY_STATE_SEVERITY[status],
            "type": "anomaly",
            "year": item_year,
            "month": month,
            "fuel": fuel,
            "ratio": ratio,
            "anomaly_status": status,
            "message": message,
        })

    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda alert: (
        order[alert["severity"]], alert["year"], alert["month"], alert["fuel"],
    ))
    return alerts


def _inventory_gap_alerts(
    session: Session,
    company_id: int,
    *,
    year: int | None,
) -> list[dict]:
    """완전성 카드와 같은 기준의 결손월을 연료별 한 알림으로 투영한다.

    보고연도가 없는 호출은 anomaly/EWS의 기존 다년 동작을 유지하기 위해 건드리지
    않는다. 탄소리포트는 quality-report가 확정한 reporting_year를 항상 전달한다.
    """
    if year is None:
        return []

    company = session.get(Company, company_id)
    if company is None:
        return []

    # 순환 import 가능성을 피하고 owner 리포트에서만 품질 엔진을 로드한다.
    from db.pcaf_engine.pcaf_quality import assess_inventory_completeness

    missing_by_fuel: dict[str, set[int]] = {}
    for scope_group in ("scope_1", "scope_2"):
        assessment = assess_inventory_completeness(
            session, company_id, year, scope_group,
        )
        for fuel, months in assessment.missing_months.items():
            missing_by_fuel.setdefault(str(fuel), set()).update(int(month) for month in months)

    fuel_labels = {"가스": "도시가스"}
    alerts = []
    for fuel in sorted(missing_by_fuel):
        months = sorted(missing_by_fuel[fuel])
        if not months:
            continue
        month_text = "·".join(str(month) for month in months)
        alerts.append({
            "company_id": company.id,
            "company_name": company.name,
            "severity": "medium",
            "type": "gap",
            "year": year,
            "month": months[0],
            "fuel": fuel,
            "missing_months": months,
            "message": f"{year}년 {month_text}월 {fuel_labels.get(fuel, fuel)} 자료가 비어 있어요.",
        })
    return alerts


def _pending_usage_review_alerts(
    session: Session,
    company_id: int,
    *,
    year: int | None = None,
) -> list[dict]:
    """전기·도시가스 사용량 누락으로 계산하지 못한 일반 HITL을 한 건씩 안내한다.

    문서 자체가 없는 completeness gap이나 사장 확인이 필요한 anomaly와 구분한다.
    calc_failure_reason의 결정론적 계산 엔진 문구를 기준으로 잡아, 수량이 없더라도
    금액 역산 가능한 경유나 연료 분류가 애매한 일반 HITL은 섞지 않는다.
    """
    company = session.get(Company, company_id)
    if company is None:
        return []

    reason_metadata = {
        "전기 사용량 미기재 — 금액 역산 불가": ("전기", "kWh"),
        "도시가스 사용량 미기재 — 금액 역산 불가": ("도시가스", "m³"),
    }
    stmt = (
        select(
            Voucher.year,
            Voucher.month,
            Classification.fuel_type,
            Classification.calc_failure_reason,
        )
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            Classification.status == "review_required",
            Classification.calc_failure_reason.in_(tuple(reason_metadata)),
        )
    )
    if year is not None:
        stmt = stmt.where(Voucher.year == year)

    grouped = {
        (int(item_year), int(month), str(fuel or fuel_label), reason)
        for item_year, month, fuel, reason in session.execute(stmt).all()
        if reason in reason_metadata
        for fuel_label, _unit in (reason_metadata[reason],)
    }

    alerts = []
    for item_year, month, fuel, reason in sorted(grouped):
        fuel_label, unit = reason_metadata[reason]
        alerts.append({
            "company_id": company.id,
            "company_name": company.name,
            "severity": "medium",
            "type": "review",
            "year": item_year,
            "month": month,
            "fuel": fuel,
            "review_reason": "missing_activity_quantity",
            "message": (
                f"{item_year}년 {month}월 {fuel_label} 고지서에 사용량({unit})이 없어 "
                "배출량을 계산하지 못했어요."
            ),
        })
    return alerts


def detect_owner_alerts(
    session: Session,
    company_id: int,
    *,
    year: int | None = None,
) -> list[dict]:
    """사장님 리포트용: 이상치·결손·사용량 검토·기존 EWS를 함께 반환한다."""
    anomalies = _persisted_anomaly_alerts(session, company_id, year=year)
    inventory_gaps = _inventory_gap_alerts(session, company_id, year=year)
    usage_reviews = _pending_usage_review_alerts(session, company_id, year=year)
    ews_alerts = detect_alerts(session, company_id=company_id, year=year)

    anomaly_periods = {(alert["year"], alert["month"]) for alert in anomalies}
    anomaly_months = {alert["month"] for alert in anomalies}
    inventory_gap_periods = {
        (alert["year"], tuple(alert["missing_months"])) for alert in inventory_gaps
    }

    # 기존 EWS gap은 회사 전체의 마지막 연동 이후 공백이다. 완전성 엔진이 같은
    # 보고연도·동일 월 집합을 더 구체적인 연료별 gap으로 설명하면 generic 알림만 뺀다.
    legacy_gap = _gap_signal(_monthly_totals(session, company_id, year=year))
    legacy_gap_period = (
        (year, tuple(legacy_gap["missing_months"]))
        if year is not None and legacy_gap is not None
        else None
    )

    deduplicated_ews = []
    for alert in ews_alerts:
        if alert["type"] in ("spike", "drop"):
            alert_year = alert.get("year")
            if (
                (alert_year is not None and (alert_year, alert["month"]) in anomaly_periods)
                or (alert_year is None and alert["month"] in anomaly_months)
            ):
                continue
        if alert["type"] == "gap" and legacy_gap_period in inventory_gap_periods:
            continue
        deduplicated_ews.append(alert)

    combined = anomalies + inventory_gaps + usage_reviews + deduplicated_ews
    order = {"high": 0, "medium": 1, "low": 2}
    combined.sort(key=lambda alert: (
        order[alert["severity"]],
        alert.get("year") or 0,
        alert["month"],
        alert.get("fuel") or "",
    ))
    return combined
