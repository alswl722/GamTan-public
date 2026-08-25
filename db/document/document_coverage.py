""""데이터 업로드" 탭(문서종류 × 월 그리드, 파일 목록·삭제)이 쓰는 결정론적 쿼리·삭제.

LLM 미호출 — 전부 결정론적 코드(CLAUDE.md 원칙1과 같은 결).

0017 마이그레이션 전제: `SourceDocument.year/month`(OCR 업로드만 채워짐)와
`Voucher.source_document_id`(실제 FK)가 있어야 이 모듈의 쿼리가 성립한다.
"""
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from db.document.document_requirements import DocumentType, FuelTypes, required_documents
from db.models import (
    Classification,
    Company,
    DocumentUploadJob,
    SourceDocument,
    SourceDocumentAccessLog,
    Voucher,
)

# water_bill은 **의도적으로 빠져 있다**(빠뜨린 게 아니다). 이 튜플이 업로드 그리드의
# 열 목록이라, 넣으면 사장님 화면에 수도 칸이 생기는데 파서가 없어서 올리면 100% 실패한다
# (db/document/document_text_extractor.py::_parse_by_type의 water_bill 분기).
# 파서(db/water_bill_extraction.py)가 생기는 시점에 여기 + api/routers/owner.py의
# _VALID_DOCUMENT_TYPES + web/components/SceneUpload.tsx를 함께 열면 된다.
# 참고: statuses.get(dt, "optional") 기본값이 있어 required_documents()에 키가 없어도
# 그리드는 깨지지 않고, upload_streak은 required 집합만 쓰므로 영향받지 않는다.
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


def upload_streak(session: Session, company_id: int) -> dict:
    """"필수 문서를 전부 채운 달"이 오늘 기준 몇 개월 연속 이어지는지 — 업로드
    그리드 위 동기부여 배지 재료. document_upload_grid와 같은 데이터 소스
    (SourceDocument.year/month — OCR 업로드만 채워짐, 파일 상단 모듈 docstring
    참고)를 써서 같은 한계를 그대로 공유한다(엑셀 업로드는 스트릭에 안 잡힘).

    이번 달은 아직 진행 중이라 스트릭에서 제외하고(원칙7과 같은 결 — 미완료를
    완료로 세지 않음) 그 직전 달부터 거꾸로 센다. electric_bill은 연료 체크 여부와
    무관하게 항상 필수라(required_documents) 연료를 아직 안 골랐어도 스트릭은
    성립할 수 있다 — document_upload_grid와 같은 규칙을 그대로 따른 결과다."""
    company = session.get(Company, company_id)
    fuel_types: FuelTypes = (company.fuel_types_json or {}) if company else {}
    required = {dt for dt, status in required_documents(fuel_types).items() if status == "required"}

    rows = session.execute(
        select(SourceDocument.year, SourceDocument.month, SourceDocument.document_type)
        .where(
            SourceDocument.company_id == company_id,
            SourceDocument.document_type.in_(required),
            SourceDocument.year.isnot(None),
            SourceDocument.month.isnot(None),
        )
        .distinct()
    ).all()

    filled: dict[tuple[int, int], set[str]] = {}
    for year, month, doc_type in rows:
        filled.setdefault((year, month), set()).add(doc_type)

    now = datetime.now(timezone.utc)
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12

    streak = 0
    while required <= filled.get((year, month), set()):
        streak += 1
        month -= 1
        if month == 0:
            year, month = year - 1, 12

    return {"streak_months": streak}


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


def document_pending_review_count(session: Session, source_document_id: int) -> int:
    """방금 올린 문서 1건에서 만들어진 전표 중 담당자 검토 대기(review_required)로
    빠진 건수 — 업로드 완료 모달이 "N건은 담당자가 검토할 예정이에요"를 보여줄 때
    쓴다. api/queries.py::get_classifications()가 지키는 것과 같은 원칙(HITL 대기
    건은 판단 근거·Scope 등 세부 내용을 사장님에게 노출하지 않는다)에 따라 건수만
    반환한다 — 어떤 항목이 왜 검토 대상인지는 노출하지 않음.
    """
    return session.execute(
        select(func.count())
        .select_from(Classification)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.source_document_id == source_document_id,
            Classification.status == "review_required",
        )
    ).scalar_one()


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
    # 업로드 잡(v1 2주차, api/document_ingestion.py::process_upload_job)이 완료 시
    # result_source_document_id로 이 문서를 가리켜뒀다 — job 자체(처리 이력)는
    # 지우지 않고 참조만 끊는다(FK가 NOT NULL이 아니라 그대로 두면 삭제 시
    # IntegrityError, 2026-08-18 실측 확인).
    session.execute(
        update(DocumentUploadJob)
        .where(DocumentUploadJob.result_source_document_id == document.id)
        .values(result_source_document_id=None)
    )

    file_path = document.file_path
    session.delete(document)
    session.commit()
    return file_path
