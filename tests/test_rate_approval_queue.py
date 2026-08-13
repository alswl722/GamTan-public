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
    seed_rate_products,
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
        seed_rate_products(session)
        # 도시가스+전기만 쓰고 경유는 안 쓰는 회사로 고정 — 안 그러면 약한 고리 원칙
        # 아래서 한 번도 안 쓴 경유 버킷의 12개월이 전부 "결손"으로 잡혀 실측을 다
        # 채워도 revenue(4등급)에 묶인다(db/pcaf_quality.py::_selected_fuels 참고).
        # 이 파일의 모든 테스트가 rate_approvals 흐름(PCAF 등급)만 다루므로 공유
        # 픽스처에 걸어도 안전하다(test_admin.py는 get_coverage 등 다른 로직도 같은
        # 픽스처를 쓰기 때문에 거기선 테스트별로 개별 설정했다).
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
            fuel_types_json={"city_gas": True, "electricity": True},
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
    정식 엔진 기준 등급 상승 후보가 되도록 한다(4등급→2등급, test_admin.py와 동일 패턴).

    db 픽스처의 회사는 도시가스+전기만 선택했으므로(경유 미선택) scope_1도 "도시가스"를
    쓴다 — "유류대금"(경유 버킷)을 쓰면 선택 안 된 연료라 매트릭스에서 아예 제외되어
    activity_basis_breakdown이 비고, candidate_score가 4가 아니라 None이 돼버린다."""
    scope = 1 if scope_group == "scope_1" else 2
    item = "도시가스" if scope_group == "scope_1" else "전기요금"
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
    assert req.target_grade == 2
    assert req.missing_summary
    assert req.status == "pending"
    assert "보장하지 않습니다" in req.disclaimer_text


def test_create_rate_request_allows_already_eligible_status(db):
    """이미 도달 가능한 최고 등급(energy_consumption 기반, 2등급)이면 db/rate_products.py가
    매칭 상품(ESG Grow-Up 특별대출, seed_rate_products)을 찾아 "이미 대상" 상태로 요청을
    허용한다 — 더 이상 NoUpgradeCandidateError가 아니다. current_grade==target_grade로
    스냅샷되고 matched_product_name이 채워진다."""
    session, cid = db
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, "도시가스", scope=1, emission=100.0, quantity=100)

    req = create_rate_request(session, cid, request_type="rate_upgrade", scope_group="scope_1")
    assert req.current_grade == 2
    assert req.target_grade == 2
    assert req.matched_product_name == "ESG Grow-Up 특별대출"
    assert "이미 조건을 충족" in req.missing_summary


def test_create_rate_request_fails_when_no_activity_data(db):
    """활동자료(전표) 자체가 없으면 여전히 NoUpgradeCandidateError — 이건 약한 고리
    원칙과 무관하게 애초에 근거가 없는 경우다."""
    session, cid = db
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
    """설비금융 요청은 등급 후보(rate_upgrade) 판정과 무관하게 등급 스냅샷 없이도
    생성 가능해야 한다."""
    session, cid = db
    req = create_rate_request(session, cid, request_type="equipment_finance")
    assert req.request_type == "equipment_finance"
    assert req.scope_group is None
    assert req.current_grade is None
    assert req.target_grade is None
    assert req.status == "pending"


def test_equipment_finance_request_stores_custom_missing_summary(db):
    """K택소노미 리드 카드가 보내는 missing_summary(설비유형 + 전표 원문)가 그대로
    스냅샷에 저장된다 — 승인요청 큐에서 담당자가 어떤 설비인지 바로 알 수 있어야 함."""
    session, cid = db
    req = create_rate_request(
        session, cid, request_type="equipment_finance",
        missing_summary="태양광 설비 · 태양광 설비 설치",
    )
    assert req.missing_summary == "태양광 설비 · 태양광 설비 설치"


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


def test_owner_rate_candidate_endpoint_reflects_eligible_status(db, client):
    """이미 최고 등급이면 빈 목록이 아니라 "eligible" 상태 + 매칭 상품이 나온다
    (db/rate_products.py 도입 이후 — 이전엔 이 상태를 표현할 데이터가 없었다)."""
    session, cid = db
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, "도시가스", scope=1, emission=100.0, quantity=100)
        _add_classified_voucher(session, cid, m, "전기요금", scope=2, emission=50.0, quantity=100)

    res = client.get(f"/owner/{cid}/rate-candidate")
    assert res.status_code == 200
    candidates = res.json()["candidates"]
    assert len(candidates) == 2
    assert all(c["status"] == "eligible" for c in candidates)
    assert all(c["products"][0]["product_name"] == "ESG Grow-Up 특별대출" for c in candidates)


def test_owner_submits_rate_upgrade_request_successfully(db, client):
    """사장님이 등급 개선 후보 상태에서 요청을 만들면 스냅샷이 저장된다.

    관리자 승인요청 큐 UI(/admin/rate-requests)는 이번 스코프에서 제외됐다(팀원
    커밋 0caca0e) — 이 테스트는 owner 쪽 생성 결과만 검증한다."""
    session, cid = db
    _make_upgrade_candidate(session, cid)

    post_res = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    )
    assert post_res.status_code == 200, post_res.text
    assert post_res.json()["status"] == "pending"
    assert post_res.json()["scope_group"] == "scope_1"


def test_owner_submit_request_succeeds_when_already_at_best_achievable_grade(db, client):
    """이미 최고 등급이어도(eligible 상태, 매칭 상품 있음) 요청을 만들 수 있다 —
    더 이상 422가 아니다(db/rate_products.py 도입 이후)."""
    session, cid = db
    for m in range(1, 13):
        _add_classified_voucher(session, cid, m, "도시가스", scope=1, emission=100.0, quantity=100)

    res = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "rate_upgrade", "scope_group": "scope_1"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["matched_product_name"] == "ESG Grow-Up 특별대출"


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


# 관리자측 승인요청 큐 HTTP 엔드포인트(/admin/rate-requests, approve/reject)는 이번
# 스코프에서 제외됐다(팀원 커밋 0caca0e, "우대금리 후보·승인요청 큐... 제외한다").
# review_rate_request/list_rate_requests 자체(순수 함수, db/rate_approvals.py)는 여전히
# 살아있고 위 "db/rate_approvals.py 순수 로직" 섹션에서 직접 검증한다 — 없어진 건 HTTP
# 라우팅뿐이라 그 부분 테스트만 걷어낸다.


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
