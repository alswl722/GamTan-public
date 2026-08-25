"""사장님 전용 API — /owner 장면이 쓰는 자기 기업 데이터 조회·입력.

- GET   /owner/alerts/{company_id}              자기 기업의 이상 신호 알림
- PATCH /owner/{company_id}/fuel-types          2단계(연료 유형 체크) 저장 + 3단계 필수서류 안내
- POST  /owner/{company_id}/documents/upload    3~4단계 업로드(세금계산서 OCR|엑셀, 전기·도시가스 OCR)
                                                 — document_type 생략 시 자동판별("그냥 업로드", mode=ocr 전용)
                                                 — 202 즉시 응답 + job_id, 실제 추출은 백그라운드(아래 jobs 참고)
- GET   /owner/{company_id}/documents/jobs/{job_id}  업로드 잡 단건 상태 폴링(처리 중/완료/실패)
- GET   /owner/{company_id}/documents/jobs      최근 업로드 잡 목록(?status=processing 등)
- GET   /owner/{company_id}/calendar            탄소 캘린더 — 그 달 날짜별 이벤트(전표+AI 활동)
- GET   /owner/{company_id}/briefing            월간 AI 브리핑 — 이번 달 vs 지난달 연료별 요약 편지
- GET   /owner/{company_id}/documents/grid      데이터 업로드 탭 — 문서종류 × 월 그리드
- GET   /owner/{company_id}/documents           그리드 한 칸의 업로드 파일 목록
- DELETE /owner/{company_id}/documents/{id}     업로드 파일 삭제(전표·분류까지 연쇄 삭제)
- GET   /owner/{company_id}/progress            5단계 위저드 실제 완료 상태 — 홈 화면 진행바·이어하기용
- GET   /owner/{company_id}/rate-candidate      우대금리 상품 자격 상태(이미 대상 | 개선 필요)
- POST  /owner/{company_id}/rate-requests       우대금리·설비금융 안내 요청 생성 → 관리자 승인요청 큐
- GET   /owner/{company_id}/k-taxonomy-leads    K택소노미·설비투자 리드(있으면 설비금융 안내 요청 버튼 노출)
- GET   /owner/{company_id}/gov-support-candidates  개인화된 정부 지원사업 매칭 후보(top-K, 근거문장 포함)
- GET   /owner/{company_id}/anomaly-checks      이상치 되묻기 — 답변 대기 중인 확인 요청 목록
- PATCH /owner/{company_id}/classifications/{voucher_id}/anomaly-check  이상치 확인 답변(네/아니오/모르겠어요, 숫자 입력 없음)
- GET   /owner/{company_id}/notifications       확정 전송 알림 목록(메인 화면 배너, 폴링 조회, ?unread=true)
- PATCH /owner/{company_id}/notifications/{id}/read  알림 읽음 처리(배너 클릭 시)
- GET   /owner/{company_id}/goal                홈 화면 목표 카드 — 활성 목표 + 재계산된 진행률·체크리스트
- POST  /owner/{company_id}/goal                목표 확정(배출량 감축 | 등급·혜택 상승) — 기존 활성 목표는 superseded
- POST  /owner/{company_id}/goal/{goal_id}/cancel  목표 취소
- GET   /owner/{company_id}/carbon-point/eligibility  탄소중립포인트 자격 판정(감탄 예상치)
- POST  /owner/{company_id}/carbon-point/applications 신청서 초안 생성(자격 충족 시 draft 저장)
- GET   /owner/{company_id}/carbon-point/applications/{id}   초안 단건 조회
- PATCH /owner/{company_id}/carbon-point/applications/{id}   제출 이후 상태를 사장님이 직접 갱신

GET /admin/alerts(은행 담당자용 포트폴리오 전체)와 같은 판정 로직
(db/alerts.py::detect_alerts)을 재사용하되 자기 기업으로만 필터한다 —
은행이 먼저 알고 사장은 모르는 구도를 만들지 않기 위함(CLAUDE.md §9,
"하지 말 것" — 알림은 항상 사장에게 먼저).
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from api.document_ingestion import (
    REPO_ROOT,
    DuplicateDocumentError,
    MissingInstitutionAttributionError,
    create_upload_job,
    process_upload_job,
)
from api.queries import (
    get_calendar_events,
    get_coverage,
    get_monthly_briefing_stats,
    get_owner_notifications,
    get_owner_progress,
    get_pending_anomaly_checks,
)
from db.owner_briefing import FuelMonthStat, compute_fuel_deltas, get_briefing_paragraphs
from db.alerts import detect_alerts
from db.carbon_neutral_point import (
    SETTLEMENT_MONTHS,
    build_application_draft,
    evaluate_eligibility,
)
from db.document.document_coverage import (
    delete_source_document,
    document_pending_review_count,
    document_upload_grid,
    documents_for_cell,
    upload_streak,
)
from db.document.document_requirements import FuelTypes, required_documents
from db.gov_support.evidence import generate_evidence_batch
from db.gov_support.matching import (
    company_profile_text,
    latest_fetched_at,
    match_gov_support_programs,
    raw_text_by_program_id,
)
from db.pcaf_engine.k_taxonomy import k_taxonomy_leads_for_company
from db.models import (
    CarbonNeutralPointApplication,
    Classification,
    Company,
    DocumentUploadJob,
    OwnerNotification,
    SourceDocument,
    Voucher,
)
from db.pcaf_engine.pcaf_quality import default_reporting_year
from db.pcaf_engine.rate_products import rate_product_status_for_company
from db.quality_issues import record_ingestion_failure
from db.pcaf_engine.rate_approvals import (
    CompanyNotFoundError,
    DISCLAIMER_TEXT,
    InvalidScopeError,
    NoUpgradeCandidateError,
    create_rate_request,
)
from db.pcaf_engine.company_goals import (
    CompanyNotFoundError as GoalCompanyNotFoundError,
    GoalNotFoundError,
    InvalidTargetGradeError,
    NoActivityDataError,
    NoEmissionDataError,
    cancel_goal,
    create_emission_reduction_goal,
    create_grade_upgrade_goal,
    get_active_goal_progress,
)

router = APIRouter(prefix="/owner", tags=["owner"])

# water_bill은 **의도적으로 빠져 있다** — 업로드 요청 검증이라 넣는 순간 수도고지서
# 업로드가 접수되고, 파서가 없어 job이 실패로 끝난다. 지금처럼 막아두면 검증 단계에서
# 명확히 거절된다. 여는 시점은 db/document/document_coverage.py::_DOCUMENT_TYPES 주석 참고.
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


@router.get("/{company_id}/calendar")
def owner_calendar(
    company_id: int,
    year: int | None = None,
    month: int | None = None,
    session: Session = Depends(get_session),
):
    """탄소 캘린더 — 그 달의 날짜별 구매·탄소 배출 내역(전표 기준).

    year/month 생략 시 서버 기준 이번 달. 사장님에게 노출 가능한 분류가 붙은
    전표만 포함한다(get_classifications()와 동일 필터 — api/queries.py::
    _owner_visible_classification_filter). 에이전트 트레이스(활동 로그)는
    포함하지 않는다 — api/queries.py::get_calendar_events 참고.
    """
    today = datetime.now(timezone.utc)
    y = year or today.year
    m = month or today.month
    return {"year": y, "month": m, "events": get_calendar_events(session, company_id, y, m)}


@router.get("/{company_id}/briefing")
def owner_briefing(
    company_id: int,
    year: int | None = None,
    month: int | None = None,
    session: Session = Depends(get_session),
):
    """월간 AI 브리핑 — 이번 달 vs 지난달 연료별 활동을 편지 문단으로 조립.

    증감률 계산(compute_fuel_deltas)은 항상 결정론적 코드다(CLAUDE.md 원칙1
    "LLM 산수 금지"). 문장 표현만 Gemini가 맡고(db/owner_briefing.py::
    get_briefing_paragraphs), LLM 실패 시 템플릿으로 자동 폴백한다 —
    generated_by 필드로 실제 생성 경로를 노출한다(실패를 감추지 않음).
    """
    today = datetime.now(timezone.utc)
    y = year or today.year
    m = month or today.month

    stats = get_monthly_briefing_stats(session, company_id, y, m)
    fuel_month_stats = [
        FuelMonthStat(
            fuel_type=f["fuel_type"],
            this_month_co2e=f["this_month_co2e"],
            last_month_co2e=f["last_month_co2e"],
        )
        for f in stats["fuel_totals"]
    ]
    fuel_deltas = compute_fuel_deltas(fuel_month_stats) if stats["has_previous_month"] else [
        {
            "fuel_type": f.fuel_type,
            "this_month_co2e": round(f.this_month_co2e, 2),
            "last_month_co2e": None,
            "delta_pct": None,
            "direction": "new",
        }
        for f in fuel_month_stats
    ]
    paragraphs, generated_by = get_briefing_paragraphs(
        session, fuel_deltas, has_previous_month=stats["has_previous_month"]
    )

    return {
        "year": y,
        "month": m,
        "has_previous_month": stats["has_previous_month"],
        "paragraphs": paragraphs,
        "fuel_stats": fuel_deltas,
        "generated_by": generated_by,  # "llm" | "llm_cache" | "template" — 실패 가시성
    }


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


@router.post("/{company_id}/documents/upload", status_code=202)
async def upload_document(
    company_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str | None = Form(None),
    mode: str = Form("ocr"),
    session: Session = Depends(get_session),
):
    """3단계(세금계산서 OCR|엑셀 택1)·4단계(전기·도시가스고지서 OCR) 공용 업로드.

    파일 저장·중복/기관귀속 검증만 이 요청 안에서 동기로 끝내고 즉시 202로
    {job_id, status:"processing"}를 반환한다 — 실제 추출(OCR/LLM, 최악 90초+
    걸릴 수 있음, api/document_ingestion.py 주석 참고)은 process_upload_job()이
    백그라운드에서 이어받는다(사장님이 업로드 페이지에 머물러 있지 않아도 되게
    하기 위함, v1 2주차). 진행 상태는 GET .../documents/jobs[/{job_id}]로 조회.

    mode="excel"은 document_type="tax_invoice"에서만 의미 있음(대량 홈택스 엑셀
    파서 경로). document_type을 생략(None)하면 어느 칸인지 모르고 올린 "그냥
    업로드"다(mode="ocr" 전용) — OCR/비전이 스스로 종류를 판별한다.

    중복 제출·기관 미귀속은 흔치 않고 사실상 설정 오류에 가까워 여기서 동기로
    즉시 409/422로 드러낸다(실패 가시성 원칙, CLAUDE.md §6) — 그 외 실패(엑셀
    형식 오류, 문서 파싱 실패 등)는 백그라운드에서 job을 failed로 남기고
    OwnerNotification으로 알린다.
    """
    if document_type is not None and document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid document_type: {document_type}")
    if mode not in ("ocr", "excel"):
        raise HTTPException(status_code=400, detail=f"invalid mode: {mode}")
    if mode == "excel" and document_type != "tax_invoice":
        raise HTTPException(status_code=400, detail="엑셀 업로드는 세금계산서만 지원합니다")

    file_bytes = await file.read()
    filename = file.filename or "upload"
    try:
        # 파일 I/O·해시·DB 조회 정도라 가볍지만, 그래도 스레드로 넘겨 이벤트 루프를
        # 막지 않는다(기존 관례 유지).
        job = await asyncio.to_thread(
            create_upload_job,
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

    background_tasks.add_task(process_upload_job, job.id)
    return {"job_id": job.id, "status": job.status}


def _job_to_dict(job: DocumentUploadJob) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "original_filename": job.original_filename,
        "document_type_hint": job.document_type_hint,
        "mode": job.mode,
        "result_source_document_id": job.result_source_document_id,
        "result_document_type": job.result_document_type,
        "result_year": job.result_year,
        "result_month": job.result_month,
        "vouchers_created": job.vouchers_created,
        "skipped_rows": job.skipped_rows,
        "guidance_message": job.guidance_message,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


@router.get("/{company_id}/documents/jobs/{job_id}")
def upload_job_status(company_id: int, job_id: int, session: Session = Depends(get_session)):
    """업로드 잡 단건 상태 폴링 — 위저드(SceneUpload)가 완료까지 이 값을 기다린다."""
    job = session.get(DocumentUploadJob, job_id)
    if job is None or job.company_id != company_id:
        raise HTTPException(status_code=404, detail=f"job_id={job_id} 없음")
    return _job_to_dict(job)


@router.get("/{company_id}/documents/jobs")
def upload_jobs(
    company_id: int,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    """최근 업로드 잡 목록(최신순 최대 30건) — /owner/uploads가 페이지 재진입 시
    "처리 중" 표시를 복원하는 데 쓴다(?status=processing)."""
    stmt = select(DocumentUploadJob).where(DocumentUploadJob.company_id == company_id)
    if status is not None:
        stmt = stmt.where(DocumentUploadJob.status == status)
    stmt = stmt.order_by(DocumentUploadJob.created_at.desc()).limit(30)
    jobs = session.execute(stmt).scalars().all()
    return {"jobs": [_job_to_dict(j) for j in jobs]}


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


@router.get("/{company_id}/gov-support-candidates")
def gov_support_candidates(company_id: int, session: Session = Depends(get_session)):
    """개인화된 정부 지원사업 매칭 — 기업 프로필 기반 top-K 후보
    (db/gov_support/matching.py::match_gov_support_programs).

    매칭 목록 자체는 결정론적 코사인 유사도가 결정하고(원칙1과 동일한 결),
    LLM은 후보별 근거 문장만 생성한다 — 생성 실패해도 evidence만 null이 되고
    후보 목록·마감일·소관기관 등 사실 필드는 그대로 노출된다(§7 실패 가시성,
    docs/gov-support-matching-plan.md 정본). 우대금리·설비금융 안내(원칙10)와
    같은 결로 "신청 후보 안내"이지 "선정 보장"이 아니다.

    일반 def다(async def 아님) — FastAPI가 이 함수 전체를 워커 스레드에서
    돌려주므로 이벤트 루프를 막지 않는다. **처음에 async def + asyncio.gather로
    만들었다가 실패했다** — async def로 바꾸면 그 앞의 블로킹 호출(DB 조회·
    임베딩 API)이 스레드로 안 넘어간 채 이벤트 루프 위에서 그대로 실행돼,
    이 요청 하나가 동시에 들어온 다른 API(우대금리·K택소노미) 요청까지 전부
    지연시켰다(2026-08-18 실측: 세 엔드포인트 동시 타임아웃). 일반 def가
    이 라우터의 다른 엔드포인트와도 같은 결.

    근거문장은 db/gov_support/evidence.py::generate_evidence_batch가
    llm_cache로 캐싱 + 캐시 미스만 병렬 생성한다 — 캐싱 없이 매번 5건을
    다시 물으면 새로고침할 때마다 8~9초씩 걸렸다(2026-08-18 실측, 전표
    분류가 이미 쓰는 llm_cache 패턴 재사용).
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="기업을 찾을 수 없습니다")

    candidates = match_gov_support_programs(session, company_id)
    if candidates:
        profile_text = company_profile_text(company)
        raw_texts = raw_text_by_program_id(session, [c["program_id"] for c in candidates])
        evidences = generate_evidence_batch(
            session, profile_text,
            [(c["program_id"], c["program_name"], raw_texts.get(c["program_id"], "")) for c in candidates],
        )
        for candidate in candidates:
            candidate["evidence"] = evidences.get(candidate["program_id"])

    fetched_at = latest_fetched_at(session)
    return {
        "as_of": fetched_at.date().isoformat() if fetched_at else None,
        "candidates": candidates,
    }


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


class GoalIn(BaseModel):
    goal_type: Literal["emission_reduction", "grade_upgrade"]
    # emission_reduction 전용
    target_reduction_pct: float | None = None
    # grade_upgrade 전용 — scope_group 필수, target_grade 생략 시 추천 목표(다음 도달
    # 가능 등급)를 그대로 쓴다.
    scope_group: Literal["scope_1", "scope_2"] | None = None
    target_grade: int | None = None


@router.get("/{company_id}/goal")
def owner_goal(company_id: int, session: Session = Depends(get_session)):
    """홈 화면 목표 카드 — 활성 목표가 없으면 goal: null. 진행률·체크리스트는 저장값이
    아니라 조회할 때마다 다시 계산한다(db/pcaf_engine/company_goals.py)."""
    if session.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail=f"company_id={company_id} 없음")
    return {"goal": get_active_goal_progress(session, company_id)}


@router.post("/{company_id}/goal")
def create_goal(company_id: int, body: GoalIn, session: Session = Depends(get_session)):
    """새 목표 확정 — 기존 활성 목표는 덮어쓰지 않고 superseded로 전환한다(CLAUDE.md 원칙8).

    goal_type="grade_upgrade"는 등급 상승과 우대금리 상품 조건 충족을 한 흐름으로
    다룬다(같은 엔진 재사용, DISCLAIMER_TEXT가 응답에 항상 동봉됨 — 원칙10).
    """
    try:
        if body.goal_type == "emission_reduction":
            if body.target_reduction_pct is None:
                raise HTTPException(status_code=422, detail="target_reduction_pct required")
            create_emission_reduction_goal(
                session, company_id, target_reduction_pct=body.target_reduction_pct
            )
        else:
            if body.scope_group is None:
                raise HTTPException(status_code=422, detail="scope_group required")
            create_grade_upgrade_goal(
                session, company_id, scope_group=body.scope_group, target_grade=body.target_grade
            )
    except GoalCompanyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (NoEmissionDataError, NoActivityDataError, InvalidTargetGradeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"goal": get_active_goal_progress(session, company_id)}


@router.post("/{company_id}/goal/{goal_id}/cancel")
def cancel_goal_endpoint(company_id: int, goal_id: int, session: Session = Depends(get_session)):
    """목표 취소 — 다른 기업 소유 목표는 404로 막는다(테넌트 경계, 기존 documents/notifications
    엔드포인트와 같은 패턴)."""
    try:
        cancel_goal(session, company_id, goal_id)
    except GoalNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"cancelled": True, "goal_id": goal_id}


# ── 소상공인 탄소중립포인트 (data-plan.md §9.1) ─────────────────────────────
#
# 응답 필드명은 프론트 `web/lib/carbon-point-fixture.ts`의
# CarbonPointEligibility·CarbonPointDraft와 **동일해야 한다** — 그 fixture를 이 API로
# 교체할 때 컴포넌트를 안 고치는 게 목적이다.
#
# 판정 대상 구간은 쿼리로 받는다. 정산 구간이 6개월이라는 건 확정이지만(회계 확인),
# 구간 시작점이 "가입월 다음 달"인지 "달력 반기 고정"인지는 미확정이라
# (develop-plan.md §2.2) 프론트가 명시적으로 넘기게 두고 기본값만 정해둔다.


class CarbonPointApplicationIn(BaseModel):
    status: Literal["submitted", "approved", "rejected"]


@router.get("/{company_id}/carbon-point/eligibility")
def carbon_point_eligibility(
    company_id: int,
    target_year: int | None = None,
    target_start_month: int = 1,
    months: int = SETTLEMENT_MONTHS,
    session: Session = Depends(get_session),
):
    """탄소중립포인트 자격 판정 — 화면의 자격 카드·홈 알림 배너가 쓴다.

    `reduction_rate_pct`는 감탄의 **자체 예상치**이고 공식 판정이 아니다(CLAUDE.md 원칙10) —
    실제 판정은 한국환경공단이 반기마다 자체 계산한다. "예상치" 표기는 API 플래그가 아니라
    프론트 정적 문구가 담당한다(data-plan.md §6.2 확정).

    제조업(산업용 전기)은 제도상 원천 제외라 감축률을 아예 계산하지 않는다 — 프론트는
    `business_scale_hint`로 카드 자체를 숨긴다.
    """
    year = target_year or datetime.now(timezone.utc).year
    return evaluate_eligibility(
        session, company_id, year, target_start_month, months=months
    )


@router.post("/{company_id}/carbon-point/applications")
def create_carbon_point_application(
    company_id: int,
    target_year: int | None = None,
    target_start_month: int = 1,
    months: int = SETTLEMENT_MONTHS,
    session: Session = Depends(get_session),
):
    """신청서 초안 생성 — 자격을 충족한 경우에만 draft 레코드를 남긴다.

    미달 기업도 초안 미리보기(fields)는 받지만 `application_id`가 null이다 — 신청 대상이
    아닌 기업의 신청서를 DB에 쌓지 않는다(rate-requests가 근거 없는 요청을 거부하는 것과
    같은 결). 초안에 들어가는 모든 수치는 계산 함수 결과를 그대로 대입하며 LLM은 개입하지
    않는다(원칙1).
    """
    year = target_year or datetime.now(timezone.utc).year
    return build_application_draft(
        session, company_id, year, target_start_month, months=months
    )


@router.get("/{company_id}/carbon-point/applications/{application_id}")
def get_carbon_point_application(
    company_id: int, application_id: int, session: Session = Depends(get_session)
):
    """초안 단건 조회 — 다른 기업 소유는 404로 막는다(테넌트 경계, 기존 goal·documents 패턴)."""
    row = session.get(CarbonNeutralPointApplication, application_id)
    if row is None or row.company_id != company_id:
        raise HTTPException(status_code=404, detail="application not found")
    return {
        "application_id": row.id,
        "status": row.status,
        "baseline_year": row.baseline_year,
        "target_year": row.target_year,
        "baseline_usage_json": row.baseline_usage_json,
        "target_usage_json": row.target_usage_json,
        "reduction_rate_pct": row.reduction_rate_pct,
        "eligible": row.eligible,
        "draft_document_url": row.draft_document_url,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.patch("/{company_id}/carbon-point/applications/{application_id}")
def update_carbon_point_application(
    company_id: int,
    application_id: int,
    body: CarbonPointApplicationIn,
    session: Session = Depends(get_session),
):
    """사장님이 제출 이후 상태를 직접 갱신한다 — 감탄은 `draft`까지만 책임진다.

    실제 신청 접수는 사장님이 탄소중립포인트 포털에서 직접 하고(data-plan.md §3.2 범위 제한),
    승인·반려 결과도 감탄이 알 수 없으므로 수동 필드다. `draft`로 되돌리는 건 허용하지
    않는다 — 이미 제출한 사실을 지우는 셈이라 이력이 왜곡된다.
    """
    row = session.get(CarbonNeutralPointApplication, application_id)
    if row is None or row.company_id != company_id:
        raise HTTPException(status_code=404, detail="application not found")
    row.status = body.status
    session.commit()
    return {"application_id": row.id, "status": row.status}
