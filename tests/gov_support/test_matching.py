"""정부 지원사업 매칭(db/gov_support/matching.py) 골든 케이스.
docs/gov-support-matching-plan.md §4·§6-2·§6-5 정본.

핵심 검증축:
  - 지역 자격 하드 필터(§6-5) — 태그 없음/전국은 통과, 특정 타 지역은 차단
  - 마감된 공고(apply_end_date < 오늘)는 제외, null(파싱 실패·상시모집)은 포함
  - 유사도 임계값 미만은 제외, 임베딩 실패 시 억지로 채우지 않고 빈 리스트
  - embedding 컬럼은 pgvector Vector가 아니라 JSON이라 SQLite로도 테스트 가능
    (§5 정정 — 이 프로젝트 테스트 전체가 SQLite로 돈다)
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.gov_support import matching
from db.gov_support.matching import (
    company_profile_text,
    cosine_similarity,
    is_region_eligible,
    match_gov_support_programs,
)
from db.models import Base, Company, GovSupportProgram

TODAY = date(2026, 8, 18)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            region="경북 구미", employee_count=12,
            fuel_types_json={"city_gas": True, "electricity": True, "diesel": False},
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_program(session, *, external_id, program_name, region_tags=None,
                  apply_end_date=None, embedding=None, is_active=True):
    p = GovSupportProgram(
        source="bizinfo", external_id=external_id, program_name=program_name,
        region_tags=region_tags, apply_end_date=apply_end_date,
        embedding=embedding, is_active=is_active,
        raw_text=program_name,
    )
    session.add(p)
    session.commit()
    return p


# --- is_region_eligible ---

def test_region_no_tags_passes():
    assert is_region_eligible("경북 구미", None) is True


def test_region_matching_passes():
    assert is_region_eligible("경북 구미", "경북") is True


def test_region_other_region_blocked():
    assert is_region_eligible("경북 구미", "경기") is False


def test_region_national_passes():
    many_regions = ",".join([f"지역{i}" for i in range(12)])
    assert is_region_eligible("경북 구미", many_regions) is True


def test_region_company_region_missing_passes():
    # 기업 지역 정보가 없으면 배제하지 않는다(안전하게 포함) — §6-5
    assert is_region_eligible(None, "경기") is True


# --- cosine_similarity ---

def test_cosine_identical_vectors_is_one():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector_is_zero_not_error():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# --- company_profile_text ---

def test_profile_text_includes_only_checked_fuels(db):
    session, company_id = db
    company = session.get(Company, company_id)
    text = company_profile_text(company)
    assert "도시가스" in text
    assert "전기" in text
    assert "경유" not in text  # fuel_types_json에서 diesel=False


# --- match_gov_support_programs ---

def test_match_excludes_expired_programs(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    # date.today()가 테스트 실행 시점과 무관하게 항상 TODAY를 반환하도록 고정
    # (실제 datetime.date는 못 바꾸므로, matching 모듈이 참조하는 이름만 교체).
    fixed_date = type("FixedDate", (), {"today": staticmethod(lambda: TODAY)})
    monkeypatch.setattr(matching, "date", fixed_date)
    _add_program(
        session, external_id="A", program_name="마감된 사업",
        apply_end_date=TODAY - timedelta(days=1), embedding=[1.0, 0.0],
    )
    _add_program(
        session, external_id="B", program_name="진행중 사업",
        apply_end_date=TODAY + timedelta(days=10), embedding=[1.0, 0.0],
    )
    results = match_gov_support_programs(session, company_id, similarity_threshold=0.0)
    names = [r["program_name"] for r in results]
    assert "진행중 사업" in names
    assert "마감된 사업" not in names


def test_match_includes_null_end_date_as_ongoing(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    _add_program(session, external_id="C", program_name="상시모집", apply_end_date=None, embedding=[1.0, 0.0])
    results = match_gov_support_programs(session, company_id, similarity_threshold=0.0)
    assert any(r["program_name"] == "상시모집" for r in results)


def test_match_excludes_other_region(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    _add_program(session, external_id="D", program_name="경기도 전용 사업", region_tags="경기", embedding=[1.0, 0.0])
    _add_program(session, external_id="E", program_name="경북 전용 사업", region_tags="경북", embedding=[1.0, 0.0])
    results = match_gov_support_programs(session, company_id, similarity_threshold=0.0)
    names = [r["program_name"] for r in results]
    assert "경북 전용 사업" in names
    assert "경기도 전용 사업" not in names


def test_match_respects_similarity_threshold(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    _add_program(session, external_id="F", program_name="유사도 높음", embedding=[1.0, 0.0])
    _add_program(session, external_id="G", program_name="유사도 낮음", embedding=[0.0, 1.0])
    results = match_gov_support_programs(session, company_id, similarity_threshold=0.9)
    names = [r["program_name"] for r in results]
    assert "유사도 높음" in names
    assert "유사도 낮음" not in names


def test_match_returns_empty_when_embedding_fails(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: None)
    _add_program(session, external_id="H", program_name="사업", embedding=[1.0, 0.0])
    results = match_gov_support_programs(session, company_id, similarity_threshold=0.0)
    assert results == []  # 임베딩 실패 시 억지로 채우지 않는다(§7 실패 가시성)


def test_match_excludes_inactive_programs(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    _add_program(session, external_id="I", program_name="비활성 사업", embedding=[1.0, 0.0], is_active=False)
    results = match_gov_support_programs(session, company_id, similarity_threshold=0.0)
    assert results == []


def test_match_respects_top_k(db, monkeypatch):
    session, company_id = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    for i in range(5):
        _add_program(session, external_id=f"J{i}", program_name=f"사업{i}", embedding=[1.0, 0.0])
    results = match_gov_support_programs(session, company_id, top_k=2, similarity_threshold=0.0)
    assert len(results) == 2


def test_match_unknown_company_returns_empty(db, monkeypatch):
    session, _ = db
    monkeypatch.setattr(matching, "embed_query", lambda text: [1.0, 0.0])
    results = match_gov_support_programs(session, 999999, similarity_threshold=0.0)
    assert results == []
