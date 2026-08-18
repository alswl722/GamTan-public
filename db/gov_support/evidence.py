"""LLM 근거 문장 생성 — 매칭된 지원사업 후보별로 "왜 이 회사에 맞는지" 1~2문장.
docs/gov-support-matching-plan.md §4·§7 정본.

매칭 목록 자체(어떤 사업이 후보인지)는 db/gov_support/matching.py의 결정론적
코사인 유사도가 이미 확정한 뒤라, 여기서 LLM이 실패하거나 이상한 답을 해도
노출되는 사업 목록 자체는 안 바뀐다 — evidence 필드만 null이 되고 프론트가
"설명 생성 실패"로 표기한다(§7 실패 가시성, 대체 문구로 안 가림). 마감일·
소관기관 등 사실 필드는 API 원문 그대로 노출하고 LLM이 재작성하지 않는다.

기업 프로필·지원사업 원문이 안 바뀌면 근거 문장도 안 바뀌어야 하는데
(결정론적 매칭에 대한 설명이라 매번 다시 물을 이유가 없음), 캐싱 없이는
새로고침할 때마다 5건을 다시 LLM에 물어 매번 8~9초씩 걸렸다(2026-08-18
실측). 전표 분류(api/agent/llm_classify.py)가 이미 쓰는 llm_cache 테이블·
"텍스트 해시→응답" 패턴을 그대로 재사용한다 — 새 캐시 테이블을 안 만들고
기존 정식 기능(CLAUDE.md §6 "llm_cache는 비용·재현성 정식 기능")에 얹는다.
"""
import concurrent.futures
import hashlib
import os
from datetime import datetime, timezone

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import LlmCache

MODEL = "gemini-3.5-flash"


def _hash(company_profile_text: str, program_name: str, program_raw_text: str) -> str:
    combined = f"{company_profile_text}|{program_name}|{program_raw_text}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _cache_get(session: Session, text_hash: str) -> str | None:
    cached = session.execute(select(LlmCache).where(LlmCache.text_hash == text_hash)).scalar_one_or_none()
    if cached is None:
        return None
    cached.hit_count = (cached.hit_count or 0) + 1
    cached.last_used_at = datetime.now(timezone.utc)
    session.commit()
    return cached.llm_response.get("evidence")


def _cache_get_many(session: Session, text_hashes: list[str]) -> dict[str, str]:
    """여러 해시를 한 번의 쿼리로 조회 — 후보 개수만큼 순차 왕복하면 각 왕복의
    네트워크 지연(Supabase까지)이 그대로 쌓인다(2026-08-18 실측: 5건 순차
    조회로 캐시 적중 상황에서도 7초 이상 걸림). hit_count 갱신도 한 번에 커밋."""
    if not text_hashes:
        return {}
    rows = session.execute(select(LlmCache).where(LlmCache.text_hash.in_(text_hashes))).scalars().all()
    now = datetime.now(timezone.utc)
    result = {}
    for row in rows:
        row.hit_count = (row.hit_count or 0) + 1
        row.last_used_at = now
        result[row.text_hash] = row.llm_response.get("evidence")
    if rows:
        session.commit()
    return result


def _cache_put(session: Session, text_hash: str, program_name: str, evidence: str) -> None:
    session.add(LlmCache(text_hash=text_hash, item_description=program_name, llm_response={"evidence": evidence}))
    try:
        session.commit()
    except IntegrityError:
        # 동일 text_hash가 이미 존재(동시 요청 등) — 기존 캐시를 신뢰하고 이번 건은 버림
        session.rollback()


def generate_evidence(company_profile_text: str, program_name: str, program_raw_text: str) -> str | None:
    """캐시를 거치지 않는 저수준 호출. 실패 시 None — 호출부가 "설명 생성 실패"로
    표기한다(대체 문구로 안 가림). 캐싱까지 원하면 generate_evidence_batch를 쓴다."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    prompt = (
        f"기업 프로필: {company_profile_text}\n"
        f"지원사업명: {program_name}\n"
        f"지원사업 개요: {program_raw_text[:500]}\n\n"
        "위 기업이 왜 이 지원사업에 적합한지 1~2문장으로 짧게 설명해줘. "
        "사업 내용에 실제로 있는 근거만 써야 하고, 없는 조건을 지어내면 안 돼.\n"
        "강조 표시(**단어**)는 이 사업이 실제로 제공하는 지원 내용(예: 융자·"
        "보조금·컨설팅·설비 지원 등 구체적으로 무엇을 주는지)에만 써줘. "
        "기업의 지역·업종·규모 같은 매칭 조건이나 그 외 문구는 강조하지 마."
    )
    try:
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=10_000))
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="너는 정부 지원사업과 기업 프로필을 비교해 적합성을 짧게 설명하는 도우미다.",
            ),
        )
        text = (resp.text or "").strip()
        return text or None
    except Exception:
        return None


def generate_evidence_batch(
    session: Session, company_profile_text: str, items: list[tuple[int, str, str]]
) -> dict[int, str | None]:
    """후보 여러 건의 근거 문장을 캐시 우선으로 채운다. items는
    (program_id, program_name, program_raw_text) 튜플 목록.

    캐시 조회·기록은 세션을 순차로만 쓴다(SQLAlchemy Session은 스레드 세이프가
    아님) — 캐시 미스만 골라서 ThreadPoolExecutor로 병렬 LLM 호출하고, 그
    구간에서는 session을 안 건드린다. 반환은 program_id → evidence(None이면
    실패, 호출부가 "설명 생성 실패"로 표기)."""
    hashed = [
        (program_id, program_name, raw_text, _hash(company_profile_text, program_name, raw_text))
        for program_id, program_name, raw_text in items
    ]
    cache_hits = _cache_get_many(session, [h for *_rest, h in hashed])

    results: dict[int, str | None] = {}
    misses: list[tuple[int, str, str, str]] = []  # (program_id, program_name, raw_text, hash)
    for program_id, program_name, raw_text, text_hash in hashed:
        if text_hash in cache_hits:
            results[program_id] = cache_hits[text_hash]
        else:
            misses.append((program_id, program_name, raw_text, text_hash))

    if not misses:
        return results

    def _call(item: tuple[int, str, str, str]):
        program_id, program_name, raw_text, text_hash = item
        return program_id, program_name, text_hash, generate_evidence(company_profile_text, program_name, raw_text)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(misses)) as pool:
        called = list(pool.map(_call, misses))

    for program_id, program_name, text_hash, evidence in called:
        results[program_id] = evidence
        if evidence is not None:
            _cache_put(session, text_hash, program_name, evidence)

    return results
