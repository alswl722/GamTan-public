"""소상공인 탄소중립포인트 트랙 — 판별·자격 판정.

정본: docs/small-business-green-supply-data-plan.md §5·§6.1(판별), §6.2(자격).

이 모듈의 함수는 전부 **조회 시점에 계산하는 함수**다. 판별 결과를 테이블에 저장하지
않는다 — data-plan §5의 설계 의도를 그대로 따른다. 사업장이 계약종별을 바꾸면(사무실을
일반용으로 새로 계약하는 등) 마이그레이션 없이 다음 조회에서 자동으로 바뀌어야 하기
때문이다. `Company`나 신규 테이블에 `business_type` 같은 저장형 컬럼을 만들지 말 것.
"""
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Classification, SourceDocument, Voucher

BusinessScaleHint = Literal["제조업/산업체", "소상공인/상업시설", "미확인"]

# 프론트(web/lib/carbon-point-fixture.ts::BusinessScaleHint)와 문자열까지 같아야 한다 —
# API 응답이 이 값을 그대로 나르고 화면 분기가 문자열 비교로 이뤄진다.
HINT_INDUSTRIAL: BusinessScaleHint = "제조업/산업체"
HINT_COMMERCIAL: BusinessScaleHint = "소상공인/상업시설"
HINT_UNKNOWN: BusinessScaleHint = "미확인"

_CLASS_TO_HINT: dict[str, BusinessScaleHint] = {
    "industrial": HINT_INDUSTRIAL,
    # 주택용도 "소상공인/상업시설"로 본다 — 제도상 대상이 가정용·상업용 전기이고(§6.2),
    # 사업장이 주택용 계약을 쓰는 경우(주택 겸용 점포 등)도 산업용이 아니라는 점에서
    # 판별 목적상 같은 편에 선다. 개인참여 vs 법인참여 구분은 별개 축이며 아직 열린
    # 질문이다(develop-plan §2.6) — 그 결정이 나면 이 매핑이 아니라 축이 하나 늘어난다.
    "commercial": HINT_COMMERCIAL,
    "residential": HINT_COMMERCIAL,
}


def business_scale_hint(session: Session, company_id: int) -> BusinessScaleHint:
    """기업의 최근 전기고지서 계약종별로 사업 규모를 추정한다(저장하지 않음).

    "최근"의 기준은 `(year, month)` 내림차순 — 같은 달에 여러 장이 있으면 나중에 적재된
    것(id 큰 것)을 쓴다. 계약종별을 못 읽은 문서(`contract_type_class`가 null)는 건너뛰고
    더 예전 문서를 본다: 최신 한 장이 파싱 실패했다고 판별을 포기하면, 직전 달에 멀쩡히
    읽은 값이 있는데도 "미확인"으로 떨어진다.

    "미확인"을 반환하는 경우는 둘이고 호출부에서 구분할 필요는 없다(둘 다 §6.1 HITL
    재확인 대상):
      - 전기고지서가 아예 없다(신규 온보딩 직후)
      - 있지만 계약종별을 읽지 못했거나 4종에 안 맞는 계약이다(`unknown`)
    """
    stmt = (
        select(SourceDocument.contract_type_class)
        .where(SourceDocument.company_id == company_id)
        .where(SourceDocument.document_type == "electric_bill")
        .where(SourceDocument.contract_type_class.isnot(None))
        .order_by(
            SourceDocument.year.desc().nullslast(),
            SourceDocument.month.desc().nullslast(),
            SourceDocument.id.desc(),
        )
    )
    for (contract_type_class,) in session.execute(stmt):
        hint = _CLASS_TO_HINT.get(contract_type_class)
        if hint is not None:
            return hint
    return HINT_UNKNOWN


# ── 월별 사용량 조회 ────────────────────────────────────────────────────────

# 감축률이 다루는 에너지원별 활동량 단위. 지금은 전기만 실제로 채워진다 —
# 수도·도시가스는 파싱 로직이 아직 없다(develop-plan §2.5).
FUEL_ELECTRICITY = "전기"


@dataclass(frozen=True)
class MonthlyUsage:
    """한 달의 사용량. `kwh`가 None이면 "미확인"이고 0과 구분된다.

    0과 None을 왜 구분하나: `Classification.activity_amount`는 계산이 사람검토로
    빠졌을 때도 0.0이 된다(calc_engine이 배출계수를 못 찾거나 수량이 없으면 `_review`).
    이걸 "그 달에 전기를 안 썼다"로 읽으면 기준값 평균이 낮아져 감축률이 부풀려진다
    (CLAUDE.md 원칙7 — 미산정을 0으로 합산하지 않는다).
    """
    year: int
    month: int
    kwh: float | None

    @property
    def is_known(self) -> bool:
        return self.kwh is not None


def monthly_electricity_usage(session: Session, company_id: int) -> list[MonthlyUsage]:
    """기업의 월별 전기 사용량(kWh) 시계열 — 연·월 오름차순, 기간 제한 없음.

    `get_classifications()`를 쓸 수 없어서 새로 만든다 — 그 함수의 반환 dict엔 year·month가
    없다(화면용 목록이라 월 시계열이 아니다).

    사용량의 출처는 `Classification.activity_amount`다. 전기는 `calc_engine._QUANTITY_ONLY`에
    속해 금액÷단가 역산 경로가 원천 차단돼 있어서, 값이 있으면 그건 고지서에 인쇄된 실측
    kWh다(추정치가 섞일 수 없다). 단위가 kWh가 아닌 행은 제외한다 — 데이터 사고로 다른
    단위가 섞였을 때 조용히 합산하지 않기 위함.

    같은 달에 고지서가 여러 장이면(재발행·분할 청구) 합산한다. 단 그중 하나라도 미확인이면
    그 달 전체를 미확인으로 둔다 — 일부만 더하면 실제보다 적은 사용량이 되어 감축률이
    부풀려지기 때문이다.
    """
    stmt = (
        select(Voucher.year, Voucher.month, Classification.activity_amount, Classification.activity_unit)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where(Classification.fuel_type == FUEL_ELECTRICITY)
        .order_by(Voucher.year, Voucher.month)
    )

    buckets: dict[tuple[int, int], list[float | None]] = {}
    for year, month, amount, unit in session.execute(stmt):
        known = amount is not None and amount > 0 and (unit is None or unit.lower() == "kwh")
        buckets.setdefault((year, month), []).append(float(amount) if known else None)

    result: list[MonthlyUsage] = []
    for (year, month) in sorted(buckets):
        values = buckets[(year, month)]
        total = None if any(v is None for v in values) else sum(values)
        result.append(MonthlyUsage(year=year, month=month, kwh=total))
    return result


# ── 감축률 계산 ─────────────────────────────────────────────────────────────

# 자격 임계값(%). 프론트 상수 CARBON_POINT_THRESHOLD_PCT와 같은 값이어야 한다.
THRESHOLD_PCT = 5.0

# 정산 구간 길이(개월) — "가입월 다음 달부터 6개월 단위로 정산, 6월·12월 지급"(회계 확인).
SETTLEMENT_MONTHS = 6

# 기준값 산출 전략. **아직 회계 확정 전이라 파라미터로 둔다**(data-plan §15.1 미확인 항목).
#   same_period_avg : 과거 2년의 **같은 구간** 평균 (예: 2026년 1~6월 vs 2024·2025년 1~6월 평균)
#   all_months_avg  : 과거 24개월 **전체** 평균 × 구간 길이
# 기본값은 same_period_avg다 — 계절성을 보존한다. all_months_avg는 비수기 구간을 연중
# 평균과 비교하게 되어 실제로 줄이지 않았는데도 감축률이 부풀려진다(S001 실측: 같은 구간
# 비교 6.74% vs 전체 평균 비교 11.37% — 인센티브 구간이 20,000P/40,000P로 갈린다).
# 골든셋 CSV의 avg_prior_2yr_kwh도 같은 달 기준으로 계산돼 있어 회계가 이쪽을 상정한 것으로
# 보이지만, 확정되면 이 기본값만 바꾸면 된다.
BaselineStrategy = Literal["same_period_avg", "all_months_avg"]
DEFAULT_BASELINE_STRATEGY: BaselineStrategy = "same_period_avg"


@dataclass(frozen=True)
class ReductionResult:
    """감축률 산정 결과.

    `reduction_rate_pct`는 **퍼센트**다(7.4 = 7.4%). 비율(0.074)이 아니다 — API 응답과
    프론트 fixture가 이 단위로 확정돼 있다. 계산 불가면 None이고 0이 아니다(원칙7).

    이 값은 감탄의 자체 예상치이고 공식 판정이 아니다 — 실제 판정은 한국환경공단이 한전
    등에서 사용량을 직접 받아 반기마다 자체 계산한다(CLAUDE.md §5 원칙10).
    """
    reduction_rate_pct: float | None
    eligible: bool
    baseline_usage_kwh: float | None
    target_usage_kwh: float | None
    baseline_months_used: int
    strategy: BaselineStrategy
    # 기준 데이터가 2년치가 안 돼 1년치로 대체했는지 — 신규 가입자 예외(회계 확인).
    used_newcomer_fallback: bool
    # 계산이 안 된 이유. 성공이면 None. 화면의 missing_data 문구로 이어진다.
    reason: str | None = None


def _window(year: int, start_month: int, months: int = SETTLEMENT_MONTHS) -> list[tuple[int, int]]:
    """(year, start_month)부터 months개월치 (연, 월) 목록. 연도 경계를 넘어간다."""
    base = year * 12 + (start_month - 1)
    return [((base + i) // 12, (base + i) % 12 + 1) for i in range(months)]


def _sum_window(usage: dict[tuple[int, int], float | None], window: list[tuple[int, int]]) -> float | None:
    """구간 합계. 구간 안에 미확인·결손 달이 하나라도 있으면 None.

    일부만 더해서 비교하면 월수가 안 맞아 감축률이 왜곡된다 — 없는 달을 0으로 채우지도,
    있는 달만 더하지도 않는다(원칙7과 같은 결).
    """
    total = 0.0
    for key in window:
        value = usage.get(key)
        if value is None:
            return None
        total += value
    return total


def compute_reduction_rate(
    monthly: list[MonthlyUsage],
    target_year: int,
    target_start_month: int,
    *,
    strategy: BaselineStrategy = DEFAULT_BASELINE_STRATEGY,
    months: int = SETTLEMENT_MONTHS,
) -> ReductionResult:
    """감축률(%) 산정 — 결정론적 순수 함수. LLM 개입 없음(원칙1).

    판정 대상은 `(target_year, target_start_month)`부터 `months`개월 구간이다. 회계 확인
    기준대로 매월 각각이 아니라 **정산 구간 단위**로 판정한다.

    기준값은 과거 2년 → 없으면 1년(신규 가입자 예외). 2년도 1년도 안 되면 계산하지 않고
    이유를 담아 반환한다 — 억지로 있는 달만 평균하면 월수가 안 맞아 감축률이 왜곡된다.
    """
    usage = {(m.year, m.month): m.kwh for m in monthly}
    target_window = _window(target_year, target_start_month, months)
    target_total = _sum_window(usage, target_window)
    if target_total is None:
        return ReductionResult(None, False, None, None, 0, strategy, False,
                               reason="감축년도 사용량이 아직 다 모이지 않았어요")

    # 과거 2년 → 1년 순으로 시도한다. 신규 가입자는 2년치가 없으므로 1년으로 대체한다
    # (회계 확인 규칙 — 누락하면 신규 온보딩 기업이 전부 계산 불가가 된다).
    for years_back, newcomer in ((2, False), (1, True)):
        if strategy == "same_period_avg":
            windows = [_window(target_year - n, target_start_month, months) for n in range(1, years_back + 1)]
            totals = [_sum_window(usage, w) for w in windows]
            if any(t is None for t in totals):
                continue
            baseline = sum(totals) / len(totals)
            months_used = months * years_back
        else:  # all_months_avg — 과거 N년 전체를 한 덩어리로 평균한 뒤 구간 길이로 환산
            all_months = [
                key for n in range(1, years_back + 1)
                for key in _window(target_year - n, target_start_month, 12)
            ]
            values = [usage.get(k) for k in all_months]
            if any(v is None for v in values):
                continue
            baseline = sum(values) / len(values) * months
            months_used = len(all_months)

        if baseline <= 0:
            return ReductionResult(None, False, baseline, target_total, months_used, strategy, newcomer,
                                   reason="기준년도 사용량이 0이라 감축률을 계산할 수 없어요")

        rate = round((baseline - target_total) / baseline * 100, 2)
        return ReductionResult(
            reduction_rate_pct=rate,
            eligible=rate >= THRESHOLD_PCT,
            baseline_usage_kwh=round(baseline, 2),
            target_usage_kwh=round(target_total, 2),
            baseline_months_used=months_used,
            strategy=strategy,
            used_newcomer_fallback=newcomer,
        )

    return ReductionResult(None, False, None, round(target_total, 2), 0, strategy, False,
                           reason="비교할 과거 사용량이 부족해요 (최소 1년치 필요)")


# ── 정산 주기 ───────────────────────────────────────────────────────────────

# 인센티브 지급월 — 반기 정산(6월·12월). 회계 확인 사항.
PAYOUT_MONTHS = (6, 12)

# 정산 구간을 어떻게 끊나. **미확정이라 둘 다 지원한다.**
#   enrollment_rolling : 가입월 다음 달부터 6개월 (기업마다 구간이 다르다)
#   fixed_half         : 달력 반기 고정 1~6월 / 7~12월 (전 기업이 같은 구간)
# "가입월 다음 달부터 6개월 단위"와 "6월·12월 지급"이 조합되면 두 해석이 다 성립한다 —
# 예: 3월 가입이면 rolling은 4~9월 구간인데 지급은 12월이 된다. 회계 확인 대기 중이라
# 기본값만 정해두고 함수 구조는 둘 다 태울 수 있게 남긴다.
SettlementWindowMode = Literal["enrollment_rolling", "fixed_half"]
DEFAULT_SETTLEMENT_MODE: SettlementWindowMode = "enrollment_rolling"


@dataclass(frozen=True)
class SettlementPeriod:
    """정산 구간 하나 — 집계 대상 6개월과 그 결과가 지급되는 달."""
    start_year: int
    start_month: int
    end_year: int
    end_month: int
    payout_year: int
    payout_month: int


def _next_payout(year: int, month: int) -> tuple[int, int]:
    """(year, month) **이후** 첫 지급월(6월·12월)."""
    for candidate in PAYOUT_MONTHS:
        if month < candidate:
            return year, candidate
    return year + 1, PAYOUT_MONTHS[0]


def settlement_period(
    enrolled_year: int,
    enrolled_month: int,
    *,
    mode: SettlementWindowMode = DEFAULT_SETTLEMENT_MODE,
) -> SettlementPeriod:
    """가입 시점 → 첫 정산 구간과 지급월.

    §4 알림·신청서가 "언제 지급되는지" 안내할 때 쓴다. 집계 시작은 가입월이 아니라
    **가입월 다음 달**이다(회계 확인) — 가입한 달은 이미 지난 사용량이라 제외한다.
    """
    if mode == "fixed_half":
        # 가입 다음 달이 속한 달력 반기를 집계 구간으로 삼는다.
        start_year, start_month = _window(enrolled_year, enrolled_month + 1, 1)[0]
        start_month = 1 if start_month <= 6 else 7
    else:
        start_year, start_month = _window(enrolled_year, enrolled_month + 1, 1)[0]

    window = _window(start_year, start_month, SETTLEMENT_MONTHS)
    end_year, end_month = window[-1]
    payout_year, payout_month = _next_payout(end_year, end_month)
    return SettlementPeriod(start_year, start_month, end_year, end_month, payout_year, payout_month)
