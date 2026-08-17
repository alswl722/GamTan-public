"""사장님 전용 API — /owner 장면이 쓰는 자기 기업 데이터 조회·입력.

- GET   /owner/alerts/{company_id}              자기 기업의 이상 신호 알림
- PATCH /owner/{company_id}/fuel-types          2단계(연료 유형 체크) 저장 + 3단계 필수서류 안내
- POST  /owner/{company_id}/documents/upload    3~4단계 업로드(세금계산서 OCR|엑셀, 전기·도시가스 OCR)
                                                 — document_type 생략 시 자동판별("그냥 업로드", mode=ocr 전용)
- GET   /owner/{company_id}/documents/grid      데이터 업로드 탭 — 문서종류 × 월 그리드
- GET   /owner/{company_id}/documents           그리드 한 칸의 업로드 파일 목록
- DELETE /owner/{company_id}/documents/{id}     업로드 파일 삭제(전표·분류까지 연쇄 삭제)
- GET   /owner/{company_id}/progress            5단계 위저드 실제 완료 상태 — 홈 화면 진행바·이어하기용
- GET   /owner/{company_id}/rate-candidate      우대금리 상품 자격 상태(이미 대상 | 개선 필요)
- POST  /owner/{company_id}/rate-requests       우대금리·설비금융 안내 요청 생성 → 관리자 승인요청 큐
- GET   /owner/{company_id}/k-taxonomy-leads    K택소노미·설비투자 리드(있으면 설비금융 안내 요청 버튼 노출)
- GET   /owner/{company_id}/anomaly-checks      이상치 되묻기 — 답변 대기 중인 확인 요청 목록
- PATCH /owner/{company_id}/classifications/{voucher_id}/anomaly-check  이상치 확인 답변(네/아니오/모르겠어요, 숫자 입력 없음)
- GET   /owner/{company_id}/notifications       확정 전송 알림 목록(메인 화면 배너, 폴링 조회, ?unread=true)
- PATCH /owner/{company_id}/notifications/{id}/read  알림 읽음 처리(배너 클릭 시)

GET /admin/alerts(은행 담당자용 포트폴리오 전체)와 같은 판정 로직
(db/alerts.py::detect_alerts)을 재사용하되 자기 기업으로만 필터한다 —
은행이 먼저 알고 사장은 모르는 구도를 만들지 않기 위함(CLAUDE.md §9,
"하지 말 것" — 알림은 항상 사장에게 먼저).
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from api.document_ingestion import (
    REPO_ROOT,
    DuplicateDocumentError,
    MissingInstitutionAttributionError,
    ingest_uploaded_document,
)
from api.queries import get_coverage, get_owner_notifications, get_owner_progress, get_pending_anomaly_checks
from db.alerts import detect_alerts
from db.document_coverage import (
    delete_source_document,
    document_pending_review_count,
    document_upload_grid,
    documents_for_cell,
    upload_streak,
)
from db.document_requirements import FuelTypes, required_documents
from db.document_text_extractor import DocumentParseError
from db.hometax_excel_parser import HometaxExcelFormatError
from db.k_taxonomy import k_taxonomy_leads_for_company
from db.models import Classification, Company, OwnerNotification, SourceDocument, Voucher
from db.pcaf_quality import default_reporting_year
from db.rate_products import rate_product_status_for_company
from db.quality_issues import record_ingestion_failure
from db.rate_approvals import (
    CompanyNotFoundError,
    DISCLAIMER_TEXT,
    InvalidScopeError,
    NoUpgradeCandidateError,
    create_rate_request,
)

router = APIRouter(prefix="/owner", tags=["owner"])

_VALID_DOCUMENT_TYPES = ("tax_invoice", "electric_bill", "gas_bill")


@router.get("/alerts/{company_id}")
def owner_alerts(company_id: int, session: Session = Depends(get_session)):
    """자기 기업의 이상 신호 알림만 — 여신 결정과 무관, 안내 문구일 뿐(CLAUDE.md §9)."""
    return {"alerts": detect_alerts(session, company_id=company_id)}


class FuelTypesIn(BaseModel):
    diesel: bool = False
    gasoline: bool = False
    city_gas: bool = False
    lpg: str = "no"  # yes | no | unsure
    electricity: bool = True


@router.patch("/{company_id}/fuel-types")
def update_fuel_types(company_id: int, body: FuelTypesIn, session: Session = Depends(get_session)):
    """연료 유형 체크 저장 + 3단계(업로드) 화면이 바로 쓸 필수/선택 문서 판정 반환.

    db/document_requirements.py 순수함수를 그대로 호출한다 — 저장과 판정을 분리하지
    않고 한 응답에 같이 내려줘야 프론트가 저장 직후 업로드 화면 뱃지를 바로 그릴 수 있다.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")

    fuel_types: FuelTypes = body.model_dump()  # type: ignore[assignment]
    company.fuel_types_json = fuel_types
    session.commit()

    return {"fuel_types": fuel_types, "required_documents": required_documents(fuel_types)}


@router.get("/{company_id}/anomaly-checks")
def pending_anomaly_checks(company_id: int, session: Session = Depends(get_session)):
    """이상치 되묻기(docs/tasks.md) — 사장님이 아직 답하지 않은 이상치 확인 요청 목록."""
    return {"items": get_pending_anomaly_checks(session, company_id)}


class AnomalyCheckIn(BaseModel):
    answer: Literal["normal", "disputed", "unknown"]
    reason: str | None = None


@router.patch("/{company_id}/classifications/{voucher_id}/anomaly-check")
def supplement_anomaly_check(
    company_id: int,
    voucher_id: int,
    body: AnomalyCheckIn,
    session: Session = Depends(get_session),
):
    """사장님이 이상치 확인 요청에 답한다 — 숫자는 받지 않는다(핵심 원칙,
    docs/tasks.md). "네, 정상이에요"는 참고정보로만 남지만, "아니요"·
    "모르겠어요"는 담당자 우선순위 알림으로 이어진다 — 이미 auto(자동확정)
    였던 건은 review_required로 되돌려 HITL 큐에서 눈에 띄게 한다.

    다른 기업 소유 전표는 404로 막는다(테넌트 경계, CLAUDE.md 원칙9 — 기존
    documents DELETE 엔드포인트와 같은 패턴).
    """
    voucher = session.get(Voucher, voucher_id)
    if voucher is None or voucher.company_id != company_id:
        raise HTTPException(status_code=404, detail=f"voucher_id={voucher_id} 없음")

    classification = session.execute(
        select(Classification).where(Classification.voucher_id == voucher_id)
    ).scalar_one_or_none()
    if classification is None or classification.anomaly_check_status != "pending":
        raise HTTPException(status_code=404, detail="확인 대기 중인 이상치 요청이 아닙니다")

    status_map = {"normal": "confirmed_normal", "disputed": "disputed", "unknown": "unknown"}
    classification.anomaly_check_status = status_map[body.answer]
    classification.anomaly_check_reason = body.reason

    if body.answer != "normal" and classification.status == "auto":
        classification.status = "review_required"

    session.commit()

    return {
        "voucher_id": voucher_id,
        "anomaly_check_status": classification.anomaly_check_status,
        "anomaly_check_reason": classification.anomaly_check_reason,
        "status": classification.status,
    }


@router.get("/{company_id}/coverage")
def owner_coverage(company_id: int, session: Session = Depends(get_session)):
    """업로드 화면(3~4단계)의 결손 넛지 카드용 — 연료체크로 필터된 gaps만 반환.

    db/alerts.py(EWS)는 분류 완료 후에나 의미가 있어 업로드 직후엔 비어 보인다.
    이건 voucher 존재 여부만 보는 훨씬 이른 신호라 업로드 직후에도 바로 쓸 수 있다.
    """
    return get_coverage(session, company_id)


@router.get("/{company_id}/progress")
def owner_progress(company_id: int, session: Session = Depends(get_session)):
    """5단계 위저드 각 단계의 실제 완료 여부 — 홈 화면 진행바, 위저드 이어하기(어느
    단계부터 시작할지)가 이 값을 그대로 쓴다. 브라우저 세션이 아니라 DB 상태 기준
    이라 새로고침·다른 기기에서 열어도 같은 값이 나온다.
    """
    try:
        return get_owner_progress(session, company_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{company_id}/documents/upload")
async def upload_document(
    company_id: int,
    file: UploadFile = File(...),
    document_type: str | None = Form(None),
    mode: str = Form("ocr"),
    session: Session = Depends(get_session),
):
    """3단계(세금계산서 OCR|엑셀 택1)·4단계(전기·도시가스고지서 OCR) 공용 업로드.

    실제 처리는 api/document_ingestion.py — source_documents 적재 후 vouchers를
    만들어 기존 classify_vouchers 파이프라인이 그대로 이어받게 한다. mode="excel"은
    document_type="tax_invoice"에서만 의미 있음(대량 홈택스 엑셀 파서 경로).

    document_type을 생략(None)하면 어느 칸인지 모르고 올린 "그냥 업로드"다(mode=
    "ocr" 전용) — OCR/비전이 스스로 종류를 판별한다. 판별 자체가 안 되면 추정으로
    채우지 않고 422로 명확히 실패한다(실패 가시성 원칙).
    """
    if document_type is not None and document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid document_type: {document_type}")
    if mode not in ("ocr", "excel"):
        raise HTTPException(status_code=400, detail=f"invalid mode: {mode}")
    if mode == "excel" and document_type != "tax_invoice":
        raise HTTPException(status_code=400, detail="엑셀 업로드는 세금계산서만 지원합니다")
    # 문서 자체(PDF 텍스트)에서 날짜를 읽어낸다(db/document_text_extractor.py).
    # 못 읽으면 합성값으로 가리지 않고 422로 명확히 실패한다(실패 가시성 원칙).

    file_bytes = await file.read()
    filename = file.filename or "upload"
    try:
        # PaddleOCR(db/document_ocr_extractor.py)은 CPU 연산이라 동기 호출 그대로 두면
        # 이 요청이 끝날 때까지 이벤트 루프 전체가 막힌다 — 그 사이 다른 사용자의 아무
        # 요청도(연료 유형 저장 등 가벼운 PATCH까지) 응답을 못 받고 타임아웃난다(실측
        # 확인). 스레드로 넘겨 이벤트 루프는 다른 요청을 계속 처리하게 한다.
        return await asyncio.to_thread(
            ingest_uploaded_document,
            session, company_id, file_bytes, filename,
            document_type, mode=mode,
        )
    except DuplicateDocumentError as e:
        record_ingestion_failure(
            session, company_id, document_type=document_type, original_filename=filename,
            failure_reason="duplicate", detail=str(e),
        )
        raise HTTPException(status_code=409, detail=str(e))
    except MissingInstitutionAttributionError as e:
        record_ingestion_failure(
            session, company_id, document_type=document_type, original_filename=filename,
            failure_reason="missing_institution", detail=str(e),
        )
        raise HTTPException(status_code=422, detail=str(e))
    except HometaxExcelFormatError as e:
        # 실패 가시성 원칙 — 파싱 실패를 목업 데이터로 가리지 않고 그대로 안내(CLAUDE.md §6)
        record_ingestion_failure(
            session, company_id, document_type=document_type, original_filename=filename,
            failure_reason="excel_format", detail=str(e),
        )
        raise HTTPException(status_code=422, detail=str(e))
    except DocumentParseError as e:
        # 문서에서 날짜·금액을 못 읽었거나(화질 불량 등) 엉뚱한 칸에 업로드된 경우 —
        # 같은 실패 가시성 원칙, 값을 지어내지 않고 사유를 그대로 보여준다.
        # OcrEngineError(PaddleOCR 엔진 자체 실패)도 이 서브클래스라 여기서
        # 같이 잡힌다 — 원인 구분은 detail 텍스트로 충분해 failure_reason은 공유한다.
        record_ingestion_failure(
            session, company_id, document_type=document_type, original_filename=filename,
            failure_reason="parse_error", detail=str(e),
        )
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{company_id}/documents/grid")
def documents_grid(
    company_id: int, year: int | None = None, session: Session = Depends(get_session)
):
    """"데이터 업로드" 탭 — 문서종류 3종 × 1~12월 업로드 현황(db/document_coverage.py
    ::document_upload_grid). year 생략 시 그 기업의 최신 전표 연도를 쓴다(사장님 리포트·
    우대금리 판정과 같은 기준 공유, db/pcaf_quality.py::default_reporting_year).
    """
    resolved_year = year if year is not None else default_reporting_year(session, company_id)
    return document_upload_grid(session, company_id, resolved_year)


@router.get("/{company_id}/upload-streak")
def upload_streak_endpoint(company_id: int, session: Session = Depends(get_session)):
    """도장판 위 동기부여 배지 — 필수 문서를 전부 채운 달이 이번 달 직전부터 몇 개월
    연속 이어지는지(db/document_coverage.py::upload_streak)."""
    return upload_streak(session, company_id)


@router.get("/{company_id}/documents")
def documents_in_cell(
    company_id: int,
    document_type: str,
    year: int,
    month: int,
    session: Session = Depends(get_session),
):
    """그리드에서 칸(문서종류·월)을 눌렀을 때 그 칸에 업로드된 파일 목록."""
    if document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid document_type: {document_type}")
    return {"documents": documents_for_cell(session, company_id, document_type, year, month)}


@router.get("/{company_id}/documents/{document_id}/review-status")
def document_review_status(company_id: int, document_id: int, session: Session = Depends(get_session)):
    """업로드 완료 모달용 — 방금 올린 문서에서 만들어진 전표 중 몇 건이 담당자
    검토 대기(review_required)인지. 어떤 항목이 왜 검토 대상인지(판단 근거·Scope
    등)는 노출하지 않는다(api/queries.py::get_classifications와 같은 원칙 — 건수만).
    프론트가 /classify/{company_id} 실행 직후 호출한다(분류가 끝나야 review_required
    가 채워짐).
    """
    doc = session.get(SourceDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise HTTPException(status_code=404, detail=f"document_id={document_id} 없음")
    return {"pending_review_count": document_pending_review_count(session, document_id)}


@router.delete("/{company_id}/documents/{document_id}")
def delete_document(company_id: int, document_id: int, session: Session = Depends(get_session)):
    """업로드 파일 삭제 — 거기서 만들어진 전표·분류·접근로그까지 연쇄 삭제하고 물리
    파일도 지운다(db/document_coverage.py::delete_source_document). 다른 기업 소유
    문서는 404로 명확히 막는다(테넌트 경계, CLAUDE.md 원칙9).
    """
    doc = session.get(SourceDocument, document_id)
    if doc is None or doc.company_id != company_id:
        raise HTTPException(status_code=404, detail=f"document_id={document_id} 없음")

    file_path = delete_source_document(session, doc)
    if file_path:
        abs_path = os.path.join(REPO_ROOT, file_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)  # best-effort — DB 삭제는 이미 커밋됨

    return {"deleted": True, "document_id": document_id}


class RateRequestIn(BaseModel):
    # Literal로 제약 — 잘못된 값은 여기서 422로 막는다. db/models.py의
    # ck_rate_approval_requests_request_type CHECK 제약까지 도달하면 처리 안 된
    # IntegrityError가 그대로 새서 500이 된다(리뷰 지적사항, PR #28).
    request_type: Literal["rate_upgrade", "equipment_finance"] = "rate_upgrade"
    # rate_upgrade는 Scope별 독립 후보라(정식 엔진) 어느 Scope에 대한 요청인지 필수.
    scope_group: Literal["scope_1", "scope_2"] | None = None
    # equipment_finance 전용 — K택소노미 리드 카드에서 어떤 설비인지 채워서 보낸다.
    # rate_upgrade는 서버가 candidate에서 계산한 missing을 쓰므로 이 값을 무시한다.
    missing_summary: str | None = None


@router.get("/{company_id}/rate-candidate")
def rate_candidate(company_id: int, session: Session = Depends(get_session)):
    """자기 기업의 Scope별 우대금리 상품 자격 상태 목록(0~2건,
    db/rate_products.py::rate_product_status_for_company).

    각 항목의 status가 "eligible"(이미 상품 자격 충족)이거나 "upgrade_needed"(등급
    개선 필요)다 — 프론트는 이 값으로 두 카드 종류를 나눠 렌더링한다. 은행 쪽
    GET /admin/rate-candidates(quality_upgrade_candidates_for_company, 등급 개선
    후보만 다룸)와는 별개 응답 구조다.
    """
    candidates = rate_product_status_for_company(session, company_id)
    return {"candidates": candidates, "disclaimer_text": DISCLAIMER_TEXT}


@router.post("/{company_id}/rate-requests")
def submit_rate_request(
    company_id: int, body: RateRequestIn, session: Session = Depends(get_session)
):
    """사장님이 안내 카드의 "요청" 버튼을 눌러 승인요청 큐에 항목을 만든다.

    여신 결정이 아니다(CLAUDE.md §9) — 이 요청은 관리자 승인요청 큐(GET /admin/rate-requests)로
    가서 담당자가 "안내 대상으로 확인"할 뿐, 금리·여신을 자동으로 확정하지 않는다.
    """
    if body.request_type == "rate_upgrade" and body.scope_group is None:
        raise HTTPException(status_code=422, detail="scope_group required for rate_upgrade")
    try:
        req = create_rate_request(
            session,
            company_id,
            request_type=body.request_type,
            scope_group=body.scope_group,
            missing_summary=body.missing_summary,
        )
    except CompanyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (NoUpgradeCandidateError, InvalidScopeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "id": req.id,
        "company_id": req.company_id,
        "request_type": req.request_type,
        "scope_group": req.scope_group,
        "current_grade": req.current_grade,
        "target_grade": req.target_grade,
        "missing_summary": req.missing_summary,
        "matched_product_name": req.matched_product_name,
        "disclaimer_text": req.disclaimer_text,
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


@router.get("/{company_id}/k-taxonomy-leads")
def k_taxonomy_leads(company_id: int, session: Session = Depends(get_session)):
    """자기 기업의 K택소노미·설비투자 리드 — 설비 단위로 묶어서 반환(있으면 프론트가
    "설비금융 안내 요청" 버튼을 노출한다).

    룰 매칭 경로에서만 채워지는 필드라(LLM 분류 경로는 항상 비어 있음) 대다수
    기업·기간은 빈 리스트가 정상이다. 은행 GET /admin/k-taxonomy-leads와 같은 원천
    데이터를 자기 기업으로 좁혀 재사용한다(db/k_taxonomy.py::k_taxonomy_leads_for_company).
    """
    return {"leads": k_taxonomy_leads_for_company(session, company_id)}


@router.get("/{company_id}/notifications")
def owner_notifications(
    company_id: int,
    unread: bool = False,
    session: Session = Depends(get_session),
):
    """메인 화면 배너용 — 확정 전송 알림 목록 (v1 §6-2). 폴링(10~15초)으로 조회한다.

    unread=true면 아직 안 읽은 것만 — 배너가 "새 알림 있음"만 감지하면 되는
    경우에 쓴다.
    """
    return {"notifications": get_owner_notifications(session, company_id, unread_only=unread)}


@router.patch("/{company_id}/notifications/{notification_id}/read")
def mark_notification_read(
    company_id: int,
    notification_id: int,
    session: Session = Depends(get_session),
):
    """배너 클릭 시 읽음 처리. 다른 기업 소유 알림을 잘못 건드리지 않도록
    company_id도 함께 검증한다(기존 documents DELETE 엔드포인트와 같은 패턴)."""
    notification = session.get(OwnerNotification, notification_id)
    if notification is None or notification.company_id != company_id:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")

    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        session.commit()

    return {"id": notification.id, "read_at": notification.read_at}
