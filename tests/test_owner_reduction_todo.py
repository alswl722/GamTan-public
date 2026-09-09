"""감축 실천 ToDo 라우터 — GET /owner/{id}/reduction-todo.

핵심 검증축:
  - 200 응답, business_scale_hint·todos 두 필드가 온다(goals는 2026-08-26에
    응답에서 제거됨 — 화면 어디에도 렌더링되지 않는 죽은 필드였다).
  - todos는 항상 채워진다(빈 화면 금지, docs/reduction-todo-plan.md §6).
  - 계산 로직 자체(기준부하·todos 조립·사업 규모 분기·LLM 선별)는
    tests/pcaf_engine/test_reduction_actions.py, test_reduction_todo.py가 이미
    단위 테스트로 검증했다 — 여기서는 라우터 배선만 확인한다(엔드포인트가 실제로
    조립 함수를 호출해 그 결과를 그대로 반환하는지).
  - 2026-08-26: 설비 신호가 매칭된 경로에서 라우터가 `_rerank_background_job`
    내부 신호를 pop해 사용자에게 노출하지 않는지, `reorder_status`가 응답에
    남아있는지 검증한다(db/pcaf_engine/reduction_todo.py::reduction_todo_for_
    company의 순수 함수 레벨 테스트와는 다른 축 — 여기서는 라우터가 그 신호를
    실제로 소비하는지를 본다).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import (
    Base,
    Classification,
    Company,
    FinancialInstitution,
    SourceDocument,
    Voucher,
)

YEAR = 2025


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        c = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12,
        )
        session.add(c)
        session.commit()
        yield session, c.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_classified_voucher(
    session, cid, *, month, fuel_type, emission_kg, k_taxonomy_facility_type=None,
):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=f"{fuel_type} 전표",
        supply_amount_krw=100_000,
    )
    session.add(v)
    session.flush()
    scope = 2 if fuel_type == "전기" else 1
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="테스트", fuel_type=fuel_type,
        amount_krw=100_000, emission_co2e=emission_kg, confidence=0.9,
        evidence="test", method="rule", status="auto",
        k_taxonomy_facility_type=k_taxonomy_facility_type,
    ))
    session.commit()
    return v.id


def _set_business_scale(session, cid, contract_type_class):
    """db/pcaf_engine/reduction_todo.py 단위 테스트와 동일한 헬퍼 — 전기고지서
    SourceDocument로 business_scale_hint()가 특정 값을 반환하게 한다."""
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    session.add(SourceDocument(
        financial_institution_id=inst.id, company_id=cid, document_type="electric_bill",
        year=YEAR, month=1, contract_type_class=contract_type_class,
    ))
    session.commit()


def test_reduction_todo_returns_business_scale_hint_and_todos(db, client):
    session, cid = db
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=1000.0)
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    res = client.get(f"/owner/{cid}/reduction-todo")
    assert res.status_code == 200
    body = res.json()
    assert "business_scale_hint" in body
    assert "todos" in body
    assert "goals" not in body
    assert len(body["todos"]) == 3  # 전기고지서가 없어 미확인 → 설비 신호도 없어 tips 폴백


def test_reduction_todo_todos_present_when_no_vouchers(db, client):
    """전표가 아예 없는(막 온보딩한) 기업도 todos는 채워진다 — 빈 화면 금지."""
    session, cid = db

    res = client.get(f"/owner/{cid}/reduction-todo")
    assert res.status_code == 200
    body = res.json()
    assert len(body["todos"]) == 3
    assert body["business_scale_hint"] == "미확인"


def test_facility_signal_response_has_reorder_status_and_no_internal_job(db, client):
    """설비 신호가 매칭된 경로(재배치 대상)에선 reorder_status가 응답에
    있고, `_rerank_background_job`(라우터 내부 신호)은 사용자에게 절대
    노출되지 않는다 — 라우터가 이걸 pop해서 background_tasks에 등록한 뒤
    응답 본문에서 제거해야 한다(2026-08-26)."""
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(
        session, cid, month=1, fuel_type="전기", emission_kg=1000.0,
        k_taxonomy_facility_type="전동지게차",
    )
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=3000.0)

    res = client.get(f"/owner/{cid}/reduction-todo")
    assert res.status_code == 200
    body = res.json()
    assert body["business_scale_hint"] == "제조업/산업체"
    assert body["reorder_status"] == "pending"  # 첫 방문, 캐시 미스
    assert "_rerank_background_job" not in body


def test_fallback_tips_response_has_no_reorder_status(db, client):
    """설비 신호가 없어 FALLBACK_TIPS로 빠지는 경로엔 reorder_status 필드
    자체가 없다 — 재배치 대상이 아니므로("매칭 결과 없을시에는 기본 폴백"
    사용자 확정)."""
    session, cid = db
    _set_business_scale(session, cid, "industrial")
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=1000.0)
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=2000.0)

    res = client.get(f"/owner/{cid}/reduction-todo")
    assert res.status_code == 200
    body = res.json()
    assert "reorder_status" not in body
