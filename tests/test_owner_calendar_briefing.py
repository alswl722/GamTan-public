"""탄소 캘린더 + 월간 AI 브리핑 라우터 — GET /owner/{id}/calendar, /briefing.

핵심 검증축:
  - 캘린더: issue_date가 없는 전표는 결과에서 빠진다(정확한 날짜에 못 꽂음).
  - 캘린더: review_required(HITL 대기)나 미전송 confirmed 건은 사장님에게
    노출되지 않는다(get_classifications()와 동일 원칙).
  - 캘린더: 에이전트 트레이스(활동 로그)는 완전히 제외되고, 구매·탄소
    배출 내역(전표 + emission_tco2e)만 날짜 오름차순으로 반환된다.
  - 브리핑: 지난달 데이터가 없으면 has_previous_month=False, 비교 없이
    시작 안내 문단만 온다.
  - 브리핑: 지난달 대비 증감이 실제 emission_co2e 합계 비율과 일치한다.

이 파일은 GEMINI_API_KEY를 비워 항상 템플릿 경로(generated_by="template")로
돈다 — 실제 LLM 호출은 네트워크·비용이 드는 별도 관심사라 여기 통합
테스트에서는 검증하지 않는다(LLM 문장 생성 자체의 동작은
db/owner_briefing.py::generate_briefing_paragraphs_llm을 직접 호출해
수동으로 확인함). 여기서는 "증감 계산이 맞는가", "그 계산값이 어떤 경로로든
편지에 반영되는가"만 검증한다.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import (
    Base,
    BorrowerEmissionInventory,
    CarbonNeutralPointApplication,
    Classification,
    Company,
    FinancialInstitution,
    OrganizationalBoundary,
    TraceLog,
    Voucher,
)

YEAR = 2026


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """이 파일의 모든 테스트는 템플릿 폴백 경로만 검증 — LLM 호출 자체를 막아
    네트워크 의존 없이 결정론적으로 돈다."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        c = Company(name="구미정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(c)
        session.commit()
        yield session, c.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_voucher(session, cid, *, month, day, fuel="경유", scope=1, co2e=2000.0, status="auto", sent=True, issue_date=True):
    from datetime import datetime, timezone

    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        issue_date=datetime(YEAR, month, day, tzinfo=timezone.utc) if issue_date else None,
        item_description=f"{fuel} 전표", supply_amount_krw=500000,
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="이동연소", fuel_type=fuel,
        amount_krw=500000, emission_co2e=co2e, confidence=0.9,
        evidence="test", method="rule", status=status,
        sent_to_owner_at=datetime(YEAR, month, day, tzinfo=timezone.utc) if (status == "confirmed" and sent) else None,
    ))
    session.commit()
    return v.id


def test_calendar_excludes_voucher_without_issue_date(db, client):
    session, cid = db
    _add_voucher(session, cid, month=7, day=12, issue_date=True)
    _add_voucher(session, cid, month=7, day=20, issue_date=False)  # 발행일 없음

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    assert res.status_code == 200
    events = res.json()["events"]
    assert len(events) == 1
    assert events[0]["date"] == f"{YEAR}-07-12"


def test_calendar_hides_pending_and_unsent_classifications(db, client):
    session, cid = db
    _add_voucher(session, cid, month=7, day=5, status="review_required")  # HITL 대기
    _add_voucher(session, cid, month=7, day=8, status="confirmed", sent=False)  # 확정했지만 미전송
    _add_voucher(session, cid, month=7, day=10, status="confirmed", sent=True)  # 확정+전송

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    assert len(events) == 1
    assert events[0]["date"] == f"{YEAR}-07-10"


def test_calendar_excludes_trace_logs():
    """사장님 캘린더는 구매·탄소 배출 내역만 보여준다 — 에이전트 활동 로그
    (결손 감지·이상치 검증 등)는 완전히 제외한다(2026-08-19 사용자 피드백:
    "이건 그냥 실행 이력을 가져온거잖아"). trace_logs가 아무리 쌓여 있어도
    응답에 섞이지 않는지 확인."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with SASession(engine) as session:
        c = Company(name="구미정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(c)
        session.commit()
        _add_voucher(session, c.id, month=7, day=15)
        session.add(TraceLog(
            company_id=c.id, session_id="s1", step_type="관찰", tool_name="check_coverage_gaps",
            message="3~5월 가스 결손 발견",
        ))
        session.commit()

        from api.queries import get_calendar_events
        events = get_calendar_events(session, c.id, YEAR, 7)

    assert len(events) == 1  # trace 1건은 결과에서 완전히 빠짐, voucher 1건만
    assert all("step_type" not in e for e in events)
    assert all("message" not in e for e in events)


def test_calendar_includes_upload_event_separate_from_issue_date(db, client):
    """전표가 다루는 거래월(issue_date)과 실제 업로드 시각(created_at)이 다를 때,
    캘린더는 둘 다 각자의 날짜에 별도 이벤트로 노출해야 한다(업로드 시점 표시)."""
    session, cid = db
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=6,
        issue_date=datetime(YEAR, 6, 30, tzinfo=timezone.utc),  # 6월분 고지서
        created_at=datetime(YEAR, 7, 3, tzinfo=timezone.utc),   # 7월에 업로드
        item_description="경유 전표", supply_amount_krw=500000,
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=1, category="이동연소", fuel_type="경유",
        amount_krw=500000, emission_co2e=1000.0, confidence=0.9,
        evidence="test", method="rule", status="auto",
    ))
    session.commit()

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    upload_events = [e for e in events if e["entry_type"] == "upload"]
    assert len(upload_events) == 1
    assert upload_events[0]["date"] == f"{YEAR}-07-03"
    assert upload_events[0]["count"] == 1


def test_calendar_groups_same_day_uploads_into_one_event(db, client):
    """하루에 여러 건을 업로드해도 캘린더엔 그 날짜 점 하나로만 나와야 한다
    (건별로 나열하면 캘린더가 점으로 뒤덮이는 문제, 2026-08-25 사용자 피드백)."""
    session, cid = db
    for i in range(3):
        v = Voucher(
            company_id=cid, source="hometax", year=YEAR, month=7,
            created_at=datetime(YEAR, 7, 3, 9 + i, tzinfo=timezone.utc),
            item_description=f"전표{i}", supply_amount_krw=100000,
        )
        session.add(v)
    session.commit()

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    upload_events = [e for e in events if e["entry_type"] == "upload"]
    assert len(upload_events) == 1
    assert upload_events[0]["count"] == 3


def test_calendar_includes_report_generation_event(db, client):
    session, cid = db
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    boundary = OrganizationalBoundary(
        financial_institution_id=inst.id, company_id=cid, reporting_year=YEAR,
        boundary_type="operational_control", consolidation_scope="separate",
    )
    session.add(boundary)
    session.commit()
    inv = BorrowerEmissionInventory(
        financial_institution_id=inst.id,
        company_id=cid, reporting_year=YEAR, organizational_boundary_id=boundary.id,
        scope_group="scope_1", emission_tco2e=3.21,
        status="calculated", version=1,
        created_at=datetime(YEAR, 7, 14, tzinfo=timezone.utc),
    )
    session.add(inv)
    session.commit()

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    report_events = [e for e in events if e["entry_type"] == "report"]
    assert len(report_events) == 1
    assert report_events[0]["date"] == f"{YEAR}-07-14"
    assert report_events[0]["emission_tco2e"] == 3.21
    assert report_events[0]["count"] == 1


def test_calendar_groups_same_day_report_scopes_into_one_event(db, client):
    """같은 날 Scope1·Scope2 리포트가 각각 새 버전으로 저장돼도 캘린더엔 그
    날짜 점 하나로만 나와야 한다(2026-08-25 사용자 피드백)."""
    session, cid = db
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    boundary = OrganizationalBoundary(
        financial_institution_id=inst.id, company_id=cid, reporting_year=YEAR,
        boundary_type="operational_control", consolidation_scope="separate",
    )
    session.add(boundary)
    session.commit()
    for scope, val, hour in [("scope_1", 1.0, 9), ("scope_2", 2.0, 10)]:
        session.add(BorrowerEmissionInventory(
            financial_institution_id=inst.id,
            company_id=cid, reporting_year=YEAR, organizational_boundary_id=boundary.id,
            scope_group=scope, emission_tco2e=val,
            status="calculated", version=1,
            created_at=datetime(YEAR, 7, 14, hour, tzinfo=timezone.utc),
        ))
    session.commit()

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    report_events = [e for e in events if e["entry_type"] == "report"]
    assert len(report_events) == 1
    assert report_events[0]["count"] == 2


def test_calendar_includes_carbon_point_application_event(db, client):
    session, cid = db
    app_row = CarbonNeutralPointApplication(
        company_id=cid, application_type="business",
        baseline_year=YEAR - 2, target_year=YEAR,
        created_at=datetime(YEAR, 7, 22, tzinfo=timezone.utc),
    )
    session.add(app_row)
    session.commit()

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    app_events = [e for e in events if e["entry_type"] == "carbon_point_application"]
    assert len(app_events) == 1
    assert app_events[0]["date"] == f"{YEAR}-07-22"


def test_calendar_events_sorted_by_date(db, client):
    session, cid = db
    _add_voucher(session, cid, month=7, day=20)
    _add_voucher(session, cid, month=7, day=3)
    _add_voucher(session, cid, month=7, day=15)

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    assert res.status_code == 200
    dates = [e["date"] for e in res.json()["events"]]
    assert dates == sorted(dates)


def test_calendar_includes_emission_tco2e(db, client):
    session, cid = db
    _add_voucher(session, cid, month=7, day=12, co2e=2360.0)  # kg → 2.36 tCO2e

    res = client.get(f"/owner/{cid}/calendar?year={YEAR}&month=7")
    events = res.json()["events"]
    assert events[0]["emission_tco2e"] == 2.36


def test_briefing_first_month_has_no_comparison(db, client):
    session, cid = db
    _add_voucher(session, cid, month=7, day=12, fuel="경유", co2e=2360.0, status="confirmed", sent=True)

    res = client.get(f"/owner/{cid}/briefing?year={YEAR}&month=7")
    assert res.status_code == 200
    body = res.json()
    assert body["has_previous_month"] is False
    assert len(body["paragraphs"]) >= 1
    assert not any("%" in p for p in body["paragraphs"])


def test_briefing_delta_matches_emission_ratio(db, client):
    session, cid = db
    # 지난달(6월) 경유 2000kgCO2e, 이번달(7월) 2360kgCO2e → +18%
    _add_voucher(session, cid, month=6, day=10, fuel="경유", co2e=2000.0, status="confirmed", sent=True)
    _add_voucher(session, cid, month=7, day=12, fuel="경유", co2e=2360.0, status="confirmed", sent=True)

    res = client.get(f"/owner/{cid}/briefing?year={YEAR}&month=7")
    assert res.status_code == 200
    body = res.json()
    assert body["has_previous_month"] is True
    fuel_stat = next(f for f in body["fuel_stats"] if f["fuel_type"] == "경유")
    assert fuel_stat["direction"] == "up"
    assert fuel_stat["delta_pct"] == 18.0
    assert body["generated_by"] == "template"  # GEMINI_API_KEY 없어 폴백
    assert any("경유" in p and "18%" in p for p in body["paragraphs"])


def test_briefing_excludes_pending_classifications_from_totals(db, client):
    session, cid = db
    _add_voucher(session, cid, month=7, day=5, fuel="경유", co2e=9999.0, status="review_required")
    _add_voucher(session, cid, month=7, day=10, fuel="경유", co2e=1000.0, status="confirmed", sent=True)

    res = client.get(f"/owner/{cid}/briefing?year={YEAR}&month=7")
    body = res.json()
    fuel_stat = next((f for f in body["fuel_stats"] if f["fuel_type"] == "경유"), None)
    assert fuel_stat is not None
    # review_required 건(9999kg)이 합산에 안 섞였는지 — 1000kg=1.0tCO2e만 반영
    assert fuel_stat["this_month_co2e"] == 1.0
