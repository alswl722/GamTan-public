"""승인요청 큐(우대금리·설비금융) + 원본문서 접근 감사 로그 테스트 (v1 §6 2주차).

핵심 검증축:
  - 기존 HITL 큐(분류 신뢰도)와 승인요청 큐(우대금리·설비금융)는 완전히 분리된
    데이터·엔드포인트다 — 둘을 섞으면 안 된다.
  - 승인/반려는 여신 결정이 아니다(CLAUDE.md §9) — 응답에 항상 비보장 문구가 있다(원칙6).
  - 요청 생성 시점의 등급 스냅샷은 이후 재산정과 무관하게 그대로 보존된다.
  - 이미 처리된 요청은 재처리할 수 없다(멱등 조치 방지).
  - 원본문서 열람은 조회할 때마다 접근 로그에 남는다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.init_db import (
    seed_emission_factors,
    seed_industry_distributions,
    seed_pcaf_quality_rules,
    seed_unit_prices,
)
from db.models import Base, Classification, Company, FinancialInstitution, SourceDocument, Voucher
from db.rate_approvals import (
    AlreadyProcessedError,
    CompanyNotFoundError,
    InvalidScopeError,
    NoUpgradeCandidateError,
    create_rate_request,
    list_rate_requests,
    review_rate_request,
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
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        seed_pcaf_quality_rules(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_classified_voucher(session, cid, month, item, *, scope, emission, status="auto", quantity=100):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000,
        raw_json={"quantity": quantity} if quantity is not None else {},
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=emission, confidence=0.9,
        evidence="테스트", method="rule", status=status,
    ))
    session.commit()
    return v.id


def _make_upgrade_candidate(session, cid, scope_group="scope_1"):
    """해당 Scope 전표 12개월 전부를 매출 환산(수량 없음, revenue/4등급)으로 채워
    정식 엔진 기준 등급 상승 후보가 되도록 한다(4등급→3등급, test_admin.py와 동일 패턴)."""
    scope = 1 if scope_group == "scope_1" else 2
    item = "유류대금" if scope_group == "scope_1" else "전기요금"
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, item, scope=scope, emission=100.0, quantity=None)


# ── db/rate_approvals.py 순수 로직 ───────────────────────────────────────────
def test_create_rate_request_snapshots_grade_at_creation_time(db):
    """생성 시점 등급 스냅샷은 저장되고, 이후 재산정과 무관하게 유지된다."""
    session, cid = db
    _make_upgrade_candidate(session, cid)

    req = create_rate_request(session, cid, request_type="rate_upgrade", scope_group="scope_1")
    assert req.scope_group == "scope_1"
    assert req.current_grade == 4
    assert req.target_grade == 3
    assert req.missing_summary
    assert req.status == "pending"
    assert "보장하지 않습니다" in req.disclaimer_text


def test_create_rate_request_fails_when_already_at_best_achievable_grade(db):
    """이미 도달 가능한 최고 등급(production 기반, 3등급)이면 요청 자체를 만들 수 없다
    (추정으로 채우지 않음)."""
    session, cid = db
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, "도시가스", scope=1, emission=100.0, quantity=100)

    with pytest.raises(NoUpgradeCandidateError):
        create_rate_request(session, cid, request_type="rate_upgrade", scope_group="scope_1")


def test_create_rate_request_rejects_missing_scope_group(db):
    """rate_upgrade 요청인데 scope_group이 없으면 어느 Scope에 대한 것인지 알 수 없어
    명확히 실패한다(정식 엔진은 Scope별 독립 판정이라 필수)."""
    session, cid = db
    _make_upgrade_candidate(session, cid)

    with pytest.raises(InvalidScopeError):
        create_rate_request(session, cid, request_type="rate_upgrade", scope_group=None)


def test_create_rate_request_unknown_company_raises(db):
    session, _ = db
    with pytest.raises(CompanyNotFoundError):
        create_rate_request(session, 99999, request_type="rate_upgrade", scope_group="scope_1")


def test_equipment_finance_request_does_not_require_grade_candidate(db):
    """설비금융 요청은 K택소노미 필드가 아직 없어 등급 스냅샷 없이도 생성 가능해야 한다."""
    session, cid = db
    req = create_rate_request(session, cid, request_type="equipment_finance")
    assert req.request_type == "equipment_finance"
    assert req.scope_group is None
    assert req.current_grade is None
    assert req.target_grade is None
    assert req.status == "pending"


def test_review_rate_request_approve_sets_reviewer_and_timestamp(db):
    session, cid = db
    _make_upgrade_candidate(session, cid)
    req = create_rate_request(session, cid, scope_group="scope_1")

    approved = review_rate_request(session, req.id, decision="approved", reviewed_by="bank-officer-1")
    assert approved.status == "approved"
    assert approved.reviewed_by == "bank-officer-1"
    assert approved.reviewed_at is not None


def test_review_rate_request_already_processed_raises_and_is_not_overwritten(db):
    """이미 처리된 요청은 재처리 시 예외를 던지고, 원래 처리 정보는 바뀌지 않는다(멱등 조치 방지)."""
    session, cid = db
    _make_upgrade_candidate(session, cid)
    req = create_rate_request(session, cid, scope_group="scope_1")
    review_rate_request(session, req.id, decision="approved", reviewed_by="officer-1")

    with pytest.raises(AlreadyProcessedError):
        review_rate_request(session, req.id, decision="rejected", reviewed_by="officer-2")

    session.refresh(req)
    assert req.status == "approved"  # 두 번째 시도(반려)가 첫 승인을 덮어쓰지 않음
    assert req.reviewed_by == "officer-1"


def test_review_rate_request_same_decision_twice_also_raises(db):
    """이미 승인된 요청을 다른 담당자가 또 "승인"해도 조용히 성공하지 않고 예외를 던진다 —
    이전엔 이 케이스만 통과돼서 두 번째 담당자가 자기 처리가 반영된 줄 착각할 수 있었다
    (리뷰 지적사항, PR #28)."""
    session, cid = db
    _make_upgrade_candidate(session, cid)
    req = create_rate_request(session, cid, scope_group="scope_1")
    review_rate_request(session, req.id, decision="approved", reviewed_by="officer-1")

    with pytest.raises(AlreadyProcessedError):
        review_rate_request(session, req.id, decision="approved", reviewed_by="officer-2-imposter")

    session.refresh(req)
    assert req.reviewed_by == "officer-1"


def test_list_rate_requests_filters_by_status(db):
    session, cid = db
    _make_upgrade_candidate(session, cid)
    req = create_rate_request(session, cid, scope_group="scope_1")
    review_rate_request(session, req.id, decision="approved", reviewed_by="officer-1")

    company2 = Company(name="타사", industry_code="C251")
    session.add(company2)
    session.commit()
    _make_upgrade_candidate(session, company2.id)
    create_rate_request(session, company2.id, scope_group="scope_1")  # pending 상태로 남김

    pending = list_rate_requests(session, status="pending")
    approved = list_rate_requests(session, status="approved")
    assert len(pending) == 1
    assert len(approved) == 1
    assert pending[0].company_id == company2.id


# ── API 라우터 — 사장님 요청 생성 → 관리자 승인/반려 ──────────────────────────
def test_owner_rate_candidate_endpoint_reflects_revenue_dominant_scope(db, client):
    session, cid = db
    _make_upgrade_candidate(session, cid)

    res = client.get(f"/owner/{cid}/rate-candidate")
    assert res.status_code == 200
    body = res.json()
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert cand["scope_group"] == "scope_1"
    assert cand["current_grade"] > cand["target_grade"]
    assert body["disclaimer_text"]


def test_owner_rate_candidate_endpoint_reflects_both_scopes_independently(db, client):
    """Scope1·Scope2가 각각 독립적으로 후보일 수 있다 — 최대 2건."""
    session, cid = db
    _make_upgrade_candidate(session, cid, scope_group="scope_1")
    _make_upgrade_candidate(session, cid, scope_group="scope_2")

    res = client.get(f"/owner/{cid}/rate-candidate")
    scopes = {c["scope_group"] for c in res.json()["candidates"]}
    assert scopes == {"scope_1", "scope_2"}


def test_owner_rate_candidate_endpoint_empty_when_already_at_best_achievable_grade(db, client):
    session, cid = db
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, "도시가스", scope=1, emission=100.0, quantity=100)
        _add_classified_voucher(session, cid, m, "전기요금", scope=2, emission=50.0, quantity=100)

    res = client.get(f"/owner/{cid}/rate-candidate")
    assert res.status_code == 200
    assert res.json()["candidates"] == []


def test_owner_submits_request_then_admin_sees_it_in_queue(db, client):
    """사장님이 만든 요청이 관리자 승인요청 큐(HITL 큐와 분리된)에 그대로 나타난다."""
    session, cid = db
    _make_upgrade_candidate(session, cid)

    post_res = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    )
    assert post_res.status_code == 200, post_res.text
    request_id = post_res.json()["id"]
    assert post_res.json()["status"] == "pending"
    assert post_res.json()["scope_group"] == "scope_1"

    admin_res = client.get("/admin/rate-requests")
    ids = {r["id"] for r in admin_res.json()["requests"]}
    assert request_id in ids
    entry = next(r for r in admin_res.json()["requests"] if r["id"] == request_id)
    assert entry["company_name"] == "○○정밀"
    assert entry["scope_group"] == "scope_1"
    assert entry["disclaimer_text"]


def test_owner_submit_request_fails_clearly_when_already_at_best_achievable_grade(db, client):
    """후보가 아닌데 요청을 보내면 422로 명확히 실패한다(추정으로 채우지 않음)."""
    session, cid = db
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, "도시가스", scope=1, emission=100.0, quantity=100)

    res = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    )
    assert res.status_code == 422


def test_owner_submit_request_fails_clearly_when_scope_group_missing(db, client):
    """rate_upgrade인데 scope_group을 안 보내면 422 — 어느 Scope 요청인지 알 수 없음."""
    session, cid = db
    _make_upgrade_candidate(session, cid)

    res = client.post(f"/owner/{cid}/rate-requests", json={"request_type": "rate_upgrade"})
    assert res.status_code == 422


def test_owner_submit_request_rejects_unknown_request_type_with_422(db, client):
    """request_type이 rate_upgrade/equipment_finance가 아니면 Pydantic 단계에서 422로
    막혀야 한다 — 이전엔 문자열 그대로 받아 DB CHECK 제약에서 처리 안 된 IntegrityError로
    새면서 500이 됐다(리뷰 지적사항, PR #28)."""
    session, cid = db
    _make_upgrade_candidate(session, cid)

    res = client.post(f"/owner/{cid}/rate-requests", json={"request_type": "bogus"})
    assert res.status_code == 422


def test_admin_approve_endpoint_always_includes_disclaimer(db, client):
    """승인 응답에 항상 비보장 문구가 포함된다(원칙6) — 여신 결정처럼 보이지 않게."""
    session, cid = db
    _make_upgrade_candidate(session, cid)
    request_id = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    ).json()["id"]

    res = client.patch(
        f"/admin/rate-requests/{request_id}/approve",
        json={"reviewed_by": "bank-officer-1"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "approved"
    assert "보장하지 않습니다" in body["disclaimer_text"]
    assert body["reviewed_by"] == "bank-officer-1"


def test_admin_reject_endpoint_records_note(db, client):
    session, cid = db
    _make_upgrade_candidate(session, cid)
    request_id = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    ).json()["id"]

    res = client.patch(
        f"/admin/rate-requests/{request_id}/reject",
        json={"reviewed_by": "bank-officer-1", "note": "재무 정보 추가 확인 필요"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"
    assert res.json()["review_note"] == "재무 정보 추가 확인 필요"


def test_admin_approve_already_processed_request_returns_409(db, client):
    session, cid = db
    _make_upgrade_candidate(session, cid)
    request_id = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    ).json()["id"]
    client.patch(f"/admin/rate-requests/{request_id}/approve", json={"reviewed_by": "officer-1"})

    res = client.patch(
        f"/admin/rate-requests/{request_id}/reject",
        json={"reviewed_by": "officer-2"},
    )
    assert res.status_code == 409


def test_admin_approve_already_approved_request_by_different_officer_returns_409(db, client):
    """이미 승인된 요청을 다른 담당자가 또 승인해도 조용히 200이 아니라 409여야 한다 —
    이전엔 같은 decision끼리는 통과돼서 두 번째 담당자가 자기 처리가 반영된 줄 착각할 수
    있었다(리뷰 지적사항, PR #28). 원래 승인자 정보도 그대로 유지돼야 한다."""
    session, cid = db
    _make_upgrade_candidate(session, cid)
    request_id = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    ).json()["id"]
    client.patch(f"/admin/rate-requests/{request_id}/approve", json={"reviewed_by": "officer-1"})

    res = client.patch(
        f"/admin/rate-requests/{request_id}/approve",
        json={"reviewed_by": "officer-2-imposter"},
    )
    assert res.status_code == 409

    unchanged = client.get("/admin/rate-requests").json()["requests"]
    entry = next(r for r in unchanged if r["id"] == request_id)
    assert entry["reviewed_by"] == "officer-1"


def test_admin_rate_requests_queue_is_separate_from_hitl_queue(db, client):
    """승인요청 큐와 HITL 큐는 서로 다른 엔드포인트·데이터다 — 하나가 다른 걸 오염시키지 않는다."""
    session, cid = db
    _make_upgrade_candidate(session, cid)
    # HITL 큐에 걸릴 저신뢰 분류 1건도 함께 심는다.
    _add_classified_voucher(session, cid, 6, "유류대금", scope=1, emission=0.0, status="review_required")

    client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    )

    hitl = client.get("/admin/hitl").json()["queue"]
    rate_requests = client.get("/admin/rate-requests").json()["requests"]

    assert len(hitl) == 1
    assert len(rate_requests) == 1
    # 필드 형태 자체가 다른 자료구조임을 확인 — 승인요청에는 status(pending 등), HITL 큐엔 없음
    assert rate_requests[0]["status"] == "pending"
    assert "status" not in hitl[0] or hitl[0].get("status") != "pending"


# ── 원본문서 접근 감사 로그 ───────────────────────────────────────────────────
def _make_source_document(session, cid):
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    doc = SourceDocument(
        financial_institution_id=inst.id, company_id=cid,
        document_type="tax_invoice", original_filename="invoice.pdf",
        file_hash="a" * 64,
    )
    session.add(doc)
    session.commit()
    return doc.id


def test_viewing_document_records_access_log(db, client):
    session, cid = db
    doc_id = _make_source_document(session, cid)

    res = client.get(f"/admin/documents/{doc_id}", params={"viewed_by": "bank-officer-1"})
    assert res.status_code == 200, res.text
    assert res.json()["access_history"][0]["accessed_by"] == "bank-officer-1"

    log_res = client.get("/admin/documents/access-log")
    entries = log_res.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["accessed_by"] == "bank-officer-1"
    assert entries[0]["company_name"] == "○○정밀"


def test_viewing_document_twice_records_two_entries(db, client):
    """같은 문서를 두 번 열람하면 로그도 두 건 — 열람 자체가 반복 가능한 이벤트다."""
    session, cid = db
    doc_id = _make_source_document(session, cid)

    client.get(f"/admin/documents/{doc_id}", params={"viewed_by": "officer-1"})
    client.get(f"/admin/documents/{doc_id}", params={"viewed_by": "officer-2"})

    res = client.get(f"/admin/documents/{doc_id}", params={"viewed_by": "officer-1"})
    assert len(res.json()["access_history"]) == 3


def test_viewing_nonexistent_document_fails_clearly(db, client):
    res = client.get("/admin/documents/99999", params={"viewed_by": "officer-1"})
    assert res.status_code == 404
