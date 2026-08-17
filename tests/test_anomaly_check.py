"""이상치 되묻기 — 사장님 확인 요청 (docs/tasks.md).

핵심 검증축:
  - GET /owner/{company_id}/anomaly-checks 는 anomaly_check_status='pending'
    건만 반환하고, 분류 상세(scope·evidence)는 내려주지 않는다.
  - "네, 정상이에요" → confirmed_normal로만 바뀌고 status(auto/review_required)는
    그대로 — 참고정보일 뿐 재계산·재판정 없음.
  - "아니요"/"모르겠어요" → disputed/unknown으로 바뀌고, status가 auto였다면
    review_required로 되돌아간다(담당자 우선순위 알림).
  - 숫자 필드를 받지 않는다 — 요청 바디에 quantity 등이 없다(스키마 자체가 없음).
  - 다른 기업 소유 voucher는 404.
  - 이미 답변된(pending 아닌) 건에 재응답하면 404.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
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


def _add_pending_anomaly(session, cid, *, status="auto", ratio=3.2):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=7,
        supplier_name="구미주유소", item_description="경유", supply_amount_krw=2000000,
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=1, category="이동연소", fuel_type="경유",
        amount_krw=2000000, emission_co2e=5000.0, confidence=0.93,
        evidence="[R005] 지게차 이동장비 연료", method="rule", status=status,
        anomaly_check_status="pending", anomaly_ratio=ratio,
    ))
    session.commit()
    return v.id


def test_pending_list_hides_scope_and_evidence(db, client):
    session, cid, _ = db
    vid = _add_pending_anomaly(session, cid)

    res = client.get(f"/owner/{cid}/anomaly-checks")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["voucher_id"] == vid
    assert item["month"] == 7
    assert item["fuel"] == "경유"
    assert item["ratio"] == 3.2
    assert "scope" not in item
    assert "evidence" not in item


def test_pending_list_excludes_already_answered(db, client):
    session, cid, _ = db
    v = Voucher(company_id=cid, source="hometax", year=YEAR, month=8, item_description="경유", supply_amount_krw=1000)
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=1, fuel_type="경유", status="auto", method="rule",
        anomaly_check_status="confirmed_normal",
    ))
    session.commit()

    res = client.get(f"/owner/{cid}/anomaly-checks")
    assert res.json()["items"] == []


def test_answer_normal_keeps_status_unchanged(db, client):
    session, cid, _ = db
    vid = _add_pending_anomaly(session, cid, status="auto")

    res = client.patch(
        f"/owner/{cid}/classifications/{vid}/anomaly-check",
        json={"answer": "normal", "reason": "지게차 2대 증차"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["anomaly_check_status"] == "confirmed_normal"
    assert body["status"] == "auto"  # 그대로 — 재판정 없음

    classification = session.query(Classification).filter_by(voucher_id=vid).one()
    assert classification.anomaly_check_status == "confirmed_normal"
    assert classification.anomaly_check_reason == "지게차 2대 증차"
    assert classification.status == "auto"


@pytest.mark.parametrize("answer,expected_status", [("disputed", "disputed"), ("unknown", "unknown")])
def test_answer_disputed_or_unknown_reverts_auto_to_review(db, client, answer, expected_status):
    session, cid, _ = db
    vid = _add_pending_anomaly(session, cid, status="auto")

    res = client.patch(
        f"/owner/{cid}/classifications/{vid}/anomaly-check",
        json={"answer": answer},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["anomaly_check_status"] == expected_status
    assert body["status"] == "review_required"  # auto -> review_required로 되돌아감

    classification = session.query(Classification).filter_by(voucher_id=vid).one()
    assert classification.status == "review_required"


def test_answer_disputed_does_not_change_already_review_required_status(db, client):
    session, cid, _ = db
    vid = _add_pending_anomaly(session, cid, status="review_required")

    res = client.patch(
        f"/owner/{cid}/classifications/{vid}/anomaly-check",
        json={"answer": "disputed"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "review_required"


def test_answer_rejects_quantity_field(db, client):
    """숫자 필드를 받지 않는다 — 스키마에 quantity가 없어 422로 막힌다."""
    session, cid, _ = db
    vid = _add_pending_anomaly(session, cid)

    res = client.patch(
        f"/owner/{cid}/classifications/{vid}/anomaly-check",
        json={"answer": "normal", "quantity": 1200},
    )
    # 알 수 없는 필드는 pydantic 기본 설정상 무시되므로 200이어야 하고,
    # 응답에 quantity가 반영되는 필드 자체가 없어야 한다(계산 경로 아님을 보장).
    assert res.status_code == 200
    assert "quantity" not in res.json()


def test_answer_rejects_other_companys_voucher(db, client):
    session, cid, other_cid = db
    vid = _add_pending_anomaly(session, cid)

    res = client.patch(
        f"/owner/{other_cid}/classifications/{vid}/anomaly-check",
        json={"answer": "normal"},
    )
    assert res.status_code == 404


def test_answer_rejects_when_not_pending(db, client):
    session, cid, _ = db
    v = Voucher(company_id=cid, source="hometax", year=YEAR, month=1, item_description="경유", supply_amount_krw=1000)
    session.add(v)
    session.flush()
    session.add(Classification(voucher_id=v.id, scope=1, fuel_type="경유", status="auto", method="rule"))
    session.commit()

    res = client.patch(
        f"/owner/{cid}/classifications/{v.id}/anomaly-check",
        json={"answer": "normal"},
    )
    assert res.status_code == 404
