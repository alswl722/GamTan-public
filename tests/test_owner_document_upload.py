"""POST /owner/{company_id}/documents/upload — 라우터 레벨(TestClient) 검증."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Company, FinancialInstitution, InstitutionBorrower


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
        inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
        session.add(inst)
        session.commit()
        session.add(InstitutionBorrower(
            financial_institution_id=inst.id, company_id=company.id,
            external_customer_id="demo-company-1", consent_status="active",
        ))
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ocr_upload_electric_bill_succeeds(db, client):
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("고지서.jpg", b"fake-bytes", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr", "year": "2025", "month": "3"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["vouchers_created"] == 1


def test_excel_upload_tax_invoice_succeeds(db, client):
    _, company_id = db
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["작성일자", "상호", "품목명", "공급가액"])
    ws.append(["2025-01-18", "구미석유", "경유 외 1종", 654000])
    ws.append(["2025-02-15", "구미석유", "유류대금", 612000])
    buf = io.BytesIO()
    wb.save(buf)

    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("hometax.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"document_type": "tax_invoice", "mode": "excel"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["vouchers_created"] == 2


def test_duplicate_upload_returns_409(db, client):
    _, company_id = db
    files = {"file": ("고지서.jpg", b"same-bytes", "image/jpeg")}
    data = {"document_type": "gas_bill", "mode": "ocr", "year": "2025", "month": "4"}
    first = client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    assert first.status_code == 200
    second = client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    assert second.status_code == 409


def test_invalid_document_type_returns_400(db, client):
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "not_a_real_type", "mode": "ocr", "year": "2025", "month": "1"},
    )
    assert res.status_code == 400


def test_excel_mode_rejected_for_non_tax_invoice(db, client):
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.xlsx", b"x", "application/octet-stream")},
        data={"document_type": "electric_bill", "mode": "excel"},
    )
    assert res.status_code == 400


def test_ocr_without_year_month_returns_400(db, client):
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert res.status_code == 400
