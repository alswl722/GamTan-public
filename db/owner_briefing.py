"""사장님 앱 "월간 AI 브리핑" — 이번 달 vs 지난달 연료별 활동을 편지 문단으로
조립. GET /owner/{company_id}/briefing (api/routers/owner.py)이 DB에서
가져온 값을 여기 넘겨 문단·통계를 만든다.

CLAUDE.md 원칙1(LLM 산수 금지)과 같은 결 — 증감률(compute_fuel_deltas)은
항상 결정론적 계산이고, LLM은 그 계산된 숫자를 문장으로 "표현"하는 역할만
한다(db/gov_support/evidence.py와 같은 패턴 — 결정론적으로 이미 확정된
사실을 자연스러운 문장으로 설명). LLM이 새로운 숫자를 만들어내는 경로는
없다 — 프롬프트가 이미 계산된 값만 문장에 쓰라고 명시하고, 응답에 값
필드 자체가 없다(evidence 생성과 동일한 방어 논리, CLAUDE.md 원칙1).

LLM 호출이 실패하면(키 없음·API 오류·타임아웃) build_briefing_paragraphs()
템플릿으로 폴백한다 — 편지가 아예 안 뜨는 것보다는 낫지만, 실패를
감추지는 않는다(응답의 generated_by로 "llm"|"template" 구분, CLAUDE.md
§6 실패 가시성).
"""
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import LlmCache

MODEL = "gemini-3.5-flash"


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
    "경유": "지게차를 더 쓰셨나요",
    "휘발유": "차량 운행이 늘었나요",
    "도시가스": "난방을 더 쓰셨나요",
    "LPG": "설비 가동이 늘었나요",
    "전기": "설비를 더 돌리셨나요",
}


def _clause_for_fuel(stat: dict) -> str:
    """한 연료의 증감을 문단 안의 한 '절'로 표현(접속사 없이) — 여러 절을
    build_briefing_paragraphs()가 쉼표·"그리고"로 자연스럽게 엮는다."""
    fuel = stat["fuel_type"]
    direction = stat["direction"]

    if direction == "new":
        return f"이번 달엔 {fuel} 사용이 새로 확인됐어요"
    if direction == "flat":
        return f"{fuel} 사용량은 지난달과 비슷하게 유지됐어요"

    pct = abs(stat["delta_pct"])
    if direction == "up":
        hint = _FUEL_HINT.get(fuel)
        hint_part = f", {hint}" if hint else ""
        return f"{fuel} 사용량이 지난달보다 {pct:.0f}% 늘었어요{hint_part}"
    return f"{fuel} 사용량은 지난달보다 {pct:.0f}% 줄었어요"


def _join_clauses(clauses: list[str]) -> str:
    """절 목록을 자연스러운 한국어 나열로 연결. 2개는 "A, 그리고 B", 3개
    이상은 "A, B, 그리고 C"처럼 마지막 절 앞에만 "그리고"를 붙인다 —
    "그리고"가 매 절마다 반복되지 않게."""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]}. 그리고 {clauses[1]}"
    return ". ".join(clauses[:-1]) + f". 그리고 {clauses[-1]}"


def build_briefing_paragraphs(fuel_deltas: list[dict], *, has_previous_month: bool) -> list[str]:
    """연료별 증감 통계 → 편지 문단 리스트.

    직전월 데이터 자체가 없는 첫 달은 비교 문장 대신 시작 안내로 대체한다 —
    없는 지난달과 억지로 비교해 %를 만들지 않는다(원칙: 없는 데이터를 있는
    것처럼 보여주지 않음, CLAUDE.md §6 실패 가시성).

    연료가 여럿이면 "반가운 소식이에요 — A는 줄었어요. 반가운 소식이에요 —
    B도 줄었어요."처럼 도입구가 반복되지 않도록, 절(clause)을 하나의 문단으로
    자연스럽게 엮는다(_join_clauses).
    """
    if not has_previous_month:
        return [
            "이번 달부터 우디가 탄소 이야기를 들려드릴게요.",
            "아직은 비교할 지난달 기록이 없어서, 이번 달 숫자부터 차근차근 보여드릴게요.",
            "다음 달부터는 지난달과 비교해서 더 재미있는 이야기를 전해드릴 수 있을 거예요.",
        ]

    if not fuel_deltas:
        return ["이번 달엔 새로 확인된 전표가 없어요. 데이터가 들어오면 바로 알려드릴게요."]

    clauses = [_clause_for_fuel(s) for s in fuel_deltas]
    has_down = any(s["direction"] == "down" for s in fuel_deltas)
    has_up = any(s["direction"] == "up" for s in fuel_deltas)

    lead_in = "반가운 소식이에요 — " if (has_down and not has_up) else "이번 달 소식을 전해드릴게요. "
    body = lead_in + _join_clauses(clauses) + "."
    paragraphs = [body]

    if has_down:
        paragraphs.append("이대로면 목표 달성에 한 걸음 더 가까워질 것 같아요.")

    paragraphs.append("아래에서 이번 달 숫자들을 자세히 볼 수 있어요. 궁금한 게 있으면 언제든 눌러서 확인해 보세요.")
    return paragraphs


_SYSTEM_PROMPT = """너는 "우디"라는 나무 캐릭터로, 대구·경북 소부장 중소기업 \
사장님에게 매달 탄소 배출 데이터를 편지 형식으로 전해주는 도우미다.

너에게는 이미 계산이 끝난 연료별 증감 통계가 주어진다. 너의 역할은 그 통계를 \
읽고 사람이 쓴 것처럼 자연스럽고 따뜻한 편지 문단으로 표현하는 것뿐이다.

분량 규칙(반드시 지킬 것):
- 전체 2~3문단, 총 4~6문장을 넘기지 않는다. 사장님은 바쁘다 — 편지가 길면 안 읽는다.
- 첫 문단(서론)은 인사 없이, 그날 가장 눈에 띄는 연료 소식으로 바로 시작하는 \
한 문장이면 충분하다. "안녕하세요, 사장님. 지난 한 달 동안 고생 많으셨어요" \
같은 인사말은 쓰지 않는다 — 매달 반복되면 지루하다.
- 본론은 연료별 숫자를 담되, 연료마다 별도 문단을 쓰지 않고 한 문단 안에서 \
자연스럽게 이어 말한다.
- 마지막 문단(결론)은 "아래에서 자세히 볼 수 있다"는 한 문장으로 짧게 끝낸다. \
"이렇게 하나씩 기록을 쌓아가다 보면..." 같은 여운을 남기는 마무리 문장을 \
따로 덧붙이지 않는다.

절대 규칙:
- 주어진 숫자(this_month_co2e, last_month_co2e, delta_pct)를 그대로만 인용한다. \
새로운 숫자를 계산하거나 어림잡아 만들어내지 않는다.
- 주어지지 않은 연료·사실을 지어내지 않는다.
- 존댓말(해요체)을 쓴다. 과장하거나 불안을 조성하지 않는다.
- 사용량이 늘었으면(direction=up) 왜 늘었을지 가볍게 되물어도 좋다(예: 지게차를 \
더 쓰셨는지, 난방을 더 썼는지 등 연료 특성에 맞게) — 단, 여러 연료가 늘었어도 \
되묻는 질문은 편지 전체에서 최대 1번만 쓴다. 줄었으면(direction=down) 짧게 \
칭찬하되, 연료마다 매번 칭찬하지 않는다.

지난달 데이터가 아예 없는 첫 달(has_previous_month=false)이면 비교하지 말고 \
"이제부터 함께 기록을 시작한다"는 취지로 짧게 안내한다(이때도 2문장을 넘기지 \
않는다)."""

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "paragraphs": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "편지 문단 목록. 각 항목이 한 문단.",
        },
    },
    "required": ["paragraphs"],
}


def _build_llm_input(fuel_deltas: list[dict], *, has_previous_month: bool) -> str:
    payload = {
        "has_previous_month": has_previous_month,
        "fuel_deltas": fuel_deltas,
    }
    return (
        "아래는 이미 계산된 이번 달 연료별 탄소 배출 통계다. 이 값만 참고해서 "
        "편지 문단을 써줘 (새 숫자를 만들지 말 것):\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def generate_briefing_paragraphs_llm(fuel_deltas: list[dict], *, has_previous_month: bool) -> list[str] | None:
    """LLM으로 편지 문단 생성. 실패 시 None — 호출부가 build_briefing_paragraphs()
    템플릿으로 폴백한다(db/gov_support/evidence.py와 동일한 실패 처리 방식).

    fuel_deltas는 compute_fuel_deltas()의 출력을 그대로 받는다 — 이 함수는
    증감 계산을 하지 않고 이미 계산된 값만 문장으로 표현한다.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    if not has_previous_month or not fuel_deltas:
        # 첫 달·데이터 없음은 LLM에 물을 내용 자체가 없다 — 템플릿이 이미
        # 정확한 안내 문구를 갖고 있으므로 여기서는 굳이 호출하지 않는다.
        return None

    prompt = _build_llm_input(fuel_deltas, has_previous_month=has_previous_month)
    try:
        # 분량 규칙이 담긴 시스템 프롬프트가 길어 응답 생성이 10초 안팎으로
        # 걸릴 때가 있다(실측 9.7초) — 10초 타임아웃은 경계선에서 실패하므로
        # 여유를 둔다. 어차피 이 경로는 llm_cache로 결과가 재사용되니(매 요청
        # 마다 다시 기다리지 않음) 느긋하게 기다려도 손해가 없다.
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=25_000))
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
            ),
        )
        data = json.loads(resp.text)
        paragraphs = data.get("paragraphs")
        if not paragraphs or not isinstance(paragraphs, list):
            return None
        return [str(p) for p in paragraphs]
    except Exception:
        return None


def _briefing_hash(fuel_deltas: list[dict]) -> str:
    """같은 달의 같은 증감 통계면 같은 편지를 재사용 — 새로고침마다 다시 물어
    비용·지연을 만들지 않는다(db/gov_support/evidence.py와 동일 이유,
    llm_cache 테이블 재사용 — CLAUDE.md "llm_cache는 비용·재현성 정식 기능")."""
    combined = json.dumps(fuel_deltas, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"owner_briefing|{combined}".encode("utf-8")).hexdigest()


def get_briefing_paragraphs(
    session: Session, fuel_deltas: list[dict], *, has_previous_month: bool
) -> tuple[list[str], str]:
    """편지 문단을 캐시→LLM→템플릿 순으로 확보. 반환: (paragraphs, generated_by)
    generated_by는 "llm"|"llm_cache"|"template" — 프론트/운영이 실제로 AI가
    썼는지 템플릿 폴백인지 구분할 수 있게(실패를 감추지 않음, CLAUDE.md §6).
    """
    if not has_previous_month or not fuel_deltas:
        return build_briefing_paragraphs(fuel_deltas, has_previous_month=has_previous_month), "template"

    text_hash = _briefing_hash(fuel_deltas)
    cached = session.execute(select(LlmCache).where(LlmCache.text_hash == text_hash)).scalar_one_or_none()
    if cached is not None:
        cached.hit_count = (cached.hit_count or 0) + 1
        cached.last_used_at = datetime.now(timezone.utc)
        session.commit()
        return cached.llm_response["paragraphs"], "llm_cache"

    llm_paragraphs = generate_briefing_paragraphs_llm(fuel_deltas, has_previous_month=has_previous_month)
    if llm_paragraphs is None:
        return build_briefing_paragraphs(fuel_deltas, has_previous_month=has_previous_month), "template"

    session.add(LlmCache(text_hash=text_hash, item_description="owner_briefing", llm_response={"paragraphs": llm_paragraphs}))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()  # 동시 요청 등으로 이미 캐시됨 — 이번 응답은 그대로 반환
    return llm_paragraphs, "llm"
