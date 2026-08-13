"""api/document_ingestion.py — 업로드(OCR/엑셀) → source_documents → vouchers 경로 검증."""
import io
from datetime import date

import openpyxl
import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.document_ingestion import (
    DuplicateDocumentError,
    MissingInstitutionAttributionError,
    ingest_uploaded_document,
)
from db.models import Base, Company, FinancialInstitution, InstitutionBorrower, SourceDocument, Voucher

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _minimal_pdf(lines: list[str]) -> bytes:
    """합성 mock이 사라졌으므로 실 파싱이 되는 최소 텍스트 PDF가 필요하다
    (tests/test_document_extraction.py와 동일 패턴)."""
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
        f"청구월: 2025-{month} 계약종별: 산업용(을) 고압A",
        f"사용량(kWh) {quantity}",
        f"청구금액(원) {amount}",
    ])


def _gas_bill_pdf(*, month="04", amount=800_000, quantity=800) -> bytes:
    return _minimal_pdf([
        "도시가스 요금고지서",
        f"사용월: 2025-{month}",
        f"사용량(m³) {quantity}",
        f"청구금액(원) {amount}",
    ])


def _tax_invoice_pdf(*, day="07-10", supplier="구미석유", amount=420_000) -> bytes:
    return _minimal_pdf([
        "전자세금계산서",
        f"작성일자: 2025-{day}",
        f"공급자: {supplier}",
        f"경유 L 300L 1,400 {amount:,}",
    ])


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.fixture()
def db_with_institution(db):
    session, company_id = db
    inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
    session.add(inst)
    session.commit()
    ib = InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company_id,
        external_customer_id="demo-company-1", consent_status="active",
    )
    session.add(ib)
    session.commit()
    return session, company_id, inst.id, ib.id


def _xlsx_bytes(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["작성일자", "상호", "품목명", "공급가액"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_without_institution_backfill_raises_clear_error(db):
    """source_documents.financial_institution_id는 NOT NULL — 백필 안 된 기업은
    DB IntegrityError가 아니라 명확한 에러로 먼저 막혀야 한다(기관 귀속 확인이
    문서 파싱보다 먼저 일어나므로 파일 내용은 아무거나 줘도 된다)."""
    session, company_id = db
    with pytest.raises(MissingInstitutionAttributionError):
        ingest_uploaded_document(
            session, company_id, b"x", "a.jpg", "gas_bill", mode="ocr",
        )


def test_ocr_upload_creates_one_source_document_and_one_voucher(db_with_institution):
    session, company_id, _inst_id, _ib_id = db_with_institution
    result = ingest_uploaded_document(
        session, company_id, _electric_bill_pdf(), "3월전기고지서.pdf",
        "electric_bill", mode="ocr",
    )
    assert result["vouchers_created"] == 1

    docs = session.execute(select(SourceDocument)).scalars().all()
    assert len(docs) == 1
    assert docs[0].document_type == "electric_bill"
    assert docs[0].source_system == "upload:ocr"

    vouchers = session.execute(select(Voucher)).scalars().all()
    assert len(vouchers) == 1
    assert vouchers[0].source == "electric_bill"
    assert vouchers[0].month == 3
    assert vouchers[0].raw_json["source_document_id"] == docs[0].id
    assert vouchers[0].raw_json["quantity_unit"] == "kWh"


def test_excel_upload_creates_one_source_document_and_multiple_vouchers(db_with_institution):
    session, company_id, _inst_id, _ib_id = db_with_institution
    xlsx = _xlsx_bytes([
        (date(2025, 1, 18), "구미석유", "경유 외 1종", 654000),
        (date(2025, 2, 15), "구미석유", "유류대금", 612000),
    ])
    result = ingest_uploaded_document(
        session, company_id, xlsx, "hometax_export.xlsx", "tax_invoice", mode="excel",
    )
    assert result["vouchers_created"] == 2

    vouchers = session.execute(select(Voucher)).scalars().all()
    assert {v.month for v in vouchers} == {1, 2}
    assert all(v.source == "tax_invoice" for v in vouchers)


def test_duplicate_file_upload_is_rejected(db_with_institution):
    session, company_id, _inst_id, _ib_id = db_with_institution
    content = _gas_bill_pdf()
    ingest_uploaded_document(session, company_id, content, "a.pdf", "gas_bill", mode="ocr")
    with pytest.raises(DuplicateDocumentError):
        ingest_uploaded_document(session, company_id, content, "a.pdf", "gas_bill", mode="ocr")


def test_db_constraint_blocks_duplicate_even_if_app_check_is_bypassed(db_with_institution):
    """앱 레벨 SELECT-then-INSERT 체크(_existing_document)는 동시 업로드 레이스를
    못 막는다 — 그 체크를 완전히 우회해 직접 INSERT해도 DB 유니크 제약(0008)이
    최종적으로 막아야 한다. IntegrityError → DuplicateDocumentError로 변환되는지도 확인."""
    from sqlalchemy.exc import IntegrityError

    from db.models import SourceDocument

    session, company_id, inst_id, _ib_id = db_with_institution
    session.add(SourceDocument(
        financial_institution_id=inst_id, company_id=company_id,
        document_type="gas_bill", file_hash="race-condition-hash",
    ))
    session.commit()

    # 앱 함수가 아니라 모델 레벨에서 직접 같은 (company_id, file_hash)를 다시 넣어도 막힌다.
    session.add(SourceDocument(
        financial_institution_id=inst_id, company_id=company_id,
        document_type="gas_bill", file_hash="race-condition-hash",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_institution_attribution_is_filled_when_backfilled(db_with_institution):
    session, company_id, inst_id, ib_id = db_with_institution
    ingest_uploaded_document(
        session, company_id, _tax_invoice_pdf(), "invoice.pdf",
        "tax_invoice", mode="ocr",
    )
    voucher = session.execute(select(Voucher)).scalars().first()
    assert voucher.financial_institution_id == inst_id
    assert voucher.institution_borrower_id == ib_id

    doc = session.execute(select(SourceDocument)).scalars().first()
    assert doc.financial_institution_id == inst_id
