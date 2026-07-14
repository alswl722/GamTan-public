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
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.queries import get_coverage, get_distribution
from db.models import Classification, Company, Voucher

# get_coverage 의 연료 대분류 → Scope 매핑 (결손 보정 시 어느 Scope 에 얹을지)
_FUEL_BUCKET_SCOPE = {"전기": 2, "가스": 1, "경유/유류": 1}


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
    scored = [(c, v) for c, v in rows if c.scope in (1, 2) and c.emission_co2e]
    hitl_count = sum(1 for c, v in rows if c.status == "review_required")
    if not scored:
        return None

    # 실측분 — Scope 별 합산(kg→t)과 등급 가중용 누적.
    # 등급: 전표 실측 수량 기반=2 / 금액 추정(spend-based)=3 (HITL은 emission 0이라 가중 제외).
    measured_kg = {1: 0.0, 2: 0.0}
    grade_weight = 0.0   # Σ(등급 × 배출량)
    total_weight = 0.0   # Σ(배출량)
    for c, v in scored:
        kg = float(c.emission_co2e)
        measured_kg[c.scope] += kg
        item_grade = 2 if (v.raw_json or {}).get("quantity") else 3
        grade_weight += item_grade * kg
        total_weight += kg

    # 결손월 보정 — 없는 월은 업종 중앙값을 12분배해 5등급으로 가산
    coverage = get_coverage(session, company_id)
    gap_kg = {1: 0.0, 2: 0.0}
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
        grade_weight += 5 * est_kg
        total_weight += est_kg
        gap_detail.append({"fuel": gap["fuel"], "missing_months": months})

    s1_t = (measured_kg[1] + gap_kg[1]) / 1000.0
    s2_t = (measured_kg[2] + gap_kg[2]) / 1000.0
    grade = _clip_grade(grade_weight / total_weight) if total_weight else 3

    return {
        "grade": grade,
        "scope1": round(s1_t, 2),
        "scope2": round(s2_t, 2),
        "total": round(s1_t + s2_t, 2),
        "measured_tco2e": round((measured_kg[1] + measured_kg[2]) / 1000.0, 2),
        "estimated_gap_tco2e": round((gap_kg[1] + gap_kg[2]) / 1000.0, 2),
        "hitl_count": hitl_count,
        "gap_months": gap_detail,
    }


def _benchmark(company, dist1, dist2, after) -> dict:
    """동종 업종 대비 위치 — min/median/max 안에서의 백분위(낮을수록 상위)."""
    industry_name = (dist1 or dist2 or {}).get("industry_name") or company.industry_name
    result = {
        "industry_code": company.industry_code,
        "industry_name": industry_name,
        "percentile_text": None,
        "hint": "가스 고지서를 추가 연동하면 결손월 보정분이 실측으로 바뀌어 등급이 오릅니다.",
    }
    # 실측 총량이 있으면 그걸로, 없으면 Before 추정으로 위치 계산
    value = after["total"] if after else None
    lo = (dist1 or {}).get("min", 0) + (dist2 or {}).get("min", 0)
    hi = (dist1 or {}).get("max", 0) + (dist2 or {}).get("max", 0)
    if value is not None and hi > lo:
        pct = max(0.0, min(1.0, (value - lo) / (hi - lo)))
        result["percentile_text"] = f"동종 {industry_name} 대비 상위 {round(pct * 100)}%"
    return result
