"""감축 실천 ToDo 조립 레이어(db/pcaf_engine/reduction_todo.py) 골든 케이스.

정본: docs/reduction-todo-plan.md §10-4.

2026-08-25 재설계 — "뭔가 이번주 할일이라는 느낌이 아니잖아" 피드백으로 응답
스키마가 바뀌었다: 메인 콘텐츠는 숫자 카드(goals)가 아니라 동사형 문장(todos).
2026-08-26에 goals 응답 필드 자체를 제거했다(화면 어디에도 렌더링 안 되는
죽은 필드였음) — 그 계산은 이제 LLM 선별의 내부 입력으로만 쓰인다.

핵심 검증축:
  - todos는 항상 채워진다 — 빈 화면 금지(§6 폴백 원칙).
  - 제조업 + 설비 신호 있음 → todos가 그 설비의 동사형 문장이다.
  - 제조업 + 설비 신호 없음(고지서만 있는 기업) → todos가 FALLBACK_TIPS로
    채워진다.
  - 소상공인(business_scale_hint == "소상공인/상업시설") → 설비 신호가 있어도
    todos는 항상 FALLBACK_TIPS다(2층이 원래 약한 트랙이라 설비 기반 문장을
    메인으로 안 쓴다 — 탄소중립포인트 트랙과의 중복 계산 방지가 목적).
  - business_scale_hint는 db/carbon_neutral_point.py::business_scale_hint()를
    그대로 반환한다(새 계산 없음).
  - LLM 선별(순서 재배치)은 문구를 바꾸지 않고, 같은 입력이면 캐시(§10-4 하단)
    에서 재사용한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import (
    Base,
    Classification,
    Company,
    FinancialInstitution,
    ReductionTodoRerankCache,
    SourceDocument,
    Voucher,
)
from db.pcaf_engine.reduction_todo import reduction_todo_for_company

YEAR = 2025


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_classified_voucher(
    session, cid, *, month, fuel_type, emission_kg,
    k_taxonomy_facility_type=None, evidence="test", year=YEAR,
):
    v = Voucher(
        company_id=cid, source="hometax", year=year, month=month,
        supplier_name="테스트", item_description=f"{fuel_type} 전표",
        supply_amount_krw=100_000,
    )
    session.add(v)
    session.flush()
    scope = 2 if fuel_type == "전기" else 1
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="테스트", fuel_type=fuel_type,
        amount_krw=100_000, emission_co2e=emission_kg, confidence=0.9,
        evidence=evidence, method="rule", status="auto",
        k_taxonomy_facility_type=k_taxonomy_facility_type,
    ))
    session.commit()
    return v.id


def _set_business_scale(session, cid, contract_type_class):
    """전기고지서 SourceDocument를 만들어 business_scale_hint()가 특정 값을
    반환하게 한다 — 실제 판별 함수를 그대로 태우는 게 계산기 재구현보다
    정확하다(db/carbon_neutral_point.py::business_scale_hint 실제 조회 조건)."""
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    session.add(SourceDocument(
        financial_institution_id=inst.id, company_id=cid, document_type="electric_bill",
        year=YEAR, month=1, contract_type_class=contract_type_class,
    ))
    session.commit()


# ── todos 메인 콘텐츠 (2026-08-25 재설계) ─────────────────────────────────
#
# 2026-08-26: goals(3층 기준부하 숫자) 응답 필드를 제거했다 — 화면 어디에도
# 렌더링되지 않는 죽은 필드였다(ReductionTodoCard·GoalSheet 둘 다 todos만
# 쓴다). 그 계산 자체(_fuel_load_summary)는 LLM 선별의 입력으로 여전히
# 쓰이므로 아래 "LLM 선별" 섹션에서 그쪽 경로로 검증한다. goals·reasons를
# 직접 검증하던 테스트는 검증 대상 필드가 사라져 함께 지웠다.

def test_manufacturing_with_facility_signal_gets_verb_phrase_todo(db):
    """제조업 + 설비 신호가 있으면 todos가 그 설비의 동사형 문장이다 — FALLBACK_TIPS
    가 아니라 설비 신호 기반 문장이 우선된다."""
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    result = reduction_todo_for_company(session, cid)
    assert result["business_scale_hint"] == "제조업/산업체"
    labels = [t["label"] for t in result["todos"]]
    assert any("충전" in label for label in labels)  # 지게차 충전 시간 문장
    # FALLBACK_TIPS 문구("냉난방 온도", "절전형 조명")는 설비 신호가 있으면 안 섞인다
    assert not any("냉난방" in label for label in labels)


def test_manufacturing_without_facility_signal_falls_back_to_tips(db):
    """제조업이지만 설비 신호가 전혀 없으면(고지서만 있음) todos가 FALLBACK_TIPS로
    채워진다 — 빈 화면 금지."""
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=1000.0)
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=2000.0)

    result = reduction_todo_for_company(session, cid)
    assert result["business_scale_hint"] == "제조업/산업체"
    assert len(result["todos"]) == 3
    assert result["todos"][0]["id"] == "tip_temperature"


def test_commercial_always_uses_tips_even_with_facility_signal(db):
    """소상공인은 설비 신호가 있어도 todos가 FALLBACK_TIPS다 — 2층이 원래
    약한 트랙이라 설비 기반 문장을 메인으로 안 쓴다(탄소중립포인트 트랙과의
    중복 계산 방지가 목적, 2026-08-25 사용자 확정)."""
    session, cid = db
    _set_business_scale(session, cid, "commercial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",  # 신호가 있어도 무시돼야 함
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    result = reduction_todo_for_company(session, cid)
    assert result["business_scale_hint"] == "소상공인/상업시설"
    labels = [t["label"] for t in result["todos"]]
    assert not any("충전" in label for label in labels)
    assert any("냉난방" in label for label in labels)


def test_business_scale_hint_unknown_when_no_electric_bill(db):
    """전기고지서가 아예 없으면(신규 온보딩 직후) '미확인'을 그대로 반환한다 —
    이 모듈이 새로 판정하지 않고 기존 함수 결과를 그대로 노출."""
    session, cid = db
    result = reduction_todo_for_company(session, cid)
    assert result["business_scale_hint"] == "미확인"


def _fake_genai_client(monkeypatch, response_text: str | None = None, *, raises: Exception | None = None):
    """google.genai.Client를 스텁으로 교체. raises가 있으면 generate_content가
    그 예외를 던지고, 없으면 response_text를 응답으로 반환한다."""
    call_count = {"n": 0}

    class _FakeResp:
        text = response_text

    class _FakeModels:
        def generate_content(self, **kwargs):
            call_count["n"] += 1
            if raises is not None:
                raise raises
            return _FakeResp()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.models = _FakeModels()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("google.genai.Client", _FakeClient)
    return call_count


# ── LLM 선별(순서 재배치) — 백그라운드 캐시 조회/저장 (2026-08-26 재설계) ──
#
# 이 함수는 더 이상 그 자리에서 LLM을 부르지 않는다(Gemini 호출이 10초
# 타임아웃을 넘겨 응답 전체를 막던 문제 실측 — 포항이엔지·대구정공,
# 504 DEADLINE_EXCEEDED). reduction_todo_for_company()는 캐시만 조회하고,
# 미스면 원래 순서 + reorder_status="pending" + 백그라운드 작업 신호를
# 반환한다. 실제 LLM 호출+캐시 저장은 run_rerank_and_cache()가 별도로
# 담당한다(라우터가 BackgroundTasks로 큐에 넣는 함수, 여기서는 직접 호출해
# 테스트한다).
#
# 문구 자체는 절대 안 바뀐다는 게 이 기능의 핵심 제약이라, 재배치 테스트는
# "label·note 텍스트는 카탈로그 원본과 동일" + "id 집합이 그대로 보존"을
# 매번 같이 확인한다 — 순서만 바뀌고 내용은 안 바뀌는 것.

def test_cache_miss_returns_original_order_as_pending(db, monkeypatch):
    """캐시가 비어있으면(첫 방문) 원래 순서를 즉시 반환하고 reorder_status가
    "pending"이다 — GEMINI_API_KEY가 있어도 그 자리에서 LLM을 부르지 않는다.

    _rerank_background_job은 이 함수(순수 함수)가 라우터에게 "백그라운드
    작업을 큐에 넣어달라"고 넘기는 내부 신호라 이 단계에선 응답에 실제로
    들어있다 — 그걸 pop해서 사용자에게 안 보이게 하는 건 라우터의 책임이다
    (tests/test_owner_reduction_todo.py에서 검증)."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    result = reduction_todo_for_company(session, cid)

    assert result["reorder_status"] == "pending"
    ids = [t["id"] for t in result["todos"]]
    assert ids == ["compressor_pressure", "facility_전동지게차"]  # 코드가 조립한 원순서 그대로
    job_company_id, job_todos, job_fuel_summary = result["_rerank_background_job"]
    assert job_company_id == cid
    assert [t["id"] for t in job_todos] == ids


def test_no_api_key_still_returns_pending_without_calling_llm(db, monkeypatch):
    """GEMINI_API_KEY가 없어도 캐시 미스면 여전히 "pending"이다 — 백그라운드
    작업 자체가 큐에 남고, 그 작업이 실행될 때 키 부재로 조용히 끝난다.
    reduction_todo_for_company() 단계에서는 키 유무를 아예 보지 않는다."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    result = reduction_todo_for_company(session, cid)
    assert result["reorder_status"] == "pending"


def test_no_reorder_status_when_facility_signal_missing(db):
    """설비 신호가 없어 FALLBACK_TIPS로 빠지는 경로엔 reorder_status 필드
    자체가 없다 — 재배치 대상이 아니므로 "분석 중"이라 할 것도 없다는
    2026-08-26 사용자 확정("매칭 결과 없을시에는 기본 폴백")."""
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=1000.0)
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=2000.0)

    result = reduction_todo_for_company(session, cid)
    assert "reorder_status" not in result


def test_no_reorder_status_for_commercial(db):
    """소상공인도 마찬가지로 재배치 대상이 아니라 reorder_status가 없다."""
    session, cid = db
    _set_business_scale(session, cid, "commercial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    result = reduction_todo_for_company(session, cid)
    assert "reorder_status" not in result


def test_cache_hit_returns_reordered_todos_as_ready(db, monkeypatch):
    """run_rerank_and_cache()로 캐시를 채운 뒤 다시 조회하면 reorder_status가
    "ready"이고 순서가 재배치돼 있다 — label·note 텍스트는 원본과 동일해야
    한다(문장은 절대 안 바뀐다는 계약)."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    first = reduction_todo_for_company(session, cid)
    assert first["reorder_status"] == "pending"
    original_by_id = {t["id"]: t for t in first["todos"]}
    original_ids = [t["id"] for t in first["todos"]]

    _fake_genai_client(monkeypatch, response_text=",".join(reversed(original_ids)))
    # 캐시 키가 일치하려면 job에 실린 fuel_summary를 그대로 써야 한다 — 라우터가
    # background_tasks.add_task(run_rerank_and_cache, *job)로 하는 것과 동일.
    company_id, todos, fuel_summary = first["_rerank_background_job"]
    run_rerank_and_cache(company_id, todos, fuel_summary, session=session)

    second = reduction_todo_for_company(session, cid)
    assert second["reorder_status"] == "ready"
    assert [t["id"] for t in second["todos"]] == list(reversed(original_ids))
    for todo in second["todos"]:
        assert todo["label"] == original_by_id[todo["id"]]["label"]
        assert todo["note"] == original_by_id[todo["id"]]["note"]


# ── run_rerank_and_cache — 백그라운드 실행부 단위 테스트 ────────────────────
#
# 프로덕션에선 요청 스코프 세션이 아니라 api/db.py::new_session()으로 독립
# 세션을 연다(process_upload_job과 같은 패턴). 테스트에서는 session= 인자로
# 위 db fixture(SQLite) 세션을 직접 넘긴다 — process_upload_job 테스트와
# 동일한 컨벤션(owns_session=False라 함수가 세션을 안 닫아, fixture 세션이
# 살아있는 채로 이어서 assert할 수 있다).


def test_run_rerank_and_cache_ignores_unknown_ids_and_appends_missing(db, monkeypatch):
    """LLM 응답에 후보에 없는 id가 섞이거나 일부 id가 누락돼도, 캐시에 저장된
    id 집합은 항상 원래 후보 id 전체와 정확히 일치한다 — id를 지어내도
    노출될 경로가 없다는 원칙1급 방어 구조를 이 함수 단위로 직접 확인."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    _fake_genai_client(monkeypatch, response_text="facility_c,made_up_id,facility_a")

    todos = [
        {"id": "facility_a", "label": "A", "note": None},
        {"id": "facility_b", "label": "B", "note": None},
        {"id": "facility_c", "label": "C", "note": None},
    ]
    run_rerank_and_cache(cid, todos, fuel_summary=[], session=session)

    cached = session.query(ReductionTodoRerankCache).filter_by(company_id=cid).one()
    assert cached.ordered_ids == ["facility_c", "facility_a", "facility_b"]


def test_run_rerank_and_cache_leaves_no_cache_on_exception(db, monkeypatch):
    """API 호출이 예외를 던지면 캐시가 아예 안 남는다 — 다음 요청은 여전히
    "pending"으로 원래 순서를 보여주고, 다음 백그라운드 시도를 다시 큐에
    남길 수 있다. 실패를 트레이스에 남기지 않는다(정렬 취향이지 계산이
    아니므로, _judge_anomaly_with_llm과 다른 지점)."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    _fake_genai_client(monkeypatch, raises=RuntimeError("network down"))

    todos = [
        {"id": "a", "label": "A", "note": None},
        {"id": "b", "label": "B", "note": None},
    ]
    run_rerank_and_cache(cid, todos, fuel_summary=[], session=session)  # 예외 없이 조용히 끝남

    assert session.query(ReductionTodoRerankCache).filter_by(company_id=cid).count() == 0


def test_run_rerank_and_cache_skipped_when_single_todo(monkeypatch):
    """후보가 1개뿐이면 순서를 정할 일이 없으므로 API를 아예 호출하지 않는다."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    def _fail_if_called(**kwargs):
        pytest.fail("todos가 1개뿐인데 LLM이 호출됨")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("google.genai.Client", _fail_if_called)

    todos = [{"id": "only", "label": "Only", "note": None}]
    run_rerank_and_cache(company_id=1, todos=todos, fuel_summary=[])  # 예외 없이 즉시 반환


def test_run_rerank_and_cache_noop_without_api_key(db, monkeypatch):
    """GEMINI_API_KEY가 없으면 캐시를 만들지 않고 조용히 끝난다."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    todos = [
        {"id": "a", "label": "A", "note": None},
        {"id": "b", "label": "B", "note": None},
    ]
    run_rerank_and_cache(cid, todos, fuel_summary=[], session=session)

    assert session.query(ReductionTodoRerankCache).filter_by(company_id=cid).count() == 0


# ── 캐싱 — 2026-08-26 ────────────────────────────────────────────────────
#
# "홈화면 들어올때마다 재계산 되잖아" 지적으로 추가. 핵심 계약: 같은 입력
# 조합(기업·todos 후보·fuel_summary)이면 두 번째 백그라운드 실행부터는
# Gemini를 다시 부르지 않고 기존 캐시를 신뢰한다.

def test_run_rerank_and_cache_second_call_uses_cache_not_api(db, monkeypatch):
    """이미 캐시가 있으면 run_rerank_and_cache가 API를 다시 부르지 않는다
    (중복 실행 방지 — 다른 요청이 그 사이 먼저 채웠을 수 있어서)."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    call_count = _fake_genai_client(monkeypatch, response_text="facility_b,facility_a")

    todos = [
        {"id": "facility_a", "label": "A", "note": None},
        {"id": "facility_b", "label": "B", "note": None},
    ]
    fuel_summary = [{"fuel": "전기", "baseline_month": 1, "baseline_tco2e": 1.0,
                      "current_month": 2, "current_tco2e": 2.0}]

    run_rerank_and_cache(cid, todos, fuel_summary, session=session)
    run_rerank_and_cache(cid, todos, fuel_summary, session=session)

    assert call_count["n"] == 1, "두 번째 실행이 캐시를 안 쓰고 API를 다시 불렀다"
    assert session.query(ReductionTodoRerankCache).filter_by(company_id=cid).count() == 1


def test_run_rerank_and_cache_miss_when_fuel_summary_changes(db, monkeypatch):
    """fuel_summary가 달라지면(새 전표 반영 등) 캐시 키도 달라져 API를 다시
    부른다 — 오래된 순서가 그대로 굳어버리지 않는다는 확인."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    call_count = _fake_genai_client(monkeypatch, response_text="facility_b,facility_a")

    todos = [
        {"id": "facility_a", "label": "A", "note": None},
        {"id": "facility_b", "label": "B", "note": None},
    ]
    summary_v1 = [{"fuel": "전기", "baseline_month": 1, "baseline_tco2e": 1.0,
                   "current_month": 2, "current_tco2e": 2.0}]
    summary_v2 = [{"fuel": "전기", "baseline_month": 1, "baseline_tco2e": 1.0,
                   "current_month": 3, "current_tco2e": 5.0}]  # 배출량 변경

    run_rerank_and_cache(cid, todos, summary_v1, session=session)
    run_rerank_and_cache(cid, todos, summary_v2, session=session)

    assert call_count["n"] == 2, "fuel_summary가 바뀌었는데도 캐시가 재사용됐다"
    assert session.query(ReductionTodoRerankCache).filter_by(company_id=cid).count() == 2


def test_run_rerank_and_cache_scoped_per_company(db, monkeypatch):
    """같은 todos·fuel_summary라도 기업이 다르면 캐시가 섞이지 않는다."""
    from db.pcaf_engine.reduction_todo import run_rerank_and_cache

    session, cid = db
    company_b = Company(
        name="다른회사", industry_code="C251", industry_name="구조용 금속제품 제조",
        employee_count=20,
    )
    session.add(company_b)
    session.commit()

    call_count = _fake_genai_client(monkeypatch, response_text="facility_b,facility_a")

    todos = [
        {"id": "facility_a", "label": "A", "note": None},
        {"id": "facility_b", "label": "B", "note": None},
    ]
    fuel_summary = [{"fuel": "전기", "baseline_month": 1, "baseline_tco2e": 1.0,
                      "current_month": 2, "current_tco2e": 2.0}]

    run_rerank_and_cache(cid, todos, fuel_summary, session=session)
    run_rerank_and_cache(company_b.id, todos, fuel_summary, session=session)

    assert call_count["n"] == 2, "다른 기업인데 캐시가 공유됐다"
    assert session.query(ReductionTodoRerankCache).filter_by(company_id=cid).count() == 1
    assert session.query(ReductionTodoRerankCache).filter_by(company_id=company_b.id).count() == 1
