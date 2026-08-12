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


def test_duplicate_upload_is_recorded_as_quality_issue(db, client):
    """실패한 업로드는 품질 이슈 로그(DocumentIngestionFailure)에 기록된다
    (v1 Tier 2 — 이전엔 HTTP 응답으로만 실패가 전달되고 DB엔 아무 것도 안 남았다)."""
    from db.models import DocumentIngestionFailure

    session, company_id = db
    files = {"file": ("고지서.jpg", b"same-bytes-2", "image/jpeg")}
    data = {"document_type": "gas_bill", "mode": "ocr", "year": "2025", "month": "6"}
    client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)

    failures = session.query(DocumentIngestionFailure).filter_by(company_id=company_id).all()
    assert len(failures) == 1
    assert failures[0].failure_reason == "duplicate"


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


def test_ocr_non_pdf_without_year_month_returns_422(db, client):
    """year/month는 더 이상 필수가 아니다(문서 자체에서 날짜를 읽는다) — 대신
    PDF가 아니라 실 추출도 안 되고 폴백용 year/month도 없으면 422로 명확히 실패한다."""
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert res.status_code == 422


def test_ocr_non_pdf_with_year_month_falls_back_to_synthetic(db, client):
    """year/month가 주어지면(개발 편의) 임의 파일도 여전히 합성 mock으로 통과한다."""
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr", "year": "2025", "month": "5"},
    )
    assert res.status_code == 200, res.text
