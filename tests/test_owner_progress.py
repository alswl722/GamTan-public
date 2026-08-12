"""api/queries.py::get_owner_progress — 5단계 위저드 실제 완료 상태 검증.

핵심 축: 브라우저 세션이 아니라 DB에 실제로 쌓인 것만 본다 — 홈 화면 진행바·
위저드 이어하기가 새로고침·다른 기기에서도 같은 값을 봐야 한다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from api.queries import get_owner_progress
from db.models import (
    Base,
    Classification,
    Company,
    FinancialInstitution,
    SourceDocument,
    TraceLog,
    Voucher,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
        session.add(inst)
        session.commit()
        company = Company(name="테스트기업", industry_code="C251")
        session.add(company)
        session.commit()
        yield session, company.id, inst.id


@pytest.fixture()
def client(db):
    session, _, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mydata_doc(session, cid, inst_id, doc_type="business_registration"):
    session.add(SourceDocument(
        financial_institution_id=inst_id, company_id=cid, document_type=doc_type,
        source_system="mydata:business-registration", file_hash=f"h-{doc_type}",
    ))
    session.commit()


def _uploaded_doc(session, cid, inst_id, doc_type):
    session.add(SourceDocument(
        financial_institution_id=inst_id, company_id=cid, document_type=doc_type,
        source_system="upload:ocr", file_hash=f"h-upload-{doc_type}-{cid}",
    ))
    session.commit()


def _voucher(session, cid, month, fuel="전기", classify=True, status="auto"):
    v = Voucher(
        company_id=cid, source="hometax", year=2025, month=month,
        item_description=fuel, supply_amount_krw=100_000, raw_json={},
    )
    session.add(v)
    session.flush()
    if classify:
        session.add(Classification(
            voucher_id=v.id, scope=1, category="고정연소", fuel_type=fuel,
            amount_krw=100_000, emission_co2e=100.0, confidence=0.9,
            evidence="테스트", method="rule", status=status,
        ))
    session.commit()
    return v.id


def test_fresh_company_has_all_steps_incomplete(db):
    session, cid, _ = db
    result = get_owner_progress(session, cid)
    assert result["steps"] == {
        "consent": False, "upload": False, "trace": False, "classify": False, "report": False,
    }
    assert result["current_step"] == 0


def test_consent_done_when_any_mydata_document_exists(db):
    session, cid, inst_id = db
    _mydata_doc(session, cid, inst_id)
    result = get_owner_progress(session, cid)
    assert result["steps"]["consent"] is True
    assert result["current_step"] == 1  # 다음은 upload


def test_upload_incomplete_without_fuel_types_json(db):
    """연료 체크 자체를 안 했으면 판정 기준이 없어 미완료로 본다."""
    session, cid, inst_id = db
    _uploaded_doc(session, cid, inst_id, "tax_invoice")
    _uploaded_doc(session, cid, inst_id, "electric_bill")
    result = get_owner_progress(session, cid)
    assert result["steps"]["upload"] is False


def test_upload_done_only_when_all_required_types_present(db):
    session, cid, inst_id = db
    company = session.get(Company, cid)
    company.fuel_types_json = {
        "diesel": True, "gasoline": False, "city_gas": False, "lpg": "no", "electricity": True,
    }
    session.commit()
    # tax_invoice(경유 선택이라 required) + electric_bill(항상 required) 둘 다 필요.
    _uploaded_doc(session, cid, inst_id, "electric_bill")
    assert get_owner_progress(session, cid)["steps"]["upload"] is False

    _uploaded_doc(session, cid, inst_id, "tax_invoice")
    assert get_owner_progress(session, cid)["steps"]["upload"] is True


def test_gas_bill_not_required_when_city_gas_unchecked(db):
    session, cid, inst_id = db
    company = session.get(Company, cid)
    company.fuel_types_json = {
        "diesel": False, "gasoline": False, "city_gas": False, "lpg": "no", "electricity": True,
    }
    session.commit()
    # 전기만 체크 — 세금계산서는 선택, 전기고지서만 있으면 충분
    _uploaded_doc(session, cid, inst_id, "electric_bill")
    assert get_owner_progress(session, cid)["steps"]["upload"] is True


def test_trace_done_when_trace_log_exists(db):
    session, cid, _ = db
    session.add(TraceLog(company_id=cid, session_id="s1", step_type="계획", message="테스트"))
    session.commit()
    assert get_owner_progress(session, cid)["steps"]["trace"] is True


def test_classify_done_requires_every_voucher_classified(db):
    session, cid, _ = db
    _voucher(session, cid, 1, classify=True)
    _voucher(session, cid, 2, classify=False)
    result = get_owner_progress(session, cid)
    assert result["steps"]["classify"] is False
    assert result["steps"]["report"] is False

    _voucher_id = _voucher(session, cid, 2, classify=True)  # 2월치를 새로 분류 완료된 걸로 추가
    result2 = get_owner_progress(session, cid)
    # 여전히 미분류(1건, classify=False)가 하나 남아있어 전체 완료는 아님
    assert result2["steps"]["classify"] is False


def test_classify_and_report_done_when_all_vouchers_classified(db):
    session, cid, _ = db
    _voucher(session, cid, 1, classify=True)
    _voucher(session, cid, 2, classify=True)
    result = get_owner_progress(session, cid)
    assert result["steps"]["classify"] is True
    assert result["steps"]["report"] is True


def test_current_step_is_last_index_when_everything_done(db):
    session, cid, inst_id = db
    _mydata_doc(session, cid, inst_id)
    company = session.get(Company, cid)
    company.fuel_types_json = {
        "diesel": False, "gasoline": False, "city_gas": False, "lpg": "no", "electricity": True,
    }
    session.commit()
    _uploaded_doc(session, cid, inst_id, "electric_bill")
    session.add(TraceLog(company_id=cid, session_id="s1", step_type="계획", message="테스트"))
    session.commit()
    _voucher(session, cid, 1, classify=True)

    result = get_owner_progress(session, cid)
    assert all(result["steps"].values())
    assert result["current_step"] == 4


def test_progress_endpoint_returns_real_state(db, client):
    session, cid, inst_id = db
    _mydata_doc(session, cid, inst_id)
    res = client.get(f"/owner/{cid}/progress")
    assert res.status_code == 200
    body = res.json()
    assert body["steps"]["consent"] is True
    assert body["current_step"] == 1


def test_progress_endpoint_404_for_unknown_company(client):
    res = client.get("/owner/99999/progress")
    assert res.status_code == 404
