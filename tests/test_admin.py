"""관리자 대시보드 백엔드 테스트 — 포트폴리오 집계 / 검토 큐 / 수정·확정·반려 / 실행 이력.

네트워크 없이 sqlite 로 시드 → 분류 몇 건 직접 심고 집계·큐·담당자 조치를 검증한다.
담당자 조치(수정/확정/반려)는 라우터를 실제로 통과시켜야 의미가 있으므로 TestClient 사용.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from api.queries import get_hitl_queue
from db.init_db import (
    seed_emission_factors,
    seed_industry_distributions,
    seed_unit_prices,
)
from db.models import Base, Classification, Company, TraceLog, Voucher
from db.pcaf import company_pcaf_summary, portfolio_summary


@pytest.fixture()
def db(tmp_path):
    # 파일 기반 sqlite + check_same_thread=False — TestClient가 별도 스레드에서
    # 같은 세션을 쓰므로(:memory: 는 스레드 간 공유 불가) 파일 DB로 연결을 공유.
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    """라우터를 sqlite 세션에 물린 TestClient — 담당자 조치 엔드포인트 검증용."""
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add(session, cid, month, item, *, scope, emission, status, conf=0.9):
    v = Voucher(company_id=cid, source="hometax", year=2025, month=month,
                supplier_name="테스트", item_description=item,
                supply_amount_krw=100000, raw_json={"quantity": 100})
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=emission, confidence=conf,
        evidence="테스트", method="rule", status=status,
    ))
    session.commit()
    return v.id


def test_portfolio_matches_per_company_summary(db):
    """포트폴리오 집계는 기업별 company_pcaf_summary(after 우선)와 일치해야 한다."""
    session, cid = db
    _add(session, cid, 1, "도시가스", scope=1, emission=1000.0, status="auto")
    _add(session, cid, 2, "전기요금", scope=2, emission=2000.0, status="auto")

    per = company_pcaf_summary(session, cid)["after"]
    assert per is not None                      # 분류가 있으니 실측 경로
    summ = portfolio_summary(session)

    assert summ["company_count"] == 1
    co = summ["companies"][0]
    assert co["measured"] is True
    assert co["scope1"] == pytest.approx(per["scope1"], abs=0.01)
    assert co["scope2"] == pytest.approx(per["scope2"], abs=0.01)
    assert co["grade"] == per["grade"]          # 집계가 등급을 왜곡하지 않음
    # 등급 분포 합 == 기업 수, 총합 == Scope 합
    assert sum(summ["grade_distribution"].values()) == summ["company_count"]
    assert summ["total"] == pytest.approx(
        summ["scope1_total"] + summ["scope2_total"], abs=0.01
    )


def test_hitl_queue_lists_only_review_required(db):
    """HITL 큐는 review_required 건만, auto/confirmed는 제외."""
    session, cid = db
    _add(session, cid, 3, "유류대금", scope=1, emission=0.0, status="review_required", conf=0.5)
    _add(session, cid, 4, "도시가스", scope=1, emission=500.0, status="auto")

    queue = get_hitl_queue(session)
    assert len(queue) == 1
    assert queue[0]["raw"] == "유류대금"
    assert queue[0]["company_name"] == "○○정밀"
    assert queue[0]["confidence"] == pytest.approx(0.5)


def test_confirm_transitions_and_leaves_queue(db):
    """확정 시 status review_required→confirmed, 큐에서 빠진다."""
    session, cid = db
    vid = _add(session, cid, 5, "유류대금", scope=1, emission=0.0,
               status="review_required", conf=0.5)

    assert len(get_hitl_queue(session)) == 1
    obj = session.query(Classification).filter_by(voucher_id=vid).one()
    obj.status = "confirmed"
    session.commit()

    assert get_hitl_queue(session) == []


def test_portfolio_exposes_before_after_and_coverage(db):
    """대시보드용 파생 필드 — Before는 전 기업 5등급, 커버리지·평균등급 산출."""
    session, cid = db
    _add(session, cid, 1, "도시가스", scope=1, emission=1000.0, status="auto")

    summ = portfolio_summary(session)
    # 도입 전 기준선은 정의상 전 기업 5등급
    assert summ["before_distribution"][5] == summ["company_count"]
    assert sum(summ["before_distribution"].values()) == summ["company_count"]
    # 실측 커버리지: 결손월 보정이 섞이므로 0<pct<=100
    assert 0 < summ["measured_coverage_pct"] <= 100
    assert 1 <= summ["avg_grade"] <= 5


# ── 담당자 조치 (라우터 경유) ────────────────────────────────────────────────
def test_edit_applies_changes_and_audit_log(db, client):
    """수정 후 확정 — 값이 반영되고 evidence에 '무엇을 무엇으로'가 남는다."""
    session, cid = db
    vid = _add(session, cid, 6, "유류대금", scope=1, emission=0.0,
               status="review_required", conf=0.5)

    res = client.patch(f"/admin/classifications/{vid}",
                       json={"scope": 2, "fuel_type": "전기"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "confirmed"

    obj = session.query(Classification).filter_by(voucher_id=vid).one()
    assert obj.scope == 2 and obj.fuel_type == "전기"
    assert "담당자 수정" in obj.evidence
    assert "경유" not in obj.evidence or "연료" in obj.evidence
    assert "테스트" in obj.evidence          # 원본 근거를 지우지 않는다(감사 추적)
    assert get_hitl_queue(session) == []     # 큐에서 빠짐


def test_edit_rejects_already_confirmed(db, client):
    """검토필요가 아닌 건은 409 — 이중 처리 방지."""
    session, cid = db
    vid = _add(session, cid, 7, "도시가스", scope=1, emission=500.0, status="auto")
    res = client.patch(f"/admin/classifications/{vid}", json={"scope": 2})
    assert res.status_code == 409


def test_reject_excludes_from_aggregation(db, client):
    """반려 건은 집계에서 빠진다 — 신뢰 못 하는 분류가 숫자에 남지 않도록."""
    session, cid = db
    keep = _add(session, cid, 1, "도시가스", scope=1, emission=1000.0, status="auto")
    drop = _add(session, cid, 2, "정체불명 유류", scope=1, emission=9000.0,
                status="review_required", conf=0.3)

    before = portfolio_summary(session)["total"]
    res = client.patch(f"/admin/classifications/{drop}/reject")
    assert res.status_code == 200 and res.json()["status"] == "rejected"

    after = portfolio_summary(session)["total"]
    assert after < before, "반려 건이 여전히 집계에 포함됨"
    obj = session.query(Classification).filter_by(voucher_id=drop).one()
    assert "담당자 반려" in obj.evidence
    assert obj.emission_co2e == 9000.0, "반려는 상태만 바꾸고 원본 값은 보존해야 한다"
    assert keep is not None


# ── 이상 신호 알림 (db/alerts.py, 결정론적 배수 계산) ─────────────────────────
def _add_month_total(session, cid, month, emission, *, scope=1, status="auto"):
    """월별 배출량 합계 하나를 만들기 위한 최소 전표+분류 1건."""
    return _add(session, cid, month, f"{month}월 연료", scope=scope, emission=emission, status=status)


def test_alerts_flags_spike_over_recent_average(db, client):
    """최신월이 직전 3개월 평균의 1.5배 이상이면 급등(high)으로 잡힌다."""
    session, cid = db
    for m, e in [(1, 100.0), (2, 100.0), (3, 100.0), (4, 400.0)]:
        _add_month_total(session, cid, m, e)

    res = client.get("/admin/alerts")
    assert res.status_code == 200, res.text
    alerts = [a for a in res.json()["alerts"] if a["company_id"] == cid]
    spikes = [a for a in alerts if a["type"] == "spike"]
    assert len(spikes) == 1
    assert spikes[0]["severity"] == "high"
    assert spikes[0]["month"] == 4


def test_alerts_flags_drop_as_medium(db, client):
    """최신월이 직전 3개월 평균의 0.5배 이하면 급감(medium) — 가동률 하락 의심."""
    session, cid = db
    for m, e in [(1, 200.0), (2, 200.0), (3, 200.0), (4, 50.0)]:
        _add_month_total(session, cid, m, e)

    res = client.get("/admin/alerts")
    alerts = [a for a in res.json()["alerts"] if a["company_id"] == cid]
    drops = [a for a in alerts if a["type"] == "drop"]
    assert len(drops) == 1
    assert drops[0]["severity"] == "medium"


def test_alerts_no_signal_for_stable_trend(db, client):
    """평월과 큰 차이 없는 정상 추세는 알림이 없어야 한다(과잉 발화 방지)."""
    session, cid = db
    for m, e in [(1, 100.0), (2, 105.0), (3, 98.0), (4, 102.0)]:
        _add_month_total(session, cid, m, e)

    res = client.get("/admin/alerts")
    alerts = [a for a in res.json()["alerts"] if a["company_id"] == cid]
    assert [a for a in alerts if a["type"] in ("spike", "drop")] == []


def test_alerts_insufficient_history_is_withheld(db, client):
    """이력이 TREND_WINDOW+1개월 미만이면 추세 판단을 보류한다(오탐 방지)."""
    session, cid = db
    _add_month_total(session, cid, 1, 100.0)
    _add_month_total(session, cid, 2, 500.0)  # 이력 부족 상태에서 배수만 보면 오탐 소지

    res = client.get("/admin/alerts")
    alerts = [a for a in res.json()["alerts"] if a["company_id"] == cid]
    assert [a for a in alerts if a["type"] in ("spike", "drop")] == []


def test_alerts_flags_trailing_data_gap(db, client):
    """마지막 보고월 이후 3개월 이상 공백이면 데이터 공백 알림이 뜬다."""
    session, cid = db
    _add_month_total(session, cid, 1, 100.0)
    _add_month_total(session, cid, 2, 100.0)
    # 3~12월 미연동 → 마지막 보고월(2) 이후 10개월 공백

    res = client.get("/admin/alerts")
    alerts = [a for a in res.json()["alerts"] if a["company_id"] == cid]
    gaps = [a for a in alerts if a["type"] == "gap"]
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "medium"


def test_alerts_sorted_by_severity_then_company(db, client):
    """severity 내림차순(high 먼저), 동률이면 기업명 순."""
    session, cid = db
    for m, e in [(1, 100.0), (2, 100.0), (3, 100.0), (4, 400.0)]:  # high
        _add_month_total(session, cid, m, e)

    res = client.get("/admin/alerts")
    alerts = res.json()["alerts"]
    severities = [a["severity"] for a in alerts]
    order = {"high": 0, "medium": 1, "low": 2}
    assert severities == sorted(severities, key=lambda s: order[s])


def test_traces_groups_runs_with_badges(db, client):
    """실행 이력 — session_id로 묶고 메시지에서 결과 배지를 뽑는다."""
    session, cid = db
    for i, (sid, msg) in enumerate([
        ("s-1", "3·4·5월 도시가스 0건, 제조업 특성상 비정상(결손 발견)"),
        ("s-1", "7월 경유 배출량이 평월 중앙값의 3.2배 — 이상치 의심"),
        ("s-2", "전표 30건 수집 완료"),
    ]):
        session.add(TraceLog(company_id=cid, session_id=sid, step_type="관찰",
                             message=msg, tool_name="테스트"))
    session.commit()

    runs = {r["session_id"]: r for r in client.get("/admin/traces").json()["runs"]}
    assert runs["s-1"]["step_count"] == 2
    assert set(runs["s-1"]["result_badges"]) == {"결손 발견", "이상치"}
    assert runs["s-2"]["result_badges"] == ["정상"]
    assert runs["s-1"]["company_name"] == "○○정밀"
    assert runs["s-1"]["status"] == "완료"
