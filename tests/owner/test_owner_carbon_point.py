"""§9.1 탄소중립포인트 API — 프론트 fixture 교체 대상 엔드포인트 4종.

핵심 검증축:
  - 응답 필드명·타입이 프론트 `CarbonPointEligibility`·`CarbonPointDraft`와 같다
    (fixture를 이 API로 바꿀 때 컴포넌트를 안 고치는 게 목적).
  - 제조업은 감축률을 아예 계산하지 않는다(제도상 원천 제외).
  - 미달 기업은 초안 미리보기는 받지만 DB 레코드가 안 생긴다.
  - 다른 기업 소유 초안은 404(테넌트 경계).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import (
    Base,
    CarbonNeutralPointApplication,
    Classification,
    Company,
    FinancialInstitution,
    SourceDocument,
    Voucher,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        inst = FinancialInstitution(name="감탄 데모", reporting_currency="KRW", tenant_key="demo")
        cafe = Company(name="동성로카페", industry_code="I561", region="대구 중구")
        factory = Company(name="대경부품", industry_code="C251", region="경북 경산")
        session.add_all([inst, cafe, factory])
        session.commit()
        yield session, inst, cafe, factory


@pytest.fixture()
def client(db):
    session, *_ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _bill(session, inst, company, year, month, kwh, contract_class="commercial"):
    session.add(SourceDocument(
        financial_institution_id=inst.id, company_id=company.id,
        document_type="electric_bill", year=year, month=month,
        contract_type="일반용(을)", contract_type_class=contract_class,
        extracted_json={"customer_number": "0355-7712-90"},
    ))
    v = Voucher(company_id=company.id, source="kepco", year=year, month=month,
                item_description="전기요금", supply_amount_krw=100_000)
    session.add(v)
    session.flush()
    session.add(Classification(voucher_id=v.id, scope=2, category="간접배출", fuel_type="전기",
                               activity_amount=kwh, activity_unit="kWh", status="auto"))
    session.commit()


def _history(session, inst, company, *, target_kwh=90.0, contract_class="commercial"):
    for year in (2024, 2025):
        for m in range(1, 13):
            _bill(session, inst, company, year, m, 100.0, contract_class)
    for m in range(1, 7):
        _bill(session, inst, company, 2026, m, target_kwh, contract_class)


# ── GET eligibility ────────────────────────────────────────────────────────


def test_eligibility_response_shape(client, db):
    session, inst, cafe, _ = db
    _history(session, inst, cafe)

    r = client.get(f"/owner/{cafe.id}/carbon-point/eligibility?target_year=2026")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "business_scale_hint", "baseline_year", "target_year",
        "reduction_rate_pct", "eligible", "missing_data",
    }
    assert body["business_scale_hint"] == "소상공인/상업시설"
    assert body["reduction_rate_pct"] == pytest.approx(10.0)
    assert body["eligible"] is True
    assert isinstance(body["missing_data"], list)


def test_eligibility_manufacturing_gets_null_rate(client, db):
    """산업용 전기는 원천 제외 — 90% 감축이어도 계산하지 않는다."""
    session, inst, _, factory = db
    _history(session, inst, factory, target_kwh=10.0, contract_class="industrial")

    body = client.get(f"/owner/{factory.id}/carbon-point/eligibility?target_year=2026").json()
    assert body["business_scale_hint"] == "제조업/산업체"
    assert body["reduction_rate_pct"] is None
    assert body["eligible"] is False


def test_eligibility_unknown_contract_type(client, db):
    session, inst, cafe, _ = db
    _bill(session, inst, cafe, 2026, 1, 90.0, contract_class=None)

    body = client.get(f"/owner/{cafe.id}/carbon-point/eligibility?target_year=2026").json()
    assert body["business_scale_hint"] == "미확인"
    assert any("계약종별" in m for m in body["missing_data"])


def test_eligibility_defaults_to_current_year(client, db):
    """target_year 생략 시 올해로 본다 — 프론트가 연도를 안 넘겨도 동작해야 한다."""
    session, inst, cafe, _ = db
    _bill(session, inst, cafe, 2026, 1, 90.0)

    r = client.get(f"/owner/{cafe.id}/carbon-point/eligibility")
    assert r.status_code == 200
    assert "target_year" in r.json()


# ── POST applications ──────────────────────────────────────────────────────


def test_create_application_returns_draft_contract(client, db):
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    session.add(SourceDocument(
        financial_institution_id=inst.id, company_id=cafe.id,
        document_type="business_registration",
        extracted_json={"business_registration_no": "211-81-10011", "company_name": "동성로카페",
                        "representative": "김○○", "site_addr": "대구 중구 ○○로 11"},
    ))
    session.commit()

    body = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()
    assert set(body) == {"application_id", "status", "fields", "applicant_fields",
                         "remaining_fields", "draft_document_url"}
    assert body["status"] == "draft"
    assert body["draft_document_url"] is None
    assert body["application_id"] is not None

    by_label = {f["label"]: f["value"] for f in body["fields"]}
    assert by_label["상호(법인명)"] == "동성로카페"
    assert by_label["사업장 주소"] == "대구 중구 ○○로 11"
    # 감축률·사용량은 `fields`에 없다(2026-08-25) — 서식에 기재란이 없어서다. 값은 DB
    # 레코드에만 남고, 자격 판정 응답(GET .../carbon-point)이 화면에 보여준다.
    assert not [f for f in body["fields"] if "감축률" in f["label"] or "사용량" in f["label"]]
    row = session.query(CarbonNeutralPointApplication).one()
    assert row.reduction_rate_pct == 10.0


def test_create_application_not_persisted_when_not_eligible(client, db):
    """미달 기업도 미리보기는 받지만 DB에는 안 쌓인다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe, target_kwh=99.0)

    body = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()
    assert body["application_id"] is None
    assert body["fields"]
    assert session.query(CarbonNeutralPointApplication).count() == 0


# ── GET / PATCH applications/{id} ──────────────────────────────────────────


def test_get_application(client, db):
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()["application_id"]

    body = client.get(f"/owner/{cafe.id}/carbon-point/applications/{app_id}").json()
    assert body["application_id"] == app_id
    assert body["status"] == "draft"
    assert body["eligible"] is True
    assert body["baseline_usage_json"] == {"electricity_kwh": 600.0}


def test_get_application_of_other_company_is_404(client, db):
    """테넌트 경계 — 남의 초안을 id만 알면 볼 수 있으면 안 된다."""
    session, inst, cafe, factory = db
    _history(session, inst, cafe)
    app_id = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()["application_id"]

    assert client.get(f"/owner/{factory.id}/carbon-point/applications/{app_id}").status_code == 404


def test_patch_application_status(client, db):
    """제출 이후 상태는 사장님이 직접 갱신한다 — 감탄은 draft까지만 책임진다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()["application_id"]

    r = client.patch(f"/owner/{cafe.id}/carbon-point/applications/{app_id}",
                     json={"status": "submitted"})
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"
    assert session.get(CarbonNeutralPointApplication, app_id).status == "submitted"


def test_patch_rejects_draft_rollback(client, db):
    """draft로 되돌리는 건 제출 사실을 지우는 셈이라 허용하지 않는다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()["application_id"]

    r = client.patch(f"/owner/{cafe.id}/carbon-point/applications/{app_id}", json={"status": "draft"})
    assert r.status_code == 422


def test_patch_application_of_other_company_is_404(client, db):
    session, inst, cafe, factory = db
    _history(session, inst, cafe)
    app_id = client.post(f"/owner/{cafe.id}/carbon-point/applications?target_year=2026").json()["application_id"]

    r = client.patch(f"/owner/{factory.id}/carbon-point/applications/{app_id}",
                     json={"status": "approved"})
    assert r.status_code == 404


# ── PATCH applications/{id}/applicant-input (4단계 위저드 3단계) ────────────
#
# 검증축: 부분 저장이 되고, 알 수 없는 필드명·닫힌 어휘 위반은 500이 아니라 422로 드러나고,
# 테넌트 경계와 제출 이력 보호가 지켜진다.


def _draft_id(client, company_id: int) -> int:
    return client.post(
        f"/owner/{company_id}/carbon-point/applications?target_year=2026"
    ).json()["application_id"]


def test_patch_applicant_input_saves_and_reports_missing(client, db):
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)

    r = client.patch(
        f"/owner/{cafe.id}/carbon-point/applications/{app_id}/applicant-input",
        json={"values": {"applicant_phone": "01011112222", "incentive_type": "cash"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["application_id"] == app_id
    assert body["values"]["applicant_phone"] == "01011112222"
    # 필수 미입력은 에러가 아니라 목록 — 화면이 "다음" 버튼을 막는 근거다.
    assert "portal_id" in body["missing_required"]
    assert "applicant_phone" not in body["missing_required"]
    assert session.get(CarbonNeutralPointApplication, app_id).applicant_phone == "01011112222"


def test_patch_applicant_input_rejects_unknown_field(client, db):
    """오타 난 필드명이 조용히 버려지면 "저장했는데 값이 안 남는" 증상으로만 드러난다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)

    r = client.patch(
        f"/owner/{cafe.id}/carbon-point/applications/{app_id}/applicant-input",
        json={"values": {"applicant_phne": "01011112222"}},
    )
    assert r.status_code == 422


def test_patch_applicant_input_rejects_unknown_incentive_type(client, db):
    """DB CHECK 위반을 500으로 흘리지 않고 422로 돌려준다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)

    r = client.patch(
        f"/owner/{cafe.id}/carbon-point/applications/{app_id}/applicant-input",
        json={"values": {"incentive_type": "local_currency"}},
    )
    assert r.status_code == 422


def test_patch_applicant_input_rejects_bad_date(client, db):
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)

    r = client.patch(
        f"/owner/{cafe.id}/carbon-point/applications/{app_id}/applicant-input",
        json={"values": {"business_open_date": "2019-13-99"}},
    )
    assert r.status_code == 422


def test_patch_applicant_input_of_other_company_is_404(client, db):
    """테넌트 경계 — id만 알면 남의 신청서에 연락처를 써넣을 수 있으면 안 된다."""
    session, inst, cafe, factory = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)

    r = client.patch(
        f"/owner/{factory.id}/carbon-point/applications/{app_id}/applicant-input",
        json={"values": {"applicant_phone": "01011112222"}},
    )
    assert r.status_code == 404


def test_patch_applicant_input_on_submitted_is_409(client, db):
    """제출한 신청서는 수정하지 않는다 — 실제로 낸 내용과 기록이 어긋난다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)
    client.patch(f"/owner/{cafe.id}/carbon-point/applications/{app_id}",
                 json={"status": "submitted"})

    r = client.patch(
        f"/owner/{cafe.id}/carbon-point/applications/{app_id}/applicant-input",
        json={"values": {"applicant_phone": "01011112222"}},
    )
    assert r.status_code == 409


def test_get_application_returns_applicant_input(client, db):
    """위저드를 다시 열었을 때 어디까지 썼는지 복원할 수 있어야 한다."""
    session, inst, cafe, _ = db
    _history(session, inst, cafe)
    app_id = _draft_id(client, cafe.id)
    client.patch(f"/owner/{cafe.id}/carbon-point/applications/{app_id}/applicant-input",
                 json={"values": {"portal_id": "cafe0001"}})

    body = client.get(f"/owner/{cafe.id}/carbon-point/applications/{app_id}").json()
    assert body["applicant_input"]["portal_id"] == "cafe0001"
    assert "portal_id" not in body["missing_required"]
