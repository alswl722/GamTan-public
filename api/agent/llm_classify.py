"""도구② 후반부 — LLM(Gemini) 분류. 룰 매칭이 확정 못한(애매·미매칭) 건만 호출.

CLAUDE.md §5-2 고정 스키마를 그대로 따른다: LLM은 분류·추출·근거·확신도만
반환하고 물량 환산·탄소량 계산은 절대 하지 않는다(도구③이 결정론적으로 수행).
동일 품목명 → 동일 응답을 보장하는 llm_cache로 래핑해 비용·재현성을 확보한다
(CLAUDE.md §5-4, 정식 기능 — 데모 임시방편 아님).
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import LlmCache

MODEL = "gemini-3.5-flash"

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "raw_text": {"type": "STRING"},
        "scope": {"type": "INTEGER", "nullable": True, "description": "1(이동/고정연소) | 2(간접배출) | null(탄소 산정 제외)"},
        "category": {"type": "STRING", "description": "이동연소 | 고정연소 | 간접배출 | 일반비용 | 기타"},
        "fuel_type": {"type": "STRING", "description": "경유 | 휘발유 | 도시가스 | LPG | 전기 | 없음 | 연료종류 불명 등"},
        "amount_krw": {"type": "INTEGER"},
        "mixed_item": {"type": "BOOLEAN"},
        "confidence": {"type": "NUMBER", "description": "0.0~1.0"},
        "evidence": {"type": "STRING", "description": "판단 근거 한 문장"},
    },
    "required": ["raw_text", "category", "fuel_type", "mixed_item", "confidence", "evidence"],
}

_SYSTEM_PROMPT = """당신은 한국 중소기업의 세금계산서·전기 고지서 품목명을 읽고 \
온실가스 Scope 1/2 여부를 분류하는 회계 보조 AI다.

분류 기준:
- Scope 1(직접배출) - 이동연소: 차량·지게차 등 이동장비의 경유·휘발유 사용
- Scope 1(직접배출) - 고정연소: 보일러·발전기 등 고정설비의 도시가스·LPG·등유 사용
- Scope 2(간접배출): 한전 전기요금 등 구매 전력 사용
- 탄소 산정 제외: 사무용품·식대·수리비·원재료 매입 등 연료 사용이 아닌 일반비용 → scope는 null

예시: "지게차 경유 외 1종" → scope=1, category="이동연소", fuel_type="경유", \
evidence="품목명에 '지게차'와 '경유'가 명시되어 직접배출(이동연소)로 분류"

"외 1종"처럼 혼합 품목이면 mixed_item=true로 표시하되, 주 품목 하나로만 분류한다 \
(금액 분할은 하지 않음 — 그건 이 시스템이 코드로 처리한다).

당신은 분류와 근거 제시만 한다. 물량 환산이나 탄소 배출량 계산은 하지 않는다 \
(그 계산은 별도의 결정론적 코드가 수행한다). 확신이 낮으면 confidence를 낮게 \
보고하라 — 낮은 confidence는 사람 검토로 이관되므로 솔직하게 보고하는 것이 중요하다."""


def _hash(item_description: str) -> str:
    return hashlib.sha256(item_description.encode("utf-8")).hexdigest()


def _cache_get(session: Session, text_hash: str) -> dict | None:
    cached = session.execute(
        select(LlmCache).where(LlmCache.text_hash == text_hash)
    ).scalar_one_or_none()
    if cached is None:
        return None
    cached.hit_count = (cached.hit_count or 0) + 1
    cached.last_used_at = datetime.now(timezone.utc)
    session.commit()
    return cached.llm_response


def _cache_put(session: Session, text_hash: str, item_description: str, response: dict) -> None:
    from sqlalchemy.exc import IntegrityError

    session.add(
        LlmCache(
            text_hash=text_hash,
            item_description=item_description,
            llm_response=response,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # 동일 text_hash 가 이미 존재(동시 실행 등) — 기존 캐시를 신뢰하고 이번 건은 버림
        session.rollback()


# 공개 별칭 — tools.py 가 병렬 분류에서 캐시 조회/저장을 직접 오케스트레이션할 때 사용.
hash_item = _hash
cache_get = _cache_get
cache_put = _cache_put


def _build_prompt(item_description: str, amount_krw: int, rule_hint: dict | None) -> str:
    parts = [
        f'품목명: "{item_description}"',
        f"공급가액: {amount_krw:,}원",
    ]
    if rule_hint:
        parts.append(
            "참고(룰 엔진 1차 판단, 애매하다고 표시됨): "
            f"scope={rule_hint.get('scope')}, category={rule_hint.get('category')}, "
            f"fuel_type={rule_hint.get('fuel_type')}, 근거=\"{rule_hint.get('reasoning')}\". "
            "이 힌트를 참고하되, 품목명 자체에서 더 정확히 판단할 수 있으면 다르게 답해도 된다."
        )
    return "\n".join(parts)


def _call_gemini(prompt: str) -> dict:
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=10_000),  # ms — 행 걸림은 빠르게 실패로
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )
    return json.loads(resp.text)


def _fallback_result(item_description: str, reason: str) -> dict:
    """JSON 파싱/호출 실패 시 — 낮은 confidence로 HITL 이관되도록 함.

    실패 가시성 원칙: 실패를 그럴듯한 사유로 포장하지 않고 사실만 적는다
    (원문 API 오류 JSON 은 노출하지 않되, 실패 종류는 정확히).
    """
    r = (reason or "").lower()
    if "resource_exhausted" in r or "429" in r or "quota" in r:
        why = "LLM 호출 실패(요청 한도 초과)"
    elif "json" in r:
        why = "LLM 응답 형식 오류"
    elif "timeout" in r or "deadline" in r:
        why = "LLM 호출 실패(시간 초과)"
    else:
        why = "LLM 호출 실패"
    return {
        "raw_text": item_description,
        "scope": None,
        "category": "불명",
        "fuel_type": "불명",
        "amount_krw": None,
        "mixed_item": False,
        "confidence": 0.0,
        "evidence": f"{why} — 미분류, 사람 검토 필요",
    }


def classify_with_llm(
    session: Session,
    item_description: str,
    amount_krw: int,
    rule_hint: dict | None = None,
) -> dict:
    """룰이 확정 못한 품목명을 Gemini로 분류. 동일 텍스트는 llm_cache로 재사용."""
    text_hash = _hash(item_description)
    cached = _cache_get(session, text_hash)
    if cached is not None:
        return cached

    result = classify_with_llm_nocache(item_description, amount_krw, rule_hint)
    if result.get("confidence", 0) > 0 or result.get("scope") is not None:
        _cache_put(session, text_hash, item_description, result)
    return result


def classify_with_llm_nocache(
    item_description: str,
    amount_krw: int,
    rule_hint: dict | None = None,
) -> dict:
    """세션(DB) 없이 Gemini만 호출 — 캐시 미스 건을 스레드풀에서 병렬 호출할 때 사용.

    실패 시 _fallback_result 를 반환할 뿐 캐시엔 쓰지 않는다(호출부가 판단해 기록).
    """
    prompt = _build_prompt(item_description, amount_krw, rule_hint)

    last_error = "unknown"
    for _attempt in range(2):  # 최초 시도 + 1회 재시도 (CLAUDE.md §5-2)
        try:
            return _call_gemini(prompt)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"JSON 파싱 실패: {e}"
            continue
        except Exception as e:  # noqa: BLE001 — API 오류(레이트리밋 등)도 동일하게 폴백
            last_error = f"API 호출 실패: {e}"
            continue

    return _fallback_result(item_description, last_error)
