""""데이터 업로드" 탭(문서종류 × 월 그리드, 파일 목록·삭제)이 쓰는 결정론적 쿼리·삭제.

LLM 미호출 — 전부 결정론적 코드(CLAUDE.md 원칙1과 같은 결).

0017 마이그레이션 전제: `SourceDocument.year/month`(OCR 업로드만 채워짐)와
`Voucher.source_document_id`(실제 FK)가 있어야 이 모듈의 쿼리가 성립한다.
"""
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db.document_requirements import DocumentType, FuelTypes, required_documents
from db.models import Classification, Company, SourceDocument, SourceDocumentAccessLog, Voucher

_DOCUMENT_TYPES: tuple[DocumentType, ...] = ("tax_invoice", "electric_bill", "gas_bill")


def document_upload_grid(session: Session, company_id: int, year: int) -> dict:
    """문서종류 3종 × 1~12월 업로드 현황 — 문서종류별 필수/선택/해당없음도 같이 반환
    (db/document_requirements.py::required_documents 재사용, 사장님이 체크한 연료 기준).

    한 칸(문서종류·월)에 여러 건이 업로드될 수 있어(같은 달 여러 장 나눠 올림 등)
    개수로 반환한다 — 0보다 크면 "채워짐".
    """
    company = session.get(Company, company_id)
    fuel_types: FuelTypes = (company.fuel_types_json or {}) if company else {}
    statuses = required_documents(fuel_types)

    rows = session.execute(
        select(SourceDocument.document_type, SourceDocument.month, func.count(SourceDocument.id))
        .where(SourceDocument.company_id == company_id, SourceDocument.year == year)
        .group_by(SourceDocument.document_type, SourceDocument.month)
    ).all()

    counts: dict[str, dict[int, int]] = {dt: {} for dt in _DOCUMENT_TYPES}
    for doc_type, month, count in rows:
        if doc_type in counts and month is not None:
            counts[doc_type][month] = count

    return {
        "reporting_year": year,
        "document_types": [
            {
                "document_type": dt,
                "status": statuses.get(dt, "optional"),
                "months": {m: counts[dt].get(m, 0) for m in range(1, 13)},
            }
            for dt in _DOCUMENT_TYPES
        ],
    }


def documents_for_cell(
    session: Session, company_id: int, document_type: str, year: int, month: int
) -> list[dict]:
    """한 칸(문서종류·월)에 업로드된 원본 문서 목록."""
    rows = session.execute(
        select(SourceDocument)
        .where(
            SourceDocument.company_id == company_id,
            SourceDocument.document_type == document_type,
            SourceDocument.year == year,
            SourceDocument.month == month,
        )
        .order_by(SourceDocument.created_at)
    ).scalars().all()
    return [
        {
            "id": d.id,
            "original_filename": d.original_filename,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "verification_status": d.verification_status,
        }
        for d in rows
    ]


def delete_source_document(session: Session, document: SourceDocument) -> str | None:
    """원본 문서와 거기서 만들어진 전표·분류·접근로그를 지운다. 물리 파일 삭제는
    호출부(api 레이어) 책임 — 이 함수는 지워야 할 file_path만 반환한다(db/ 모듈은
    파일시스템을 직접 건드리지 않는다, api/document_ingestion.py와 같은 관례).

    PCAF 등급·집계는 저장값이 아니라 매 요청마다 재계산이라(db/pcaf_quality.py::
    assess_borrower_emission_quality 등) 별도 후처리가 필요 없다 — 다음 조회 때
    자동으로 반영된다.

    호출부가 소유권(company_id)·존재 여부를 먼저 확인해야 한다 — 이 함수는 이미
    검증된 SourceDocument 객체를 받는다.
    """
    voucher_ids = session.execute(
        select(Voucher.id).where(Voucher.source_document_id == document.id)
    ).scalars().all()
    if voucher_ids:
        session.execute(delete(Classification).where(Classification.voucher_id.in_(voucher_ids)))
        session.execute(delete(Voucher).where(Voucher.id.in_(voucher_ids)))
    session.execute(
        delete(SourceDocumentAccessLog).where(SourceDocumentAccessLog.source_document_id == document.id)
    )

    file_path = document.file_path
    session.delete(document)
    session.commit()
    return file_path
