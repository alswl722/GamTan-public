"""근거 문장 생성·캐싱(db/gov_support/evidence.py) 골든 케이스.
docs/gov-support-matching-plan.md §4·§7 정본.

핵심 검증축:
  - 같은 (기업 프로필, 사업명, 사업 원문) 조합이면 캐시를 재사용하고 LLM을
    다시 안 부른다(2026-08-18 사용자 피드백 — 새로고침마다 매번 재호출되던
    문제 수정, 전표 분류가 이미 쓰는 llm_cache 패턴 재사용)
  - 캐시 미스만 실제로 LLM을 호출한다
  - 성공한 결과만 캐시에 쓴다(실패까지 캐싱하면 일시적 오류가 영구화됨)
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.gov_support import evidence
from db.gov_support.evidence import _cache_get, _cache_put, _hash, generate_evidence_batch
from db.models import Base, LlmCache


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_hash_is_stable_for_same_inputs():
    a = _hash("프로필", "사업명", "원문")
    b = _hash("프로필", "사업명", "원문")
    assert a == b


def test_hash_differs_when_any_input_changes():
    base = _hash("프로필", "사업명", "원문")
    assert _hash("다른 프로필", "사업명", "원문") != base
    assert _hash("프로필", "다른 사업명", "원문") != base
    assert _hash("프로필", "사업명", "다른 원문") != base


def test_cache_put_then_get_roundtrip(session):
    h = _hash("프로필", "사업명", "원문")
    _cache_put(session, h, "사업명", "이 기업은 적합합니다")
    assert _cache_get(session, h) == "이 기업은 적합합니다"


def test_cache_get_miss_returns_none(session):
    assert _cache_get(session, "없는해시") is None


def test_batch_uses_cache_and_skips_llm_call(session, monkeypatch):
    h = _hash("프로필", "캐시된사업", "원문1")
    _cache_put(session, h, "캐시된사업", "캐시된 근거")

    calls = []

    def _fake_generate(profile, name, raw):
        calls.append(name)
        return f"새로 생성된 근거: {name}"

    monkeypatch.setattr(evidence, "generate_evidence", _fake_generate)

    results = generate_evidence_batch(
        session, "프로필",
        [(1, "캐시된사업", "원문1"), (2, "새사업", "원문2")],
    )

    assert results[1] == "캐시된 근거"  # 캐시에서 옴, LLM 재호출 안 됨
    assert results[2] == "새로 생성된 근거: 새사업"
    assert calls == ["새사업"]  # 캐시된 것은 호출 목록에 없음


def test_batch_writes_new_results_to_cache(session, monkeypatch):
    monkeypatch.setattr(evidence, "generate_evidence", lambda profile, name, raw: f"근거: {name}")

    generate_evidence_batch(session, "프로필", [(1, "사업A", "원문A")])

    h = _hash("프로필", "사업A", "원문A")
    assert session.query(LlmCache).filter(LlmCache.text_hash == h).count() == 1
    assert _cache_get(session, h) == "근거: 사업A"


def test_batch_does_not_cache_failures(session, monkeypatch):
    monkeypatch.setattr(evidence, "generate_evidence", lambda profile, name, raw: None)

    results = generate_evidence_batch(session, "프로필", [(1, "실패사업", "원문")])

    assert results[1] is None
    h = _hash("프로필", "실패사업", "원문")
    assert session.query(LlmCache).filter(LlmCache.text_hash == h).count() == 0


def test_batch_repeated_call_hits_cache_second_time(session, monkeypatch):
    calls = []
    monkeypatch.setattr(evidence, "generate_evidence", lambda profile, name, raw: calls.append(name) or f"근거: {name}")

    generate_evidence_batch(session, "프로필", [(1, "사업B", "원문B")])
    generate_evidence_batch(session, "프로필", [(1, "사업B", "원문B")])

    assert calls == ["사업B"]  # 두 번째 호출은 캐시 적중, LLM 재호출 없음
