"""GET/PATCH /owner/{company_id}/notifications — 확정 전송 알림 (v1 §6-2).

핵심 검증축:
  - unread=true 필터가 실제로 읽지 않은 것만 반환한다.
  - 최신순 정렬.
  - 읽음 처리는 해당 기업 소유 알림에만 적용되고, 다른 기업 알림은 404.
  - 이미 읽은 알림을 다시 읽음 처리해도 에러 없이 그대로(멱등).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Company, OwnerNotification


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        c1 = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        c2 = Company(name="다른기업", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add_all([c1, c2])
        session.commit()
        yield session, c1.id, c2.id


@pytest.fixture()
def client(db):
    session, _, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_notification(session, cid, message, *, read=False):
    from datetime import datetime, timezone
    n = OwnerNotification(
        company_id=cid, type="classification_sent", message=message,
        payload={"sent_count": 1},
        read_at=datetime.now(timezone.utc) if read else None,
    )
    session.add(n)
    session.commit()
    return n.id


def test_lists_notifications_most_recent_first(db, client):
    session, cid, _ = db
    _add_notification(session, cid, "첫번째")
    _add_notification(session, cid, "두번째")

    res = client.get(f"/owner/{cid}/notifications")
    assert res.status_code == 200
    messages = [n["message"] for n in res.json()["notifications"]]
    assert messages == ["두번째", "첫번째"]


def test_unread_filter_excludes_read_notifications(db, client):
    session, cid, _ = db
    _add_notification(session, cid, "읽음", read=True)
    _add_notification(session, cid, "안읽음")

    res = client.get(f"/owner/{cid}/notifications?unread=true")
    assert res.status_code == 200
    messages = [n["message"] for n in res.json()["notifications"]]
    assert messages == ["안읽음"]


def test_mark_read_sets_read_at(db, client):
    session, cid, _ = db
    nid = _add_notification(session, cid, "안읽음")

    res = client.patch(f"/owner/{cid}/notifications/{nid}/read")
    assert res.status_code == 200
    assert res.json()["read_at"] is not None

    notification = session.get(OwnerNotification, nid)
    assert notification.read_at is not None


def test_mark_read_is_idempotent(db, client):
    session, cid, _ = db
    nid = _add_notification(session, cid, "안읽음")

    first = client.patch(f"/owner/{cid}/notifications/{nid}/read")
    second = client.patch(f"/owner/{cid}/notifications/{nid}/read")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["read_at"] == second.json()["read_at"]


def test_mark_read_rejects_other_companys_notification(db, client):
    session, cid, other_cid = db
    nid = _add_notification(session, cid, "내 알림 아님")

    res = client.patch(f"/owner/{other_cid}/notifications/{nid}/read")
    assert res.status_code == 404
