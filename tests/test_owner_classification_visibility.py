"""사장님 화면(장면③ AI 분류+근거)에 뭐가 보이는지 골든 케이스.

핵심 검증축:
  - get_classifications()는 담당자가 확정(confirmed) + 전송(sent_to_owner_at)까지
    마친 건만 반환한다 — 검토 대기(review_required) 건과 확정만 되고 아직 전송
    안 한 건은 원문·Scope·근거를 사장님에게 보여주지 않는다.
  - get_hitl_pending_count()는 "검토 대기 + 확정됐지만 미전송" 건수를 합쳐 반환한다
    (둘 다 사장님 입장에선 아직 "검토중"으로 보여야 하므로).
  - get_pending_send_count()는 확정됐지만 미전송인 건수만 반환한다(관리자 전송 버튼용).
  - GET/POST /classify/{company_id} 응답에 hitl_pending_count가 포함된다.
  - 담당자가 confirm/edit로 확정해도 즉시 노출되지 않고, 반드시
    POST /admin/companies/{id}/send-classifications 를 호출해야 그 시점까지
    확정된 건 전체가 한 번에 사장님 조회 결과에 나타난다.
  - 전송 이후 새로 확정된 건은 다시 전송 전까지 비공개다(재전송 시 그 건만 반영).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from api.queries import (
    get_classifications,
    get_hitl_pending_count,
    get_hitl_queue,
    get_pending_send_count,
)
from db.models import Base, Classification, Company, Voucher

YEAR = 2025


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_voucher_with_classification(session, cid, month, item, *, status, evidence="근거"):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item, supply_amount_krw=100000,
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=1, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=500.0, confidence=0.9,
        evidence=evidence, method="rule", status=status,
    ))
    session.commit()
    return v.id


# ── db/queries.py 순수 로직 ───────────────────────────────────────────────────
def test_get_classifications_excludes_unsent_confirmed(db):
    """확정만 되고 전송 전이면(sent_to_owner_at is null) 사장님 조회 결과에 안 나온다."""
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "확정만 된 건", status="confirmed")
    _add_voucher_with_classification(session, cid, 2, "검토중건", status="review_required")

    assert get_classifications(session, cid) == []


def test_get_classifications_includes_confirmed_and_sent(db):
    session, cid = db
    vid = _add_voucher_with_classification(session, cid, 1, "확정+전송건", status="confirmed")
    c = session.query(Classification).filter_by(voucher_id=vid).one()
    from datetime import datetime, timezone
    c.sent_to_owner_at = datetime.now(timezone.utc)
    session.commit()

    results = get_classifications(session, cid)
    assert len(results) == 1
    assert results[0]["raw"] == "확정+전송건"


def test_get_hitl_pending_count_includes_unsent_confirmed(db):
    """검토 대기 + 확정됐지만 미전송인 건을 합쳐서 센다."""
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "검토중건", status="review_required")
    _add_voucher_with_classification(session, cid, 2, "확정만 된 건", status="confirmed")

    assert get_hitl_pending_count(session, cid) == 2


def test_get_pending_send_count_counts_confirmed_unsent_only(db):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "검토중건", status="review_required")
    _add_voucher_with_classification(session, cid, 2, "확정만 된 건1", status="confirmed")
    _add_voucher_with_classification(session, cid, 3, "확정만 된 건2", status="confirmed")

    assert get_pending_send_count(session, cid) == 2


# ── API 라우터 ────────────────────────────────────────────────────────────────
def test_classify_endpoint_hides_unsent_confirmed(db, client):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "확정만 된 건", status="confirmed")
    _add_voucher_with_classification(session, cid, 2, "검토중건", status="review_required")

    res = client.get(f"/classify/{cid}")
    assert res.status_code == 200
    body = res.json()
    assert body["results"] == []
    assert body["hitl_pending_count"] == 2


def test_confirm_alone_does_not_expose_to_owner(db, client):
    """담당자가 확정 버튼(PATCH .../confirm)만 눌러선 사장님 화면에 안 나타난다."""
    session, cid = db
    vid = _add_voucher_with_classification(session, cid, 1, "검토중건", status="review_required")

    confirm_res = client.patch(f"/admin/classifications/{vid}/confirm")
    assert confirm_res.status_code == 200

    after = client.get(f"/classify/{cid}").json()
    assert after["results"] == []
    assert after["hitl_pending_count"] == 1  # 확정됐지만 미전송이라 여전히 "검토중" 취급


def test_send_classifications_exposes_confirmed_batch(db, client):
    """전송 엔드포인트를 눌러야 그 시점까지 확정된 건 전체가 한 번에 노출된다."""
    session, cid = db
    v1 = _add_voucher_with_classification(session, cid, 1, "검토중건1", status="review_required")
    v2 = _add_voucher_with_classification(session, cid, 2, "검토중건2", status="review_required")

    client.patch(f"/admin/classifications/{v1}/confirm")
    client.patch(f"/admin/classifications/{v2}/confirm")

    # 전송 전 — 둘 다 안 보임
    before = client.get(f"/classify/{cid}").json()
    assert before["results"] == []

    send_res = client.post(f"/admin/companies/{cid}/send-classifications")
    assert send_res.status_code == 200
    assert send_res.json()["sent_count"] == 2

    after = client.get(f"/classify/{cid}").json()
    assert len(after["results"]) == 2
    assert after["hitl_pending_count"] == 0


def test_send_classifications_only_sends_pending_ones(db, client):
    """재전송 시 이미 전송된 건은 그대로 두고, 그 사이 새로 확정된 건만 추가로 나간다."""
    session, cid = db
    v1 = _add_voucher_with_classification(session, cid, 1, "1차건", status="review_required")
    client.patch(f"/admin/classifications/{v1}/confirm")
    first_send = client.post(f"/admin/companies/{cid}/send-classifications")
    assert first_send.json()["sent_count"] == 1

    v2 = _add_voucher_with_classification(session, cid, 2, "2차건", status="review_required")
    client.patch(f"/admin/classifications/{v2}/confirm")

    second_send = client.post(f"/admin/companies/{cid}/send-classifications")
    assert second_send.json()["sent_count"] == 1  # 1차건은 재전송 대상 아님

    after = client.get(f"/classify/{cid}").json()
    assert len(after["results"]) == 2


def test_send_classifications_unknown_company_returns_404(db, client):
    res = client.post("/admin/companies/99999/send-classifications")
    assert res.status_code == 404


def test_company_overview_includes_pending_send_count(db, client):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "확정만 된 건", status="confirmed")

    res = client.get(f"/admin/companies/{cid}/overview")
    assert res.status_code == 200
    assert res.json()["pending_send_count"] == 1


# ── HITL 검토 작업대(get_hitl_queue) — 확정해도 전송 전까지 남는다 ─────────────
def test_hitl_queue_keeps_confirmed_unsent_items_with_status_flag(db, client):
    """검토 대기 건과 확정만 된(미전송) 건이 같은 큐에 status로 구분돼 함께 보인다."""
    session, cid = db
    v1 = _add_voucher_with_classification(session, cid, 1, "검토중건", status="review_required")
    v2 = _add_voucher_with_classification(session, cid, 2, "확정된건", status="review_required")
    client.patch(f"/admin/classifications/{v2}/confirm")

    queue = get_hitl_queue(session)
    assert len(queue) == 2
    by_id = {item["voucher_id"]: item["status"] for item in queue}
    assert by_id[v1] == "review_required"
    assert by_id[v2] == "confirmed"


def test_hitl_queue_drops_item_only_after_send(db, client):
    """전송 버튼을 눌러야 그 건이 검토 작업대에서도 함께 사라진다."""
    session, cid = db
    vid = _add_voucher_with_classification(session, cid, 1, "검토중건", status="review_required")
    client.patch(f"/admin/classifications/{vid}/confirm")
    assert len(get_hitl_queue(session)) == 1  # 확정만으론 안 빠짐

    client.post(f"/admin/companies/{cid}/send-classifications")
    assert get_hitl_queue(session) == []
