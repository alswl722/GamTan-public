"""POST /owner/{company_id}/documents/upload — 라우터 레벨(TestClient) 검증."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Company, FinancialInstitution, InstitutionBorrower

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _minimal_pdf(lines: list[str]) -> bytes:
    """테스트 전용 — 합성 mock이 사라졌으므로 OCR 성공 케이스는 실제로 파싱되는
    최소 텍스트 PDF가 있어야 한다(tests/test_document_extraction.py와 동일 패턴)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    y = 700
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def _electric_bill_pdf(*, month="03", amount=987_654, quantity=1234) -> bytes:
    return _minimal_pdf([
        "전기요금 고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        f"청구월: 2025-{month} 계약종별: 산업용(을) 고압A",
        f"사용량(kWh) {quantity}",
        f"청구금액(원) {amount}",
    ])


def _gas_bill_pdf(*, month="04", amount=555_555, quantity=321) -> bytes:
    return _minimal_pdf([
        "도시가스 요금고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        f"사용월: 2025-{month}",
        f"사용량(m³) {quantity}",
        f"청구금액(원) {amount}",
    ])


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
        files={"file": ("고지서.pdf", _electric_bill_pdf(), "application/pdf")},
        data={"document_type": "electric_bill", "mode": "ocr"},
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
    files = {"file": ("고지서.pdf", _gas_bill_pdf(month="04"), "application/pdf")}
    data = {"document_type": "gas_bill", "mode": "ocr"}
    first = client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    assert first.status_code == 200, first.text
    second = client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    assert second.status_code == 409


def test_duplicate_upload_is_recorded_as_quality_issue(db, client):
    """실패한 업로드는 품질 이슈 로그(DocumentIngestionFailure)에 기록된다
    (v1 Tier 2 — 이전엔 HTTP 응답으로만 실패가 전달되고 DB엔 아무 것도 안 남았다)."""
    from db.models import DocumentIngestionFailure

    session, company_id = db
    files = {"file": ("고지서.pdf", _gas_bill_pdf(month="06"), "application/pdf")}
    data = {"document_type": "gas_bill", "mode": "ocr"}
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
        data={"document_type": "not_a_real_type", "mode": "ocr"},
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


def test_ocr_non_pdf_returns_422(db, client):
    """PDF가 아니거나 실 추출이 안 되는 파일은 합성값으로 가리지 않고 422로
    명확히 실패한다(실패 가시성 원칙, 합성 mock 폴백 없음)."""
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert res.status_code == 422


def test_ocr_pdf_with_unrecognized_format_returns_422(db, client):
    """PDF는 맞지만 알려진 서식이 아니면(제목 줄 불일치 등) 값을 지어내지 않고
    422로 실패한다 — 예전엔 year/month가 있으면 합성값으로 통과했었다."""
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.pdf", _minimal_pdf(["아무 문서", "관련 없는 내용"]), "application/pdf")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert res.status_code == 422
