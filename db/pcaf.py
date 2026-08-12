"""PCAF 데이터 품질 등급 산정 — 저장된 Classification 을 읽어 집계(읽기 전용).

⚠️ 등급 정의는 회계 담당 최종 확인 전 **임시안**이다 (CLAUDE.md §4 '790조'·
   PCAF 공개 방법론의 축소 적용). 코드가 유일한 명세이므로 여기 주석에 고정한다.

  등급 | 조건
  ---- | ----
   2   | 전표에 실측 수량(kWh/L/m³)이 있어 그대로 사용(measured). 회계 '수량 우선' 규칙.
   3   | 수량 없이 금액→물량 환산(spend-based) 추정.
   4   | status='review_required' (HITL 미확정) — emission 0이라 등급 가중 제외.
   5   | 결손월(voucher 자체가 없음) → industry_distributions 업종 평균으로 온더플라이 보정.

Before(기준선)은 항상 5등급 — 전표 없이 매출/업종 통계만 대입하는 기존 방식.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.queries import get_coverage, get_distribution
from db.models import Classification, Company, Voucher


def portfolio_summary(session: Session) -> dict:
    """관리자 대시보드 — 거래 기업 전체의 금융배출량 집계 + PCAF 등급 분포.

    각 기업의 company_pcaf_summary 를 재사용해 실측(after) 우선, 없으면 기준선(before)
    으로 합산한다. 데모는 시연 기업 1곳이지만 로직은 N개 기업으로 그대로 확장된다
    — 프론트가 company_count 를 정직하게 표기(현재 1개 → 결선 포트폴리오).
    """
    companies = session.execute(select(Company).order_by(Company.id)).scalars().all()
    grade_dist = {g: 0 for g in range(1, 6)}
    per_company = []
    s1_total = s2_total = 0.0
    grade_weight = 0.0        # Σ(등급 × 배출량) — 배출가중 평균등급용
    measured_total = 0.0      # 전표 실측분 (결손월 업종평균 보정분 제외)

    for co in companies:
        summ = company_pcaf_summary(session, co.id)
        after = summ["after"]
        used = after or summ["before"]         # 분류 미실행 기업은 기준선(5등급)으로
        s1 = used.get("scope1", 0.0) or 0.0
        s2 = used.get("scope2", 0.0) or 0.0
        grade = used["grade"]
        grade_dist[grade] = grade_dist.get(grade, 0) + 1
        s1_total += s1
        s2_total += s2
        grade_weight += grade * (s1 + s2)
        measured_total += (after or {}).get("measured_tco2e", 0.0) or 0.0
        per_company.append({
            "company_id": co.id,
            "company_name": co.name,
            "industry_name": co.industry_name,
            "grade": grade,
            "measured": after is not None,       # 전표 기반 실측인지, 기준선 추정인지
            "scope1": round(s1, 2),
            "scope2": round(s2, 2),
            "total": round(s1 + s2, 2),
            "hitl_count": (after or {}).get("hitl_count", 0),
        })

    total = s1_total + s2_total
    return {
        "company_count": len(companies),
        "scope1_total": round(s1_total, 2),
        "scope2_total": round(s2_total, 2),
        "total": round(total, 2),
        "grade_distribution": grade_dist,        # {등급: 기업수} — 도입 후(실측)
        # 도입 전 기준선은 정의상 전 기업 5등급 (매출·업종 통계 대입) — 대시보드 Before/After용
        "before_distribution": {g: (len(companies) if g == 5 else 0) for g in range(1, 6)},
        # 배출가중 평균등급 — 큰 배출원의 데이터 품질이 포트폴리오 품질을 좌우하므로 건수평균 아님
        "avg_grade": round(grade_weight / total, 1) if total else None,
        # 실측 커버리지 — 전체 배출량 중 실제 전표로 산정된 비율(나머지는 결손월 업종평균 보정)
        "measured_coverage_pct": round(measured_total / total * 100, 1) if total else 0.0,
        "hitl_total": sum(c["hitl_count"] for c in per_company),
        "reviewed_today": _reviewed_today(session),
        "companies": per_company,
    }


def _reviewed_today(session: Session) -> int:
    """오늘(UTC 자정 이후) 담당자가 확정/반려로 마감한 건수 — 메인 대시보드 진행 현황용."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return session.execute(
        select(func.count(Classification.id)).where(Classification.reviewed_at >= today_start)
    ).scalar_one()

# get_coverage 의 연료 대분류 → Scope 매핑 (결손 보정 시 어느 Scope 에 얹을지)
_FUEL_BUCKET_SCOPE = {"전기": 2, "가스": 1, "경유/유류": 1}

# Classification.fuel_type(세분류, api/agent/llm_classify.py 스키마) → get_coverage와
# 같은 3대분류로 묶는다 — 리포트의 "항목별 상세"가 결손 보정 문구("2월 전기 고지서…")와
# 같은 용어를 쓰게 하기 위함(새 분류체계를 따로 만들지 않음).
_FUEL_TYPE_TO_BUCKET = {
    "전기": "전기",
    "도시가스": "가스",
    "경유": "경유/유류",
    "휘발유": "경유/유류",
    "LPG": "경유/유류",
}


def _fuel_bucket(fuel_type: str | None) -> str:
    return _FUEL_TYPE_TO_BUCKET.get(fuel_type or "", "기타")


def _clip_grade(g: float) -> int:
    return max(1, min(5, round(g)))


def company_pcaf_summary(session: Session, company_id: int) -> dict:
    """기업의 PCAF Before/After + 벤치마킹. 분류 미실행 시 after=None."""
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company_id={company_id} 없음")

    dist1 = get_distribution(session, company.industry_code, 1)
    dist2 = get_distribution(session, company.industry_code, 2)

    before = _before_baseline(company, dist1, dist2)
    after = _after_measured(session, company_id, dist1, dist2)
    benchmark = _benchmark(company, dist1, dist2, after)

    return {"before": before, "after": after, "benchmark": benchmark}


def _before_baseline(company, dist1, dist2) -> dict:
    """기존 방식 — 업종 인당 중앙값 × 종업원수 (매출 통계 대입의 대용). 항상 5등급.

    industry_distributions.median 은 이미 tCO2e 단위다.
    """
    emp = company.employee_count or 0
    s1 = (dist1["median_per_employee"] or 0) * emp if dist1 else 0.0
    s2 = (dist2["median_per_employee"] or 0) * emp if dist2 else 0.0
    return {
        "grade": 5,
        "scope1": round(s1, 2),
        "scope2": round(s2, 2),
        "emission_tco2e": round(s1 + s2, 2),
        "basis": "업종 인당 중앙값 × 종업원수 (매출 통계 대입 추정, 실측 아님)",
    }


def _after_measured(session, company_id, dist1, dist2) -> dict | None:
    """전표 기반 실측 — 저장된 Classification 집계 + 결손월 업종 평균 보정.

    분류가 한 건도 없으면 None (프론트가 '③ 먼저 실행하세요' 안내).
    emission_co2e 는 kgCO2e 로 저장돼 있으므로 ÷1000 해 tCO2e 로 집계한다.
    """
    rows = (
        session.execute(
            select(Classification, Voucher)
            .join(Voucher, Classification.voucher_id == Voucher.id)
            .where(Voucher.company_id == company_id)
        )
        .all()
    )
    # 담당자가 반려한 건(status='rejected')은 분류를 신뢰할 수 없다는 판정이므로 집계 제외
    scored = [
        (c, v) for c, v in rows
        if c.scope in (1, 2) and c.emission_co2e and c.status != "rejected"
    ]
    hitl_count = sum(1 for c, v in rows if c.status == "review_required")
    if not scored:
        return None

    # 실측분 — Scope 별 합산(kg→t)과 등급 가중용 누적. 연료 대분류별로도 같이 쌓아
    # "항목별 상세"(리포트 화면)의 재료로 쓴다.
    # 등급: 전표 실측 수량 기반=2 / 금액 추정(spend-based)=3 (HITL은 emission 0이라 가중 제외).
    measured_kg = {1: 0.0, 2: 0.0}
    measured_by_bucket_kg: dict[str, float] = {}
    grade_weight = 0.0   # Σ(등급 × 배출량)
    total_weight = 0.0   # Σ(배출량)
    for c, v in scored:
        kg = float(c.emission_co2e)
        measured_kg[c.scope] += kg
        bucket = _fuel_bucket(c.fuel_type)
        measured_by_bucket_kg[bucket] = measured_by_bucket_kg.get(bucket, 0.0) + kg
        item_grade = 2 if (v.raw_json or {}).get("quantity") else 3
        grade_weight += item_grade * kg
        total_weight += kg

    # 결손월 보정 — 없는 월은 업종 중앙값을 12분배해 5등급으로 가산
    coverage = get_coverage(session, company_id)
    gap_kg = {1: 0.0, 2: 0.0}
    gap_by_bucket_kg: dict[str, float] = {}
    gap_detail = []
    for gap in coverage["gaps"]:
        scope = _FUEL_BUCKET_SCOPE.get(gap["fuel"])
        dist = dist1 if scope == 1 else dist2
        if not scope or not dist or not dist["median"]:
            continue
        months = gap["missing_months"]
        # dist median 은 tCO2e → kg 로 환산(×1000) 후 12분배
        est_kg = (dist["median"] * 1000.0 / 12.0) * len(months)
        gap_kg[scope] += est_kg
        gap_by_bucket_kg[gap["fuel"]] = gap_by_bucket_kg.get(gap["fuel"], 0.0) + est_kg
        grade_weight += 5 * est_kg
        total_weight += est_kg
        gap_detail.append({"fuel": gap["fuel"], "missing_months": months})

    by_fuel = [
        {
            "fuel": bucket,
            "measured_tco2e": round(measured_by_bucket_kg.get(bucket, 0.0) / 1000.0, 2),
            "estimated_tco2e": round(gap_by_bucket_kg.get(bucket, 0.0) / 1000.0, 2),
            "total_tco2e": round(
                (measured_by_bucket_kg.get(bucket, 0.0) + gap_by_bucket_kg.get(bucket, 0.0)) / 1000.0, 2
            ),
        }
        for bucket in sorted(
            set(measured_by_bucket_kg) | set(gap_by_bucket_kg),
            key=lambda b: -(measured_by_bucket_kg.get(b, 0.0) + gap_by_bucket_kg.get(b, 0.0)),
        )
    ]

    s1_t = (measured_kg[1] + gap_kg[1]) / 1000.0
    s2_t = (measured_kg[2] + gap_kg[2]) / 1000.0
    grade = _clip_grade(grade_weight / total_weight) if total_weight else 3

    # 결손분이 5등급 대신 실측(spend-based=3등급)으로 채워졌다면 등급이 어디까지
    # 오르는지 역산 — 등급 상승 후보 안내(§6 "등급 상승 역산 요청")의 재료.
    gap_total_kg = sum(gap_kg.values())
    if gap_total_kg > 0 and total_weight:
        resolved_weight = grade_weight - 5 * gap_total_kg + 3 * gap_total_kg
        projected_grade = _clip_grade(resolved_weight / total_weight)
    else:
        projected_grade = grade

    return {
        "grade": grade,
        "scope1": round(s1_t, 2),
        "scope2": round(s2_t, 2),
        "total": round(s1_t + s2_t, 2),
        "measured_tco2e": round((measured_kg[1] + measured_kg[2]) / 1000.0, 2),
        "estimated_gap_tco2e": round((gap_kg[1] + gap_kg[2]) / 1000.0, 2),
        "hitl_count": hitl_count,
        "gap_months": gap_detail,
        "projected_grade": projected_grade,
        "by_fuel": by_fuel,
    }


def _benchmark(company, dist1, dist2, after) -> dict:
    """동종 업종 대비 위치 — min/median/max 안에서의 백분위(낮을수록 상위)."""
    industry_name = (dist1 or dist2 or {}).get("industry_name") or company.industry_name
    result = {
        "industry_code": company.industry_code,
        "industry_name": industry_name,
        "percentile_text": None,
        "hint": "가스 고지서를 추가 연동하면 결손월 보정분이 실측으로 바뀌어 등급이 오릅니다.",
        # 프론트 분포 시각화용 — 값이 없으면 전부 None
        "value": None,
        "min": None,
        "median": None,
        "max": None,
        "percentile_pct": None,
    }
    # 실측 총량이 있으면 그걸로, 없으면 Before 추정으로 위치 계산
    value = after["total"] if after else None
    lo = (dist1 or {}).get("min", 0) + (dist2 or {}).get("min", 0)
    hi = (dist1 or {}).get("max", 0) + (dist2 or {}).get("max", 0)
    med = (dist1 or {}).get("median", 0) + (dist2 or {}).get("median", 0)
    if value is not None and hi > lo:
        pct = max(0.0, min(1.0, (value - lo) / (hi - lo)))
        result["percentile_text"] = f"동종 {industry_name} 대비 상위 {round(pct * 100)}%"
        result["value"] = round(value, 2)
        result["min"] = round(lo, 2)
        result["median"] = round(med, 2)
        result["max"] = round(hi, 2)
        result["percentile_pct"] = round(pct * 100)
    return result


def upgrade_candidate_for_company(session: Session, company_id: int) -> dict | None:
    """단일 기업의 등급 상승 후보 판정 — rate_upgrade_candidates와 db/rate_approvals.py
    (승인요청 큐 생성 시 스냅샷)가 동일 판정 로직을 공유하도록 분리했다.

    결손이 없거나, 결손을 채워도 등급이 안 오르면 None(후보 아님).
    """
    company = session.get(Company, company_id)
    if company is None:
        return None
    dist1 = get_distribution(session, company.industry_code, 1)
    dist2 = get_distribution(session, company.industry_code, 2)
    after = _after_measured(session, company_id, dist1, dist2)
    if not after or not after["gap_months"]:
        return None
    if after["projected_grade"] >= after["grade"]:
        return None

    fuels = ", ".join(dict.fromkeys(g["fuel"] for g in after["gap_months"]))
    missing_month_count = sum(len(g["missing_months"]) for g in after["gap_months"])
    return {
        "company_id": company.id,
        "company_name": company.name,
        "current_grade": after["grade"],
        "target_grade": after["projected_grade"],
        "missing": f"{fuels} 고지서 {missing_month_count}개월분",
        "benefit": f"PCAF {after['grade']}등급 → {after['projected_grade']}등급 시 우대금리 대상 안내 가능",
    }


def rate_upgrade_candidates(session: Session) -> list[dict]:
    """등급 상승 역산 후보 — 결손월만 채우면 PCAF 등급이 오르는 기업 목록.

    에이전트 행동 "등급 상승 역산 요청"(CLAUDE.md §6)의 관리자 화면 대응.
    여신 결정이 아니라 우대금리 '자격 안내'까지만 다룬다(CLAUDE.md §9).
    """
    companies = session.execute(select(Company).order_by(Company.id)).scalars().all()
    candidates = []
    for co in companies:
        candidate = upgrade_candidate_for_company(session, co.id)
        if candidate is not None:
            candidates.append(candidate)
    return candidates
