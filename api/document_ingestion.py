"""업로드 문서(OCR/엑셀) → source_documents 적재 → vouchers 생성.

두 인입 경로(마이데이터 mock, 업로드)가 공유하는 최종 착지점. 여기서 만든
vouchers는 기존 classify_vouchers()/calc_engine.py 파이프라인을 무수정으로 탄다
(감탄 v1 1주차 아키텍처 결정 — docs 미반영, 채팅 계획 참고).
"""
import hashlib
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.queries import resolve_institution_borrower
from db.document_extraction import extract_document
from db.hometax_excel_parser import parse_hometax_excel
from db.models import SourceDocument, Voucher

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
UPLOADS_DIR = os.path.join(REPO_ROOT, "data", "uploads")

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


def _save_file(company_id: int, file_hash: str, filename: str, file_bytes: bytes) -> str:
    """data/uploads/{company_id}/ 아래 원본 저장, DB엔 저장소 루트 기준 상대경로만 기록.

    file_hash를 파일명 접두어로 넣어 동일 파일 재업로드 시 충돌을 피하고, 디버깅 시
    파일과 DB 레코드를 서로 대조하기 쉽게 한다.
    """
    company_dir = os.path.join(UPLOADS_DIR, str(company_id))
    os.makedirs(company_dir, exist_ok=True)
    abs_path = os.path.join(company_dir, f"{file_hash}_{filename}")
    with open(abs_path, "wb") as f:
        f.write(file_bytes)
    return os.path.relpath(abs_path, REPO_ROOT)


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
) -> dict:
    """업로드 1건 처리 → {"source_document_id", "vouchers_created"} 반환.

    mode="excel"은 document_type="tax_invoice"에서만 의미가 있다(여러 행 → 여러
    voucher). 그 외에는 항상 PDF 실 추출 1건 → voucher 1건 — 실패하면 값을
    지어내지 않고 DocumentParseError를 그대로 던진다(db/document_extraction.py).
    """
    if document_type not in DOCUMENT_TYPE_TO_VOUCHER_SOURCE:
        raise ValueError(f"알 수 없는 document_type: {document_type}")

    file_hash = _file_hash(file_bytes)
    if _existing_document(session, company_id, file_hash) is not None:
        raise DuplicateDocumentError("이미 업로드된 파일입니다")

    file_path = _save_file(company_id, file_hash, filename, file_bytes)

    ib = resolve_institution_borrower(session, company_id)
    if ib is None:
        raise MissingInstitutionAttributionError(
            f"company {company_id}는 아직 금융기관에 귀속되지 않았습니다 (institution_borrowers 없음)"
        )
    financial_institution_id, institution_borrower_id = ib

    skipped_rows = 0
    if document_type == "tax_invoice" and mode == "excel":
        rows, skipped_rows = parse_hometax_excel(file_bytes)
        extracted: dict = {"rows": rows, "skipped_rows": skipped_rows}
        source_system = "upload:excel"
    else:
        row = extract_document(file_bytes, document_type)
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
        file_path=file_path,
        extracted_json=extracted,
        verification_status="unverified",
    )
    voucher_source = DOCUMENT_TYPE_TO_VOUCHER_SOURCE[document_type]
    created: list[Voucher] = []
    try:
        # doc 추가부터 commit까지 통째로 감싼다 — 중간의 session.flush()가 doc의
        # file_hash 유니크 제약 위반을 이 시점에 먼저 던질 수 있어(레이스), try
        # 블록을 마지막 commit()에만 좁게 걸면 그 순간의 IntegrityError를 놓친다.
        session.add(doc)
        session.flush()  # doc.id 확보 — voucher들의 source_document_id로 필요

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
    except IntegrityError as e:
        # 앞의 _existing_document() 체크는 SELECT-then-INSERT라 동시 업로드(더블클릭·
        # 재시도)가 둘 다 체크를 통과할 수 있다 — DB 유니크 제약(0008)이 최종 방어선.
        session.rollback()
        raise DuplicateDocumentError("이미 업로드된 파일입니다") from e

    result = {
        "source_document_id": doc.id,
        "vouchers_created": len(created),
        "skipped_rows": skipped_rows,
    }
    if mode == "ocr":
        # 프론트가 더 이상 업로드 전에 월을 묻지 않으므로, 문서에서 실제로 읽어낸
        # year/month를 응답에 실어 보내 업로드 완료 후 "1월 접수됨" 같은 표시를 만든다.
        result["year"] = rows[0]["year"]
        result["month"] = rows[0]["month"]
    return result
