"""소상공인 탄소중립포인트 트랙 — 판별·자격 판정.

정본: docs/small-business-green-supply-data-plan.md §5·§6.1(판별), §6.2(자격).

이 모듈의 함수는 전부 **조회 시점에 계산하는 함수**다. 판별 결과를 테이블에 저장하지
않는다 — data-plan §5의 설계 의도를 그대로 따른다. 사업장이 계약종별을 바꾸면(사무실을
일반용으로 새로 계약하는 등) 마이그레이션 없이 다음 조회에서 자동으로 바뀌어야 하기
때문이다. `Company`나 신규 테이블에 `business_type` 같은 저장형 컬럼을 만들지 말 것.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    CarbonNeutralPointApplication,
    Classification,
    SourceDocument,
    Voucher,
)

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


# ── 자격 판정 결과 조립 (API·알림·신청서 공용) ──────────────────────────────

# 아직 감축률에 반영하지 못한 에너지원. 원문 브레인스토밍은 전기·수도·도시가스 3종을
# 포인트 지급 대상으로 명시하는데 수도·가스는 파싱 로직이 없다(develop-plan §2.5) —
# 전기만으로 계산하면 실제보다 부정확해진다는 사실을 숨기지 않고 missing_data로 노출한다.
MISSING_WATER = "상수도 요금고지서(수도 사용량)"
MISSING_GAS = "도시가스 요금고지서(가스 사용량)"
MISSING_CONTRACT_TYPE = "전기요금고지서의 계약종별"


def evaluate_eligibility(
    session: Session,
    company_id: int,
    target_year: int,
    target_start_month: int = 1,
    *,
    strategy: BaselineStrategy = DEFAULT_BASELINE_STRATEGY,
    months: int = SETTLEMENT_MONTHS,
) -> dict:
    """자격 판정 결과 — `GET /owner/{id}/carbon-point/eligibility` 응답 본문.

    필드명·타입은 프론트 `CarbonPointEligibility`와 **동일해야 한다**(web/lib/
    carbon-point-fixture.ts) — fixture를 이 응답으로 교체할 때 컴포넌트를 안 고치려면
    필드명까지 같아야 한다. `is_estimate` 같은 플래그는 넣지 않는다(2026-08-21 확정,
    이 경로는 항상 예상치만 반환하므로 항상 true인 플래그는 정보량이 없다).

    제조업(산업용 전기)은 제도상 원천 제외라 감축률을 아예 계산하지 않는다(§6.2) —
    계산해서 숨기는 게 아니라 계산 자체를 안 한다.
    """
    hint = business_scale_hint(session, company_id)
    missing: list[str] = []

    if hint == HINT_UNKNOWN:
        missing.append(MISSING_CONTRACT_TYPE)

    if hint != HINT_COMMERCIAL:
        # 제조업·미확인은 감축률을 계산하지 않는다. reduction_rate_pct는 0이 아니라
        # null이다 — "감축 안 했다"가 아니라 "판정 대상이 아니다/모른다"이므로(원칙7).
        return {
            "business_scale_hint": hint,
            "baseline_year": target_year - 1,
            "target_year": target_year,
            "reduction_rate_pct": None,
            "eligible": False,
            "missing_data": missing,
        }

    monthly = monthly_electricity_usage(session, company_id)
    result = compute_reduction_rate(
        monthly, target_year, target_start_month, strategy=strategy, months=months
    )
    if result.reason is not None:
        missing.append(result.reason)
    # 수도·가스는 파싱이 없어 항상 미반영이다 — 감축률이 계산됐을 때만 알린다(계산도 안 된
    # 상태에서 이것까지 나열하면 무엇이 진짜 걸림돌인지 흐려진다).
    if result.reduction_rate_pct is not None:
        missing.extend([MISSING_WATER, MISSING_GAS])

    years_back = 1 if result.used_newcomer_fallback else 2
    return {
        "business_scale_hint": hint,
        "baseline_year": target_year - years_back,
        "target_year": target_year,
        "reduction_rate_pct": result.reduction_rate_pct,
        "eligible": result.eligible,
        "missing_data": missing,
    }


# ── 알림 트리거 ─────────────────────────────────────────────────────────────

# owner_notifications.type — 이 컬럼엔 CHECK 제약이 없어(String(30) 자유형식) 값을
# 코드에서만 관리한다. 기존 값 3종: classification_sent | document_processed |
# document_failed. 30자 제한 안에 들어간다(21자).
NOTIFICATION_TYPE_ELIGIBLE = "carbon_point_eligible"


def notify_if_eligible(
    session: Session,
    company_id: int,
    target_year: int,
    target_start_month: int = 1,
    **kwargs,
) -> "OwnerNotification | None":
    """자격 충족 시 사장님 알림 생성. 이미 있으면 만들지 않고 None.

    "등급 상승 후보 판정" 패턴(`db/pcaf_engine/rate_approvals.py::create_rate_request`)에서
    가져온 것: **근거 없이는 레코드를 만들지 않는다.** 거기서 활동자료가 없으면
    NoUpgradeCandidateError로 거부하는 것과 같은 이유로, 여기서는 자격 미충족·계산 불가면
    조용히 None을 반환한다(빈 알림으로 배너를 채우지 않는 기존 관례 —
    api/routers/admin.py의 `if sent_count > 0` 가드와 같은 결).

    중복 방지: **이 테이블의 첫 중복 방지 로직이다.** owner_notifications엔 유니크 제약도
    기존 dedup 코드도 없다(기존 3종은 잡·전송 액션당 1건이라 문제가 없었다). 여기서는
    조회마다 판정이 돌아 같은 알림이 계속 쌓일 수 있어 가드가 필요하다 — 같은 기업·같은
    타입의 **안 읽은** 알림이 있으면 새로 만들지 않는다.
    이 방식의 한계를 알고 쓴다: 동시 요청 레이스를 막지 못한다(SourceDocument가
    `(company_id, file_hash)` 유니크로 최종 방어선을 둔 것과 대조된다). 폴링으로 읽는 배너라
    최악의 결과가 "알림 2개"뿐이어서 마이그레이션까지 하지 않았다 — 문제가 되면
    `(company_id, type, 정산구간키)` 유니크 인덱스를 새 revision으로 추가하면 된다.

    비보장 문구는 여기 담지 않는다 — data-plan §6.2가 "예상치" 표기를 API가 아니라 프론트
    정적 문구로 강제하기로 확정했다(`CarbonPointCard`가 이미 렌더). 대신 message 자체를
    확정적으로 쓰지 않는다("예상 감축률", "확정"·"지급 확정" 금지).
    """
    from db.models import OwnerNotification

    info = evaluate_eligibility(session, company_id, target_year, target_start_month, **kwargs)
    if not info["eligible"]:
        return None

    existing = session.execute(
        select(OwnerNotification)
        .where(OwnerNotification.company_id == company_id)
        .where(OwnerNotification.type == NOTIFICATION_TYPE_ELIGIBLE)
        .where(OwnerNotification.read_at.is_(None))
    ).scalars().first()
    if existing is not None:
        return None

    rate = info["reduction_rate_pct"]
    note = OwnerNotification(
        company_id=company_id,
        type=NOTIFICATION_TYPE_ELIGIBLE,
        message=(
            f"예상 감축률이 {rate}%로 탄소중립포인트 신청 기준({THRESHOLD_PCT:.0f}%)을 넘었어요. "
            "신청서 초안을 만들어 뒀으니 확인해 보세요."
        ),
        # message는 완성된 문장, payload는 문구를 다시 조립할 수 있는 원자료 —
        # 0023 마이그레이션 docstring이 정한 이 테이블의 규약.
        payload={
            "reduction_rate_pct": rate,
            "threshold_pct": THRESHOLD_PCT,
            "baseline_year": info["baseline_year"],
            "target_year": info["target_year"],
            "missing_data": info["missing_data"],
        },
    )
    session.add(note)
    session.commit()
    return note


# ── 신청서 초안 ─────────────────────────────────────────────────────────────

# fields[].source 어휘 — 프론트 fixture(getDraftFixture)가 쓰는 문자열과 맞춘다.
SRC_MYDATA_BIZ = "마이데이터 · 사업자등록증명"
SRC_CALC = "감탄 계산값"
SRC_CALC_ESTIMATE = "감탄 계산값(예상치)"
SRC_BILL = "전기요금고지서 파싱값"
SRC_UNCONFIRMED = "출처 확인 중(data-plan §6.3)"
SRC_OWNER_INPUT = "사장님 직접 입력"
SRC_PORTAL = "탄소중립포인트 포털에서 직접 발급"

# 서식에 있지만 감탄도 사장님도 채울 수 없어 **안내만 하는** 항목.
#
# 0032 이전에는 휴대전화번호·전자메일·인센티브 유형·계좌정보 등이 전부 여기 있었다. 그건
# 화면이 "초안 미리보기"뿐이라 사장님 입력을 받을 자리가 없었기 때문이고, 4단계 위저드의
# 3단계가 그 입력을 받게 되면서 전부 `APPLICANT_FIELDS`로 옮겨갔다.
#
# 비밀번호만 남는다 — 탄소중립포인트 포털 계정의 비밀번호이고 가입 처리 후 포털이 임시번호를
# 문자로 발급하는 흐름이라, 감탄이 값을 받아 보관해야 할 단계가 아예 없다. 타 기관
# 자격증명을 대신 들고 있지 않는다(0032 주석 참고).
REMAINING_FIELDS = [
    "비밀번호 — 감탄이 보관하지 않아요. 가입 신청 후 문자로 오는 임시번호로 포털에 접속해 직접 바꾸셔야 해요",
]

# 서식에 있지만 **상업시설 신청에는 해당 없어 화면에도 초안에도 넣지 않는** 항목.
#
# data-plan §6.3 지적: 문서명이 "사업자 참여 신청서(상업시설/공공기관/학교)"인데 가정용
# 항목이 그대로 남아 있다(상업시설·가구 공용 템플릿 재활용 추정). 상업시설 신청에는 사실상
# 무의미할 가능성이 높아 억지로 채우면 틀린 값이 된다.
#
# 0032 전에는 `fields`에 value=null로 넣어 "해당 없음"을 화면에 노출했는데, 채울 수도 없고
# 채울 필요도 없는 칸이 초안 미리보기를 길게 만들 뿐이라 아예 빼기로 했다(2026-08-25 결정).
# 상수는 남겨둔다 — 가구용 서식(application_type='household')을 다루게 되면 이 목록이
# "해당 없음"에서 "필수"로 바뀌는 축이 되기 때문이다.
BLANK_BY_POLICY = ("거주 면적(m²)", "세대원 수", "전입일자")


# ── 사장님 직접 입력 항목 (3단계 "없는 데이터 입력하기") ─────────────────────
#
# 서식에 있고, 감탄이 가진 데이터로는 채울 수 없고, 사장님이 답할 수 있는 항목의 명세다.
# **라벨·필수여부·선택지 어휘를 전부 백엔드가 정한다** — `fields`의 라벨을 백엔드가 정하는
# 것과 같은 원칙이고, 프론트는 이 배열을 순서대로 렌더한다. 서식이 개정되면 이 파일만 고친다.
#
# `input_type`이 UI 관심사인데 왜 백엔드에 있나: 선택지가 있는 항목(인센티브 유형)의 값
# 어휘가 DB CHECK 제약과 같아야 해서다. 프론트가 옵션 목록을 따로 들고 있으면 제약과
# 어긋나는 값을 보낼 수 있고, 그때 실패가 422로만 드러난다.
#
# 비밀번호는 여기 없다 — 받지 않는다(REMAINING_FIELDS 주석).

# 인센티브 유형 5종 — DB CHECK(ck_cnp_applications_incentive_type)와 같은 어휘여야 한다.
# 서식 원문 표기(①상품권 ②현금 ③현금기부 ④그린카드포인트 ⑤기타)를 라벨로 쓴다.
INCENTIVE_TYPES: tuple[tuple[str, str], ...] = (
    ("gift_certificate", "상품권"),
    ("cash", "현금"),
    ("cash_donation", "현금 기부"),
    ("green_card_point", "그린카드 포인트"),
    ("other", "기타"),
)

APPLICATION_KINDS: tuple[tuple[str, str], ...] = (
    ("new", "가입 신청"),
    ("change", "정보 변경 신청"),
)


@dataclass(frozen=True)
class ApplicantField:
    """3단계 입력 폼의 한 칸.

    `visible_when`은 "다른 칸의 값이 특정 값일 때만 보인다"는 조건이다 — 서식이 명시한
    조건부 항목을 그대로 옮긴 것이고(금융정보는 "②현금으로 선택한 분만", 기타 자유기재는
    ⑤기타 선택 시만), 조건이 안 맞으면 프론트가 칸 자체를 렌더하지 않는다. 해당 없는 칸을
    비활성으로 띄워두면 사장님이 "내가 뭘 안 채웠나" 헷갈린다.
    """
    key: str
    label: str
    input_type: str = "text"          # text | tel | email | date | select | radio
    required: bool = False
    group: str = ""
    placeholder: str | None = None
    help_text: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    visible_when: tuple[str, str] | None = None   # (다른 필드 key, 그 값)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "input_type": self.input_type,
            "required": self.required,
            "group": self.group,
            "placeholder": self.placeholder,
            "help_text": self.help_text,
            "options": [{"value": v, "label": lb} for v, lb in self.options],
            "visible_when": (
                None if self.visible_when is None
                else {"key": self.visible_when[0], "equals": self.visible_when[1]}
            ),
        }


# 그룹 라벨 — 3단계 폼의 섹션 제목. 서식 1페이지의 묶음을 따른다.
GROUP_SIGNUP = "신청 구분"
GROUP_BUSINESS = "사업자 정보"
GROUP_CONTACT = "연락처"
GROUP_ADDRESS = "사업장 주소"
GROUP_CUSTOMER_NO = "고지서 고객번호"
GROUP_INCENTIVE = "인센티브"

# 필수(*) 표시는 서식 원문의 별표를 그대로 따랐다 — 아이디, 신청인 휴대전화번호, 주소,
# 인센티브 유형, 고지서 고객번호(전기).
APPLICANT_FIELDS: tuple[ApplicantField, ...] = (
    ApplicantField(
        key="application_kind", label="신청 구분", input_type="radio", required=True,
        group=GROUP_SIGNUP, options=APPLICATION_KINDS,
    ),
    ApplicantField(
        key="portal_id", label="아이디(ID)", required=True, group=GROUP_SIGNUP,
        placeholder="영문·숫자 8~20자",
        help_text="탄소중립포인트 포털에서 쓸 아이디를 정해 적어주세요. 비밀번호는 가입 후 문자로 오는 임시번호로 직접 설정하시게 됩니다.",
    ),
    ApplicantField(
        key="corporate_registration_no", label="법인번호", group=GROUP_BUSINESS,
        placeholder="000000-0000000",
        help_text="법인사업자만 적으시면 돼요. 개인사업자는 비워 두세요.",
    ),
    ApplicantField(
        key="business_open_date", label="영업개시일자", input_type="date",
        group=GROUP_BUSINESS,
        help_text="사업자등록증명에 개업일자가 없어 직접 확인이 필요해요.",
    ),
    ApplicantField(
        key="applicant_phone", label="신청인 휴대전화번호", input_type="tel", required=True,
        group=GROUP_CONTACT, placeholder="'-' 없이 숫자만 입력",
        help_text="가입 확인과 인센티브 지급 안내를 문자로 받으실 번호예요.",
    ),
    ApplicantField(
        key="applicant_email", label="전자메일", input_type="email", group=GROUP_CONTACT,
        placeholder="example@email.com",
    ),
    ApplicantField(
        key="postal_code", label="우편번호", group=GROUP_ADDRESS, placeholder="00000",
        help_text="사업자등록증명에는 주소만 있고 우편번호가 없어요.",
    ),
    ApplicantField(
        key="road_address", label="도로명 주소", required=True, group=GROUP_ADDRESS,
        placeholder="대구광역시 중구 ○○로 00",
    ),
    ApplicantField(
        key="address_detail", label="상세 주소", group=GROUP_ADDRESS,
        placeholder="동·층·호",
    ),
    ApplicantField(
        key="electric_customer_number", label="전기", required=True, group=GROUP_CUSTOMER_NO,
        help_text="전기요금고지서에서 읽어 미리 채워 드려요. 값이 비어 있거나 다르면 고지서를 보고 고쳐주세요.",
    ),
    ApplicantField(key="water_customer_number", label="수도", group=GROUP_CUSTOMER_NO),
    ApplicantField(key="city_gas_customer_number", label="도시가스", group=GROUP_CUSTOMER_NO),
    ApplicantField(
        key="district_heating_customer_number", label="지역난방", group=GROUP_CUSTOMER_NO,
    ),
    ApplicantField(
        key="incentive_type", label="인센티브 유형", input_type="select", required=True,
        group=GROUP_INCENTIVE, options=INCENTIVE_TYPES,
        help_text="관할 지방자치단체가 시행하는 유형 중 하나만 고르실 수 있어요. 그린카드 미가입자는 그린카드 포인트를 고를 수 없습니다.",
    ),
    ApplicantField(
        key="incentive_type_other", label="기타 유형", group=GROUP_INCENTIVE,
        visible_when=("incentive_type", "other"),
    ),
    # 서식: "금융계좌는 인센티브 유형을 ②현금으로 선택하신 분에 한하여 기입하시면 됩니다."
    ApplicantField(
        key="bank_name", label="은행명", group=GROUP_INCENTIVE,
        visible_when=("incentive_type", "cash"),
    ),
    ApplicantField(
        key="account_number", label="계좌번호", group=GROUP_INCENTIVE,
        placeholder="'-' 없이 숫자만 입력", visible_when=("incentive_type", "cash"),
    ),
    ApplicantField(
        key="account_holder", label="예금주", group=GROUP_INCENTIVE,
        visible_when=("incentive_type", "cash"),
    ),
)

APPLICANT_FIELD_KEYS: frozenset[str] = frozenset(f.key for f in APPLICANT_FIELDS)

# 날짜로 저장하는 키 — 문자열("2026-08-25")로 들어오므로 저장 전에 date로 바꾼다.
_DATE_KEYS = frozenset({"business_open_date"})


def _latest_extracted(session: Session, company_id: int, document_type: str) -> dict:
    """해당 문서종류의 최신 `extracted_json`. 없으면 빈 dict."""
    row = session.execute(
        select(SourceDocument.extracted_json)
        .where(SourceDocument.company_id == company_id)
        .where(SourceDocument.document_type == document_type)
        .order_by(SourceDocument.id.desc())
    ).scalars().first()
    return row or {}


def _electric_customer_number(session: Session, company_id: int) -> str | None:
    """전기 고객번호 — 최신 전기고지서에서 파싱된 값(0029 이후 업로드분에만 있다)."""
    rows = session.execute(
        select(SourceDocument.extracted_json)
        .where(SourceDocument.company_id == company_id)
        .where(SourceDocument.document_type == "electric_bill")
        .order_by(SourceDocument.year.desc().nullslast(), SourceDocument.month.desc().nullslast(),
                  SourceDocument.id.desc())
    ).scalars().all()
    for extracted in rows:
        if extracted and extracted.get("customer_number"):
            return str(extracted["customer_number"])
    return None


def build_application_draft(
    session: Session,
    company_id: int,
    target_year: int,
    target_start_month: int = 1,
    *,
    strategy: BaselineStrategy = DEFAULT_BASELINE_STRATEGY,
    months: int = SETTLEMENT_MONTHS,
) -> dict:
    """신청서 초안 생성 — `POST /owner/{id}/carbon-point/applications` 응답 본문.

    반환 구조는 프론트 `CarbonPointDraft`와 동일하다(web/lib/carbon-point-fixture.ts):
    `application_id`, `status`, `fields[{label, value, source}]`, `remaining_fields`,
    `draft_document_url`. **라벨 문구까지 백엔드가 정한다** — 프론트는 배열을 그대로 렌더한다.

    LLM은 개입하지 않는다(원칙1) — 모든 수치는 `compute_reduction_rate()` 결과를 그대로
    문자열로 옮긴다. 채울 수 없는 값은 빈 문자열이 아니라 `None`이다(실패 가시성).

    data-plan §6.3이 "마이데이터 사업자등록증명 (기존)"으로 적어둔 항목 중 주소·연락처는
    실제로 그 페이로드에 없었다(2026-08-24 코드 확인). 둘의 성격이 달라 다르게 처리했다:

    - **주소**: 실제 사업자등록증명원에는 인쇄돼 나오는 항목인데 우리 mock 범위에서만
      빠져 있었다(회계 합성데이터 가이드의 `key_fields`가 "사업자번호, 기업명"으로 좁게
      잡힌 데서 비롯). `_synthetic_business_registration`에 `site_addr`를 추가해 채운다.
    - **휴대전화번호·전자메일**: 마이데이터 5종(국세청·중소벤처기업부·한전 발급 서류)
      어디에도 없다. 실서비스라면 은행 내부 고객정보에서 와야 하는데 그건 마이데이터가
      아니고 연동 가능성도 우리가 결정할 수 없다 — mock으로 지어내면 "이미 가진 데이터"인
      척하게 되므로 잔여 필드로 둔다.
    """
    info = evaluate_eligibility(
        session, company_id, target_year, target_start_month, strategy=strategy, months=months
    )
    # 제조업·미확인은 사용량도 계산하지 않는다 — evaluate_eligibility가 감축률을 아예
    # 계산하지 않는 것과 같은 기준을 지킨다. 감축률은 null인데 사용량만 채워 보내면
    # "계산은 했는데 결과만 감췄다"처럼 보여 §6.2의 원천 제외 취지와 어긋난다.
    if info["business_scale_hint"] == HINT_COMMERCIAL:
        result = compute_reduction_rate(
            monthly_electricity_usage(session, company_id),
            target_year, target_start_month, strategy=strategy, months=months,
        )
    else:
        result = ReductionResult(None, False, None, None, 0, strategy, False,
                                 reason="탄소중립포인트 에너지분야 신청 대상이 아니에요")
    biz = _latest_extracted(session, company_id, "business_registration")
    company_name = biz.get("company_name")
    representative = biz.get("representative")

    def _kwh(value: float | None) -> str | None:
        return None if value is None else f"전기 {value:,.0f} kWh"

    baseline_year, target = info["baseline_year"], info["target_year"]
    rate = info["reduction_rate_pct"]
    fields = [
        {"label": "상호(법인명)", "value": company_name, "source": SRC_MYDATA_BIZ},
        {"label": "대표자 성명", "value": representative, "source": SRC_MYDATA_BIZ},
        {"label": "사업자등록번호", "value": biz.get("business_registration_no"), "source": SRC_MYDATA_BIZ},
        {"label": "사업장 주소", "value": biz.get("site_addr"), "source": SRC_MYDATA_BIZ},
        # 연락처·전자메일은 마이데이터 5종 어디에도 없다 — 국세청·중소벤처기업부·한전이
        # 주는 서류라서다. 실서비스라면 은행이 이미 가진 고객정보에서 와야 하지만 그건
        # 마이데이터가 아니라 은행 내부 데이터이고(InstitutionBorrower에 연락처 컬럼이
        # 없는 이유), 그 연동 가능성은 우리가 결정할 수 없다. mock으로 지어내면 "이미
        # 가진 데이터"인 척하게 되므로 잔여 필드로 둔다(2026-08-24 결정).
        {"label": "신청인 휴대전화번호", "value": None, "source": SRC_OWNER_INPUT},
        {"label": "전자메일", "value": None, "source": SRC_OWNER_INPUT},
        {"label": "고지서 고객번호 — 전기", "value": _electric_customer_number(session, company_id),
         "source": SRC_BILL},
        # 수도 파싱이 이번 범위 밖이라 항상 null(develop-plan §2.5).
        {"label": "고지서 고객번호 — 수도", "value": None, "source": SRC_OWNER_INPUT},
        {"label": f"기준년도({baseline_year}) 사용량", "value": _kwh(result.baseline_usage_kwh),
         "source": SRC_CALC},
        {"label": f"감축년도({target}) 사용량", "value": _kwh(result.target_usage_kwh), "source": SRC_CALC},
        # "예상 감축률" 문구로 통일 — 확정치처럼 표기하지 않는다(develop-plan §2.3).
        {"label": "예상 감축률", "value": None if rate is None else f"{rate}%", "source": SRC_CALC_ESTIMATE},
    ]
    # BLANK_BY_POLICY(거주 면적·세대원 수·전입일자)는 `fields`에 넣지 않는다 — 상업시설
    # 신청에 해당 없는 칸을 "해당 없음"으로 띄워두면 초안 미리보기만 길어진다(2026-08-25).

    # draft 레코드는 자격을 충족했을 때만 남긴다 — 미달 기업의 신청서를 DB에 쌓지 않는다
    # (rate_approvals가 근거 없는 요청을 거부하는 것과 같은 결).
    #
    # 이미 있는 draft는 **재사용해서 갱신한다**(0032 이후). 위저드 3단계에서 받은 사장님
    # 입력이 같은 행에 붙어 있어서, POST마다 새 행을 만들면 화면을 다시 열 때마다 입력이
    # 사라진다. 반대로 status가 draft가 아닌 행(사장님이 제출했다고 표시한 행)은 절대
    # 건드리지 않고 새 draft를 만든다 — 제출 이력을 덮어쓰면 안 된다(원칙8과 같은 결).
    application = None
    if info["eligible"]:
        application = _reusable_draft(session, company_id, target)
        if application is None:
            application = CarbonNeutralPointApplication(
                company_id=company_id,
                application_type="business",
                baseline_year=baseline_year,
                target_year=target,
                status="draft",
            )
            session.add(application)
        application.baseline_year = baseline_year
        # 수도·가스는 파싱이 없어 **키를 아예 넣지 않는다** — 0을 넣으면 "안 썼다"와
        # "아직 모른다"가 뭉개진다(원칙7).
        application.baseline_usage_json = {"electricity_kwh": result.baseline_usage_kwh}
        application.target_usage_json = {"electricity_kwh": result.target_usage_kwh}
        application.reduction_rate_pct = rate
        application.eligible = True
        session.commit()

    # 3단계 입력 명세 + 지금까지 저장된 값. 전기 고객번호는 고지서 파싱값을 기본값으로
    # 깔아준다 — 사장님이 고칠 수 있게 폼에도 남기되(서식 필수 항목) 빈칸부터 시작하지 않는다.
    saved = applicant_saved_values(application)
    # setdefault를 쓰면 안 된다 — applicant_saved_values는 미입력 항목도 key를 None으로 채워
    # 반환하므로 key가 항상 존재한다. 값이 비었는지로 판단해야 한다.
    if not saved.get("electric_customer_number"):
        saved["electric_customer_number"] = _electric_customer_number(session, company_id)
    applicant_fields = [dict(spec.as_dict(), value=saved.get(spec.key)) for spec in APPLICANT_FIELDS]

    # 초안 미리보기(`fields`)에도 사장님이 채운 값이 반영돼야 한다 — 같은 화면의 2·4단계가
    # 서로 다른 값을 보여주면 안 된다. 라벨이 겹치는 항목만 덮어쓴다.
    _merge_applicant_into_fields(fields, saved)

    return {
        "application_id": application.id if application is not None else None,
        "status": "draft",
        "fields": fields,
        "applicant_fields": applicant_fields,
        "remaining_fields": list(REMAINING_FIELDS),
        # 초안 파일 생성은 이번 범위 밖(hwp 서식 렌더링 미착수) — 프론트가 이 값이 null이면
        # 다운로드 버튼을 비활성으로 둔다.
        "draft_document_url": None,
    }


def _reusable_draft(
    session: Session, company_id: int, target_year: int
) -> CarbonNeutralPointApplication | None:
    """같은 기업·같은 감축년도의 **미제출(draft)** 초안. 없으면 None.

    submitted/approved/rejected 행은 반환하지 않는다 — 이미 제출한 신청서를 다시 계산한
    값으로 덮어쓰면 사장님이 실제로 낸 내용과 기록이 어긋난다.
    """
    return session.execute(
        select(CarbonNeutralPointApplication)
        .where(CarbonNeutralPointApplication.company_id == company_id)
        .where(CarbonNeutralPointApplication.target_year == target_year)
        .where(CarbonNeutralPointApplication.status == "draft")
        .order_by(CarbonNeutralPointApplication.id.desc())
    ).scalars().first()


def applicant_saved_values(application: CarbonNeutralPointApplication | None) -> dict:
    """저장된 사장님 입력값 — `APPLICANT_FIELDS`의 key → 값. date는 ISO 문자열로 낸다."""
    if application is None:
        return {}
    values: dict[str, str | None] = {}
    for key in APPLICANT_FIELD_KEYS:
        raw = getattr(application, key, None)
        values[key] = raw.isoformat() if isinstance(raw, date) else raw
    return values


# 초안 미리보기의 라벨 ↔ 입력 key 대응. `fields`는 서식 순서대로 사람이 읽는 목록이고
# `applicant_fields`는 폼이라 라벨 문구가 다를 수 있어(예: "전기" vs "고지서 고객번호 — 전기")
# 자동 매칭에 의존하지 않고 명시적으로 적는다.
_FIELD_LABEL_TO_KEY = {
    "신청인 휴대전화번호": "applicant_phone",
    "전자메일": "applicant_email",
    "고지서 고객번호 — 전기": "electric_customer_number",
    "고지서 고객번호 — 수도": "water_customer_number",
}


def _merge_applicant_into_fields(fields: list[dict], saved: dict) -> None:
    """사장님이 채운 값을 초안 미리보기 항목에 덮어쓴다(제자리 수정)."""
    for field in fields:
        key = _FIELD_LABEL_TO_KEY.get(field["label"])
        if key is not None and saved.get(key):
            field["value"] = saved[key]


def save_applicant_input(
    session: Session, company_id: int, application_id: int, values: dict
) -> dict:
    """3단계 입력 저장 — `PATCH .../applications/{id}/applicant-input` 본문 처리.

    부분 저장을 허용한다(전달된 key만 갱신) — 사장님이 폼을 다 채우기 전에 나가도 지금까지
    쓴 게 남아야 한다. 그래서 필수 항목 검사를 여기서 하지 않는다. "필수인데 비었다"는
    응답의 `missing_required`로 알려주고, 그걸 근거로 화면이 다음 단계 버튼을 막는다.

    `APPLICANT_FIELDS`에 없는 key는 조용히 무시하지 않고 호출부(라우터)가 422로 거른다 —
    오타 난 필드명이 조용히 버려지면 "저장했는데 값이 안 남는" 증상으로만 드러난다.

    status가 draft가 아닌 행은 갱신하지 않는다(제출 이력 보호) — 라우터가 409로 막는다.
    """
    row = session.get(CarbonNeutralPointApplication, application_id)
    if row is None or row.company_id != company_id:
        raise LookupError("application not found")
    if row.status != "draft":
        raise PermissionError("이미 제출한 신청서는 수정할 수 없어요")

    for key, raw in values.items():
        # 빈 문자열은 "지웠다"는 뜻이라 null로 저장한다 — ""와 null이 섞이면 미입력 판정이
        # 두 갈래가 된다.
        value = None if raw is None or (isinstance(raw, str) and raw.strip() == "") else raw
        if key in _DATE_KEYS and isinstance(value, str):
            value = date.fromisoformat(value)
        setattr(row, key, value)

    row.applicant_input_updated_at = datetime.now(timezone.utc)
    session.commit()

    saved = applicant_saved_values(row)
    return {
        "application_id": row.id,
        "values": saved,
        "missing_required": missing_required_keys(saved),
    }


def missing_required_keys(saved: dict) -> list[str]:
    """필수인데 아직 안 채워진 입력 key — 화면의 "다음" 버튼 활성 조건.

    `visible_when` 조건이 안 맞아 화면에 안 나오는 칸은 검사하지 않는다 — 인센티브를
    상품권으로 골랐다면 계좌번호는 애초에 물어보지 않았으므로 미입력이 정상이다.
    """
    missing = []
    for spec in APPLICANT_FIELDS:
        if not spec.required:
            continue
        if spec.visible_when is not None:
            dep_key, dep_value = spec.visible_when
            if saved.get(dep_key) != dep_value:
                continue
        if not saved.get(spec.key):
            missing.append(spec.key)
    return missing
