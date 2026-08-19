"""사장님 앱 "월간 AI 브리핑" — 이번 달 vs 지난달 연료별 활동을 편지 문단으로
조립하는 순수 함수. GET /owner/{company_id}/briefing (api/routers/owner.py)이
DB에서 가져온 값을 여기 넘겨 문단·통계를 만든다.

CLAUDE.md 원칙1(LLM 산수 금지)과 같은 결 — 증감률은 결정론적 계산이고,
문장은 미리 정한 템플릿에 그 값을 끼워 넣을 뿐이다. LLM은 쓰지 않는다.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FuelMonthStat:
    fuel_type: str
    this_month_co2e: float  # tCO2e
    last_month_co2e: float | None  # tCO2e, None이면 지난달 데이터 없음


def _delta_pct(this_month: float, last_month: float) -> float:
    """지난달 대비 증감률(%). 지난달이 0이면 계산 불가(무한대) — 호출부에서
    last_month > 0 확인 후에만 부른다."""
    return (this_month - last_month) / last_month * 100


def compute_fuel_deltas(stats: list[FuelMonthStat]) -> list[dict]:
    """연료별 증감 통계로 변환. 반환 순서는 입력 순서 그대로 유지(정렬은
    호출부 책임 — 여기서는 계산만).

    반환: [{fuel_type, this_month_co2e, last_month_co2e, delta_pct, direction}]
    direction: "up" | "down" | "flat" | "new"(지난달 데이터 없음)
    """
    results = []
    for s in stats:
        if s.last_month_co2e is None or s.last_month_co2e == 0:
            results.append({
                "fuel_type": s.fuel_type,
                "this_month_co2e": round(s.this_month_co2e, 2),
                "last_month_co2e": s.last_month_co2e,
                "delta_pct": None,
                "direction": "new",
            })
            continue
        pct = _delta_pct(s.this_month_co2e, s.last_month_co2e)
        if abs(pct) < 1.0:
            direction = "flat"
        elif pct > 0:
            direction = "up"
        else:
            direction = "down"
        results.append({
            "fuel_type": s.fuel_type,
            "this_month_co2e": round(s.this_month_co2e, 2),
            "last_month_co2e": round(s.last_month_co2e, 2),
            "delta_pct": round(pct, 1),
            "direction": direction,
        })
    return results


# 연료별로 "무엇을 더 썼는지" 되묻는 톤을 다르게 — 편지가 사람이 쓴 것처럼
# 읽히게 하는 최소한의 분기. 새 연료가 추가돼도 기본 문구로 자연 처리된다.
_FUEL_HINT = {
    "경유": "지게차를 더 쓰셨나요?",
    "휘발유": "차량 운행이 늘었나요?",
    "도시가스": "난방을 더 쓰셨나요?",
    "LPG": "설비 가동이 늘었나요?",
    "전기": "설비를 더 돌리셨나요?",
}


def _paragraph_for_fuel(stat: dict) -> str:
    fuel = stat["fuel_type"]
    direction = stat["direction"]

    if direction == "new":
        return f"이번 달 {fuel} 사용이 처음 확인됐어요."
    if direction == "flat":
        return f"{fuel} 사용량은 지난달과 비슷하게 유지됐어요."

    pct = abs(stat["delta_pct"])
    if direction == "up":
        hint = _FUEL_HINT.get(fuel, "")
        hint_part = f" {hint}" if hint else ""
        return f"이번 달 {fuel} 사용량이 지난달보다 {pct:.0f}% 늘었어요.{hint_part}"
    return f"반가운 소식이에요 — {fuel} 사용량은 지난달보다 {pct:.0f}% 줄었어요."


def build_briefing_paragraphs(fuel_deltas: list[dict], *, has_previous_month: bool) -> list[str]:
    """연료별 증감 통계 → 편지 문단 리스트.

    직전월 데이터 자체가 없는 첫 달은 비교 문장 대신 시작 안내로 대체한다 —
    없는 지난달과 억지로 비교해 %를 만들지 않는다(원칙: 없는 데이터를 있는
    것처럼 보여주지 않음, CLAUDE.md §6 실패 가시성).
    """
    if not has_previous_month:
        return [
            "이번 달부터 우디가 탄소 이야기를 들려드릴게요.",
            "아직은 비교할 지난달 기록이 없어서, 이번 달 숫자부터 차근차근 보여드릴게요.",
            "다음 달부터는 지난달과 비교해서 더 재미있는 이야기를 전해드릴 수 있을 거예요.",
        ]

    if not fuel_deltas:
        return ["이번 달엔 새로 확인된 전표가 없어요. 데이터가 들어오면 바로 알려드릴게요."]

    paragraphs = [_paragraph_for_fuel(s) for s in fuel_deltas]

    closing_candidates = [s for s in fuel_deltas if s["direction"] == "down"]
    if closing_candidates:
        paragraphs.append("이대로면 목표 달성에 한 걸음 더 가까워질 것 같아요.")

    paragraphs.append("아래에서 이번 달 숫자들을 자세히 볼 수 있어요. 궁금한 게 있으면 언제든 눌러서 확인해 보세요.")
    return paragraphs
