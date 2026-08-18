"""업로드 문서(OCR/엑셀) → source_documents 적재 → vouchers 생성.

두 인입 경로(마이데이터 mock, 업로드)가 공유하는 최종 착지점. 여기서 만든
vouchers는 기존 classify_vouchers()/calc_engine.py 파이프라인을 무수정으로 탄다
(감탄 v1 1주차 아키텍처 결정 — docs 미반영, 채팅 계획 참고).

접수(create_upload_job, 동기·빠름)와 실제 추출(process_upload_job, 백그라운드)을
분리한다 — PaddleOCR 콜드 로딩(~28초)에 LLM 최후수단(Gemini 최대 20초×2회
재시도)까지 이어지면 90초를 넘길 수 있어(실측, web/lib/api.ts 주석), 그 요청을
그대로 사장님이 붙잡고 있게 하지 않기 위함(v1 2주차, docs 미반영·채팅 계획 참고).
"""
import hashlib
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.db import new_session
from api.queries import resolve_institution_borrower
from db.document.document_extraction import extract_document
from db.document.document_text_extractor import DOCUMENT_TYPE_LABEL, DocumentParseError
from db.hometax_excel_parser import HometaxExcelFormatError, parse_hometax_excel
from db.models import DocumentUploadJob, OwnerNotification, SourceDocument, Voucher
from db.quality_issues import record_ingestion_failure

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
UPLOADS_DIR = os.path.join(REPO_ROOT, "data", "uploads")

DOCUMENT_TYPE_TO_VOUCHER_SOURCE = {
    "tax_invoice": "tax_invoice",
    "electric_bill": "electric_bill",
    "gas_bill": "gas_bill",
}


class DuplicateDocumentError(ValueError):
    """동일 기업이 같은 파일을 다시 올렸거나, 그 파일이 이미 처리 중일 때."""


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


def _existing_processing_job(session: Session, company_id: int, file_hash: str) -> DocumentUploadJob | None:
    """같은 파일이 이미 처리 중인지 — 더블클릭·연타 제출로 같은 OCR을 두 번 태우지 않기 위한 방어선."""
    stmt = select(DocumentUploadJob).where(
        DocumentUploadJob.company_id == company_id,
        DocumentUploadJob.file_hash == file_hash,
        DocumentUploadJob.status == "processing",
    )
    return session.execute(stmt).scalars().first()


def create_upload_job(
    session: Session,
    company_id: int,
    file_bytes: bytes,
    filename: str,
    document_type: str | None,
    mode: str = "ocr",
) -> DocumentUploadJob:
    """업로드 접수 — 빠른 DB 체크·파일 저장만 동기로 수행하고 잡을 만들어 반환한다.

    무거운 추출(OCR/LLM)은 process_upload_job()이 백그라운드에서 이어받는다.
    중복·기관미귀속 검증은 실패 시 사용자가 즉시 알아야 하는 종류라(사실상 설정
    오류거나 명백한 재업로드) 여기서 동기로 판정해 예외를 그대로 던진다 — 라우터가
    지금처럼 409/422로 바로 응답한다.
    """
    if document_type is not None and document_type not in DOCUMENT_TYPE_TO_VOUCHER_SOURCE:
        raise ValueError(f"알 수 없는 document_type: {document_type}")

    file_hash = _file_hash(file_bytes)
    if _existing_document(session, company_id, file_hash) is not None:
        raise DuplicateDocumentError("이미 업로드된 파일입니다")
    if _existing_processing_job(session, company_id, file_hash) is not None:
        raise DuplicateDocumentError("이미 처리 중인 파일입니다")

    ib = resolve_institution_borrower(session, company_id)
    if ib is None:
        raise MissingInstitutionAttributionError(
            f"company {company_id}는 아직 금융기관에 귀속되지 않았습니다 (institution_borrowers 없음)"
        )

    file_path = _save_file(company_id, file_hash, filename, file_bytes)

    job = DocumentUploadJob(
        company_id=company_id,
        original_filename=filename,
        file_hash=file_hash,
        file_path=file_path,
        document_type_hint=document_type,
        mode=mode,
        status="processing",
    )
    session.add(job)
    session.commit()
    return job


def _fail_job(session: Session, job: DocumentUploadJob, *, failure_reason: str, detail: str) -> None:
    """실패 처리 공통 경로 — job 갱신 + 실패 이력 + 사장님 알림(실패 가시성 원칙, CLAUDE.md §6)."""
    record_ingestion_failure(
        session, job.company_id, document_type=job.document_type_hint,
        original_filename=job.original_filename, failure_reason=failure_reason, detail=detail,
    )
    job.status = "failed"
    job.error_message = detail
    job.finished_at = datetime.now(timezone.utc)
    session.add(OwnerNotification(
        company_id=job.company_id,
        type="document_failed",
        message=f"{job.original_filename} 업로드에 실패했어요 — {detail} 다시 올려 주세요.",
        payload={"job_id": job.id, "failure_reason": failure_reason},
    ))
    session.commit()


def process_upload_job(job_id: int, session: Session | None = None) -> None:
    """백그라운드 실행부 — create_upload_job()이 저장해둔 파일을 읽어 실제 추출·적재를 수행한다.

    요청 스코프 세션은 응답이 나가면 닫히므로 기본적으로 독립 세션(api/db.py::
    new_session)을 새로 연다. session을 직접 넘기면(테스트 전용 — create_upload_job과
    같은 세션/엔진을 써야 눈에 보인다) 그 세션을 그대로 쓰고 여기서 닫지 않는다
    (호출자가 lifecycle을 소유). 로직은 기존 ingest_uploaded_document()의 나머지
    절반과 동일 — 룰만 "예외를 던진다"에서 "job을 failed로 남기고 리턴한다"로
    바뀐다(백그라운드라 호출자가 예외를 받을 수 없음).
    """
    owns_session = session is None
    if session is None:
        session = new_session()
    try:
        job = session.get(DocumentUploadJob, job_id)
        if job is None or job.status != "processing":
            return

        abs_path = os.path.join(REPO_ROOT, job.file_path)
        with open(abs_path, "rb") as f:
            file_bytes = f.read()

        ib = resolve_institution_borrower(session, job.company_id)
        if ib is None:
            # 접수 시점엔 있었는데 그 사이 사라지는 경우는 사실상 없지만, 방어적으로.
            _fail_job(session, job, failure_reason="missing_institution",
                      detail="기업이 금융기관에 귀속되어 있지 않습니다.")
            return
        financial_institution_id, institution_borrower_id = ib

        document_type = job.document_type_hint
        mode = job.mode

        skipped_rows = 0
        extraction_method = None
        extraction_confidence = None
        guidance_message = None
        try:
            if document_type == "tax_invoice" and mode == "excel":
                rows, skipped_rows = parse_hometax_excel(file_bytes)
                extracted: dict = {"rows": rows, "skipped_rows": skipped_rows}
                source_system = "upload:excel"
                resolved_document_type = "tax_invoice"
            else:
                row = extract_document(session, file_bytes, document_type)
                rows = [row]
                extracted = row
                source_system = "upload:ocr"
                resolved_document_type = row["document_type"]
                extraction_method = row.get("extraction_method")
                extraction_confidence = row.get("extraction_confidence")
                guidance_message = row.get("guidance_message")
        except HometaxExcelFormatError as e:
            _fail_job(session, job, failure_reason="excel_format", detail=str(e))
            return
        except DocumentParseError as e:
            _fail_job(session, job, failure_reason="parse_error", detail=str(e))
            return

        for row in rows:
            if not row.get("item_description"):
                _fail_job(session, job, failure_reason="parse_error",
                           detail="품목명을 읽어내지 못했어요 — 더 선명하게 다시 올려 주세요")
                return

        verification_status = extracted.get("quality_flag", "unverified") if mode != "excel" else "unverified"

        doc = SourceDocument(
            financial_institution_id=financial_institution_id,
            company_id=job.company_id,
            document_type=resolved_document_type,
            source_system=source_system,
            original_filename=job.original_filename,
            file_hash=job.file_hash,
            file_path=job.file_path,
            extracted_json=extracted,
            verification_status=verification_status,
            extraction_method=extraction_method,
            extraction_confidence=extraction_confidence,
            year=rows[0]["year"] if mode == "ocr" else None,
            month=rows[0]["month"] if mode == "ocr" else None,
        )
        voucher_source = DOCUMENT_TYPE_TO_VOUCHER_SOURCE[resolved_document_type]

        created: list[Voucher] = []
        try:
            session.add(doc)
            session.flush()

            for row in rows:
                raw = {**row, "source_document_id": doc.id}
                v = Voucher(
                    company_id=job.company_id,
                    source=voucher_source,
                    year=row["year"],
                    month=row["month"],
                    issue_date=_parse_issue_date(row.get("issue_date")),
                    supplier_name=row.get("supplier_name"),
                    item_description=row.get("item_description"),
                    supply_amount_krw=row.get("supply_amount_krw"),
                    raw_json=raw,
                    source_document_id=doc.id,
                    financial_institution_id=financial_institution_id,
                    institution_borrower_id=institution_borrower_id,
                )
                session.add(v)
                created.append(v)

            session.commit()
        except IntegrityError:
            session.rollback()
            _fail_job(session, job, failure_reason="duplicate", detail="이미 업로드된 파일입니다")
            return

        job.status = "done"
        job.result_source_document_id = doc.id
        job.result_document_type = resolved_document_type
        job.vouchers_created = len(created)
        job.skipped_rows = skipped_rows
        job.guidance_message = guidance_message
        job.finished_at = datetime.now(timezone.utc)

        label = DOCUMENT_TYPE_LABEL.get(resolved_document_type, resolved_document_type)
        if mode == "ocr":
            job.result_year = rows[0]["year"]
            job.result_month = rows[0]["month"]
            message = f"{label} {job.result_month}월 자료가 등록됐어요."
        else:
            message = f"{label} {len(created)}건이 등록됐어요."
        session.add(OwnerNotification(
            company_id=job.company_id,
            type="document_processed",
            message=message,
            payload={"job_id": job.id, "source_document_id": doc.id},
        ))
        session.commit()
    finally:
        if owns_session:
            session.close()
