"""업로드 문서(OCR/엑셀) → source_documents 적재 → vouchers 생성.

두 인입 경로(마이데이터 mock, 업로드)가 공유하는 최종 착지점. 여기서 만든
vouchers는 기존 classify_vouchers()/calc_engine.py 파이프라인을 무수정으로 탄다
(감탄 v1 1주차 아키텍처 결정 — docs 미반영, 채팅 계획 참고).
"""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.queries import resolve_institution_borrower
from db.document_extraction import extract_document
from db.hometax_excel_parser import parse_hometax_excel
from db.models import SourceDocument, Voucher

DOCUMENT_TYPE_TO_VOUCHER_SOURCE = {
    "tax_invoice": "tax_invoice",
    "electric_bill": "electric_bill",
    "gas_bill": "gas_bill",
}


class DuplicateDocumentError(ValueError):
    """동일 기업이 같은 파일을 다시 올렸을 때 — source_documents.file_hash 중복방지."""


class MissingInstitutionAttributionError(ValueError):
    """기업이 아직 어느 금융기관에도 백필(0006 마이그레이션)되지 않은 경우.

    source_documents.financial_institution_id는 NOT NULL이라 여기서 명확히
    막지 않으면 DB IntegrityError로 훨씬 알아보기 어렵게 실패한다."""


def _file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _parse_issue_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _existing_document(session: Session, company_id: int, file_hash: str) -> SourceDocument | None:
    stmt = select(SourceDocument).where(
        SourceDocument.company_id == company_id,
        SourceDocument.file_hash == file_hash,
    )
    return session.execute(stmt).scalars().first()


def ingest_uploaded_document(
    session: Session,
    company_id: int,
    file_bytes: bytes,
    filename: str,
    document_type: str,
    mode: str = "ocr",
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """업로드 1건 처리 → {"source_document_id", "vouchers_created"} 반환.

    mode="excel"은 document_type="tax_invoice"에서만 의미가 있다(여러 행 → 여러
    voucher). 그 외에는 항상 OCR mock 1건 → voucher 1건.
    """
    if document_type not in DOCUMENT_TYPE_TO_VOUCHER_SOURCE:
        raise ValueError(f"알 수 없는 document_type: {document_type}")

    file_hash = _file_hash(file_bytes)
    if _existing_document(session, company_id, file_hash) is not None:
        raise DuplicateDocumentError("이미 업로드된 파일입니다")

    ib = resolve_institution_borrower(session, company_id)
    if ib is None:
        raise MissingInstitutionAttributionError(
            f"company {company_id}는 아직 금융기관에 귀속되지 않았습니다 (institution_borrowers 없음)"
        )
    financial_institution_id, institution_borrower_id = ib

    if document_type == "tax_invoice" and mode == "excel":
        rows = parse_hometax_excel(file_bytes)
        extracted: dict = {"rows": rows}
        source_system = "upload:excel"
    else:
        if year is None or month is None:
            raise ValueError("OCR 업로드는 year/month가 필요합니다")
        row = extract_document(file_bytes, document_type, year=year, month=month)
        rows = [row]
        extracted = row
        source_system = "upload:ocr"

    doc = SourceDocument(
        financial_institution_id=financial_institution_id,
        company_id=company_id,
        document_type=document_type,
        source_system=source_system,
        original_filename=filename,
        file_hash=file_hash,
        extracted_json=extracted,
        verification_status="unverified",
    )
    session.add(doc)
    session.flush()  # doc.id 확보

    voucher_source = DOCUMENT_TYPE_TO_VOUCHER_SOURCE[document_type]
    created: list[Voucher] = []
    for row in rows:
        raw = {**row, "source_document_id": doc.id}
        v = Voucher(
            company_id=company_id,
            source=voucher_source,
            year=row["year"],
            month=row["month"],
            issue_date=_parse_issue_date(row.get("issue_date")),
            supplier_name=row.get("supplier_name"),
            item_description=row.get("item_description"),
            supply_amount_krw=row.get("supply_amount_krw"),
            raw_json=raw,
            financial_institution_id=financial_institution_id,
            institution_borrower_id=institution_borrower_id,
        )
        session.add(v)
        created.append(v)

    session.commit()
    return {"source_document_id": doc.id, "vouchers_created": len(created)}
