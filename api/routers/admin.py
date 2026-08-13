"""관리자 API — 은행 ESG·여신 담당자용 대시보드 데이터 소스.

- GET   /admin/portfolio                      포트폴리오 금융배출량 집계 + PCAF 등급 분포
- GET   /admin/rate-candidates                 등급 상승 역산 후보 (우대금리 자격 안내)
- GET   /admin/k-taxonomy-leads                K택소노미·설비투자 리드 목록 (녹색여신·설비금융 안내 대상)
- GET   /admin/hitl                           전 기업 담당자 검토 큐 (저신뢰 분류 건)
- PATCH /admin/classifications/{id}/confirm   그대로 확정
- PATCH /admin/classifications/{id}           분류 수정 후 확정 (담당자 교정)
- PATCH /admin/classifications/{id}/reject    반려 — 집계에서 제외
- GET   /admin/traces                         에이전트 실행 이력 목록 (드릴다운은 /trace/{sid})
- PATCH /admin/classifications/bulk-confirm   여러 건 일괄 확정 (건별 성공/실패 반환)
- PATCH /admin/classifications/bulk-reject    여러 건 일괄 반려 (건별 성공/실패 반환)
- GET   /admin/review-log                     담당자 조치 이력(감사 로그) — evidence 누적 기록을 노출
- GET   /admin/rate-requests                  승인요청 큐 (우대금리·설비금융 — HITL과 분리된 별도 큐)
- PATCH /admin/rate-requests/{id}/approve     승인요청 승인 (여신 결정 아님 — 안내 대상 확정)
- PATCH /admin/rate-requests/{id}/reject      승인요청 반려
- GET   /admin/documents/{id}                 원본문서 열람 (조회 시 접근 로그 자동 기록)
- GET   /admin/documents/access-log           원본문서 접근 감사 로그 목록
- GET   /admin/quality-issues                 품질 이슈 로그 — 업로드 반려·실패 이력 (열람 전용)
- GET   /admin/audit-package                  감사 대응 근거 패키지 — 기업·기간 지정 시계열 원자료 CSV

여신 결정·스코어링은 하지 않는다(CLAUDE.md §9). AI가 1차 스크리닝한 저신뢰 건을
사람이 최종 확정하는 HITL 마감만 담당 — 금융분야 AI 가이드라인의 보조수단성 구현.
모든 담당자 조치는 evidence 에 감사 로그로 남긴다(설명가능성 원칙).

HITL 큐(분류 신뢰도 기준 — /admin/hitl)와 승인요청 큐(우대금리·설비금융 안내 —
/admin/rate-requests)는 서로 다른 데이터·화면이다(v1 §6 2주차). 승인요청의 "승인"도
여신 결정이 아니라 "안내 대상으로 확인했다"는 은행 담당자의 수동 확인일 뿐이며,
응답에는 항상 비보장 문구(disclaimer_text)가 동반된다(원칙6).
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.db import get_session
from api.queries import get_emission_factors, get_hitl_queue, get_unit_prices
from db.alerts import detect_alerts
from db.calc_engine import CalcDataGap, ClassifiedItemInput, compute_emission, \
    index_emission_factors, index_unit_prices
from db.audit_package import build_audit_package
from db.document_access_log import access_history, record_access, recent_access_log
from db.k_taxonomy import k_taxonomy_leads
from db.models import Classification, Company, SourceDocument, TraceLog, Voucher
from db.pcaf import portfolio_summary
from db.pcaf_quality import quality_rate_upgrade_candidates
from db.quality_issues import list_ingestion_failures
from db.rate_approvals import AlreadyProcessedError, list_rate_requests, review_rate_request

router = APIRouter(prefix="/admin", tags=["admin"])


class ClassificationEdit(BaseModel):
    """담당자 교정 입력 — 분류 필드만. 금액·물량은 담당자가 못 바꾼다(전표가 원본)."""

    scope: int | None = None
    category: str | None = None
    fuel_type: str | None = None


class BulkAction(BaseModel):
    """일괄 처리 대상 전표 ID 목록."""

    voucher_ids: list[int]


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)):
    """거래 기업 전체의 Scope 1/2 합산 + PCAF 등급 분포 + 기업별 내역."""
    return portfolio_summary(session)


@router.get("/rate-candidates")
def rate_candidates(session: Session = Depends(get_session)):
    """등급 상승 후보 — 정식 엔진(db/pcaf_quality.py) 기준 Scope별 독립 판정.

    기업마다 최대 2행(Scope1·Scope2 각각)이 나올 수 있다. 여신 결정은 하지 않는다
    (CLAUDE.md §9) — 우대금리 자격 '안내'까지만 담당.
    """
    return {"candidates": quality_rate_upgrade_candidates(session)}


@router.get("/k-taxonomy-leads")
def k_taxonomy_leads_endpoint(session: Session = Depends(get_session)):
    """K택소노미·설비투자 리드 목록 — 전 기업에서 finance_lead_type이 채워진 분류 건.

    여신 결정이 아니라 안내 대상 목록이다(CLAUDE.md §9). 정렬은 데이터 완전성만
    사용한다(원칙7).
    """
    return {"leads": k_taxonomy_leads(session)}


@router.get("/hitl")
def hitl_queue(session: Session = Depends(get_session)):
    """전 기업의 담당자 검토 대기 건(status='review_required')."""
    return {"queue": get_hitl_queue(session)}


@router.get("/alerts")
def alerts(session: Session = Depends(get_session)):
    """이상 신호 알림 — 전 기업 배출량 추세 급변·데이터 공백을 스캔(결정론적 계산).

    급등/급감 판정은 코드가 배수로 계산하고, 여신 결정은 하지 않는다(CLAUDE.md §9).
    담당자가 조짐을 먼저 인지하도록 안내하는 조기 경보일 뿐이다.
    """
    return {"alerts": detect_alerts(session)}


def _load_reviewable(session: Session, voucher_id: int) -> Classification:
    """검토 대기 상태의 분류를 가져온다 — 아니면 404/409."""
    obj = session.query(Classification).filter_by(voucher_id=voucher_id).one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"voucher_id={voucher_id} 분류 없음")
    if obj.status != "review_required":
        raise HTTPException(
            status_code=409,
            detail=f"처리 불가 — 현재 상태 '{obj.status}' (검토필요 건만 가능)",
        )
    return obj


def _append_evidence(obj: Classification, note: str) -> None:
    """판단 근거에 담당자 조치를 덧붙인다 — 원본 근거를 지우지 않는다(감사 추적)."""
    obj.evidence = f"{obj.evidence or ''} | {note}".lstrip(" |")


@router.patch("/classifications/{voucher_id}/confirm")
def confirm_classification(voucher_id: int, session: Session = Depends(get_session)):
    """수정 없이 확정 — status: review_required → confirmed.

    분류 내용(scope/category)은 그대로 두고 '사람이 확인했다'만 기록한다.
    AI가 값을 바꾸는 게 아니라 사람이 판정을 마감하는 것(보조수단성).
    """
    obj = _load_reviewable(session, voucher_id)
    obj.status = "confirmed"
    obj.reviewed_at = datetime.now(timezone.utc)
    _append_evidence(obj, "담당자 확정(수정 없음)")
    session.commit()
    return {"voucher_id": voucher_id, "status": obj.status}


def _bulk_apply(session: Session, voucher_ids: list[int], new_status: str, note: str) -> list[dict]:
    """여러 건에 동일 조치를 적용 — 한 건 실패해도 나머지는 계속 처리한다(부분 실패 가시성).

    ⚠️ 이 라우트는 반드시 `PATCH /classifications/{voucher_id}` 보다 먼저 등록돼야 한다 —
    안 그러면 "bulk-confirm" 문자열이 {voucher_id}(int) 로 파싱 시도되어 422로 막힌다.
    """
    results = []
    for vid in voucher_ids:
        try:
            obj = _load_reviewable(session, vid)
        except HTTPException as e:
            session.rollback()
            results.append({"voucher_id": vid, "ok": False, "error": e.detail})
            continue
        obj.status = new_status
        obj.reviewed_at = datetime.now(timezone.utc)
        _append_evidence(obj, note)
        session.commit()
        results.append({"voucher_id": vid, "ok": True})
    return results


@router.patch("/classifications/bulk-confirm")
def bulk_confirm(payload: BulkAction, session: Session = Depends(get_session)):
    """선택한 여러 건을 수정 없이 일괄 확정. 건별 성공/실패를 그대로 반환한다."""
    return {"results": _bulk_apply(session, payload.voucher_ids, "confirmed", "담당자 일괄 확정(수정 없음)")}


@router.patch("/classifications/bulk-reject")
def bulk_reject(payload: BulkAction, session: Session = Depends(get_session)):
    """선택한 여러 건을 일괄 반려 — 집계에서 제외. 건별 성공/실패를 그대로 반환한다."""
    return {
        "results": _bulk_apply(
            session, payload.voucher_ids, "rejected", "담당자 일괄 반려 — 분류 신뢰 불가, 집계 제외"
        )
    }


@router.patch("/classifications/{voucher_id}")
def edit_classification(
    voucher_id: int,
    edit: ClassificationEdit,
    session: Session = Depends(get_session),
):
    """담당자가 분류를 교정한 뒤 확정 — AI 1차 판정을 사람이 덮어쓴다.

    바뀐 필드는 evidence 에 '무엇을 무엇으로' 남기고, 연료·scope 가 바뀌면
    배출량을 재계산한다. 계산은 기존 결정론적 엔진(compute_emission)만 사용 —
    LLM 산수 금지 원칙 유지.
    """
    obj = _load_reviewable(session, voucher_id)

    changes = []
    if edit.scope is not None and edit.scope != obj.scope:
        changes.append(f"Scope {obj.scope}→{edit.scope}")
        obj.scope = edit.scope
    if edit.category is not None and edit.category != obj.category:
        changes.append(f"카테고리 {obj.category}→{edit.category}")
        obj.category = edit.category
    if edit.fuel_type is not None and edit.fuel_type != obj.fuel_type:
        changes.append(f"연료 {obj.fuel_type}→{edit.fuel_type}")
        obj.fuel_type = edit.fuel_type

    recalculated = _recalculate(session, obj)

    obj.status = "confirmed"
    obj.reviewed_at = datetime.now(timezone.utc)
    _append_evidence(
        obj,
        f"담당자 수정: {', '.join(changes)}" if changes else "담당자 확정(수정 없음)",
    )
    session.commit()
    return {
        "voucher_id": voucher_id,
        "status": obj.status,
        "changes": changes,
        "recalculated": recalculated,
        "emission_co2e": obj.emission_co2e,
    }


def _recalculate(session: Session, obj: Classification) -> bool:
    """교정된 분류로 배출량 재계산. 계산 불가(단가 없음/연료 불명)면 0으로 두고 False."""
    voucher = session.get(Voucher, obj.voucher_id)
    if voucher is None or not obj.fuel_type:
        return False
    raw = voucher.raw_json or {}
    try:
        item = ClassifiedItemInput(
            fuel_type=obj.fuel_type,
            scope=obj.scope,
            amount_krw=float(obj.amount_krw or voucher.supply_amount_krw or 0),
            year=int(voucher.year),
            month=int(voucher.month),
            quantity=raw.get("quantity"),
            quantity_unit=raw.get("quantity_unit"),
        )
        result = compute_emission(
            item,
            index_unit_prices(get_unit_prices(session)),
            index_emission_factors(get_emission_factors(session)),
        )
    except (CalcDataGap, ValueError):
        # 담당자 교정 결과가 계산 불가여도 확정은 유지 — 숫자만 비운다(추정 금지)
        obj.activity_amount = None
        obj.activity_unit = None
        obj.emission_co2e = 0.0
        return False

    if result.get("skipped") or result.get("needs_review"):
        obj.activity_amount = None
        obj.activity_unit = None
        obj.emission_co2e = 0.0
        return False

    obj.activity_amount = result.get("activity_amount")
    obj.activity_unit = result.get("activity_unit")
    obj.emission_co2e = result.get("emission_co2e") or 0.0
    return True


@router.patch("/classifications/{voucher_id}/reject")
def reject_classification(voucher_id: int, session: Session = Depends(get_session)):
    """반려 — 분류를 신뢰할 수 없다는 판정. status='rejected' 로 집계에서 제외한다.

    값을 지우지 않고 상태만 바꾼다(원본 보존 = 감사 가능).
    """
    obj = _load_reviewable(session, voucher_id)
    obj.status = "rejected"
    obj.reviewed_at = datetime.now(timezone.utc)
    _append_evidence(obj, "담당자 반려 — 분류 신뢰 불가, 집계 제외")
    session.commit()
    return {"voucher_id": voucher_id, "status": obj.status}


@router.get("/review-log")
def review_log(session: Session = Depends(get_session)):
    """담당자 조치 이력(감사 로그) — 확정/반려된 건을 최근 조치순으로.

    별도 감사 테이블을 새로 두지 않는다 — confirm/edit/reject 가 이미 evidence 에
    "무엇을 했는지"를 원본 판단 근거 뒤에 누적해서 남긴다(설계 원칙: 모든 판단에
    evidence 저장). 이 엔드포인트는 그 기록을 조회용으로 노출만 한다.
    """
    stmt = (
        select(Classification, Voucher, Company)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .join(Company, Voucher.company_id == Company.id)
        .where(Classification.reviewed_at.isnot(None))
        .order_by(Classification.reviewed_at.desc())
        .limit(300)
    )
    rows = session.execute(stmt).all()
    return {
        "entries": [
            {
                "voucher_id": v.id,
                "company_name": co.name,
                "raw": v.item_description,
                "month": v.month,
                "status": c.status,
                "evidence": c.evidence,
                "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
            }
            for c, v, co in rows
        ]
    }


# 실행 이력 메시지에서 결과 배지를 뽑는 규칙 — 트레이스 문구와 1:1로 맞춰둔다.
_BADGE_RULES = (
    ("비어있네요", "결손 발견"),
    ("왜 그런지 다시 확인해볼게요", "이상치"),
    ("다시 확인하다가 막혔어요", "재검증 실패"),
)


@router.get("/traces")
def trace_runs(session: Session = Depends(get_session)):
    """에이전트 실행 이력 목록 — session_id 단위로 묶어 최신순.

    드릴다운(스텝 타임라인)은 기존 GET /trace/{session_id} 를 그대로 쓴다.
    """
    rows = session.execute(
        select(
            TraceLog.session_id,
            TraceLog.company_id,
            Company.name,
            func.min(TraceLog.created_at).label("ran_at"),
            func.count(TraceLog.id).label("step_count"),
        )
        .join(Company, Company.id == TraceLog.company_id)
        .group_by(TraceLog.session_id, TraceLog.company_id, Company.name)
        .order_by(func.min(TraceLog.created_at).desc())
    ).all()

    runs = []
    for sid, company_id, company_name, ran_at, step_count in rows:
        messages = session.execute(
            select(TraceLog.message).where(TraceLog.session_id == sid)
        ).scalars().all()
        blob = " ".join(m or "" for m in messages)

        badges = [label for needle, label in _BADGE_RULES if needle in blob]
        # 실행 중단은 오케스트레이터가 예외 시 남기는 문구 — 그 외는 완료로 본다
        failed = "실행 중단" in blob
        if not badges and not failed:
            badges = ["정상"]

        runs.append({
            "session_id": sid,
            "company_id": company_id,
            "company_name": company_name,
            "ran_at": ran_at.isoformat() if ran_at else None,
            "step_count": int(step_count),
            "status": "실패" if failed else "완료",
            "result_badges": badges,
        })
    return {"runs": runs}


# ── 승인요청 큐 (우대금리·설비금융) — HITL 큐와 분리된 별도 데이터·화면 ──────────

class ReviewDecision(BaseModel):
    """승인/반려 처리자·비고. 아직 별도 인증 체계가 없어 문자열로 직접 받는다
    (기존 review-log가 evidence 문자열로 조치자를 남기는 것과 같은 관례)."""

    reviewed_by: str
    note: str | None = None


def _serialize_rate_request(req) -> dict:
    return {
        "id": req.id,
        "company_id": req.company_id,
        "request_type": req.request_type,
        "scope_group": req.scope_group,
        "current_grade": req.current_grade,
        "target_grade": req.target_grade,
        "missing_summary": req.missing_summary,
        "disclaimer_text": req.disclaimer_text,
        "status": req.status,
        "reviewed_by": req.reviewed_by,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "review_note": req.review_note,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


@router.get("/rate-requests")
def rate_requests(status: str | None = None, session: Session = Depends(get_session)):
    """승인요청 큐 — 사장님이 우대금리/설비금융 안내를 요청한 건.

    HITL 큐(분류 신뢰도)와 별개 데이터다 — GET /admin/hitl과 혼동하지 말 것.
    """
    requests = list_rate_requests(session, status=status)
    company_names = {
        c.id: c.name
        for c in session.execute(select(Company)).scalars().all()
    }
    return {
        "requests": [
            {**_serialize_rate_request(r), "company_name": company_names.get(r.company_id)}
            for r in requests
        ]
    }


@router.patch("/rate-requests/{request_id}/approve")
def approve_rate_request(
    request_id: int, decision: ReviewDecision, session: Session = Depends(get_session)
):
    """승인 — 여신 결정이 아니라 "안내 대상으로 확인했다"는 담당자 수동 확인(CLAUDE.md §9).
    응답에는 항상 disclaimer_text(비보장 문구)가 동반된다(원칙6).

    이미 처리된 요청은 새 decision이 이전과 같아도(예: 이미 승인된 걸 다시 승인) 항상
    409다 — 원래 처리자 정보를 조용히 덮어쓰지 않고, 두 번째 호출자에게 자기 처리가
    반영되지 않았음을 명확히 알린다(리뷰 지적사항, PR #28).
    """
    try:
        req = review_rate_request(
            session, request_id, decision="approved",
            reviewed_by=decision.reviewed_by, note=decision.note,
        )
    except AlreadyProcessedError as e:
        raise HTTPException(status_code=409, detail=f"이미 {e.request.status} 처리된 요청입니다")
    if req is None:
        raise HTTPException(status_code=404, detail=f"request_id={request_id} 없음")
    return _serialize_rate_request(req)


@router.patch("/rate-requests/{request_id}/reject")
def reject_rate_request(
    request_id: int, decision: ReviewDecision, session: Session = Depends(get_session)
):
    """반려 — 사유는 review_note에 남긴다. 이미 처리된 요청은 항상 409(approve와 동일 규칙)."""
    try:
        req = review_rate_request(
            session, request_id, decision="rejected",
            reviewed_by=decision.reviewed_by, note=decision.note,
        )
    except AlreadyProcessedError as e:
        raise HTTPException(status_code=409, detail=f"이미 {e.request.status} 처리된 요청입니다")
    if req is None:
        raise HTTPException(status_code=404, detail=f"request_id={request_id} 없음")
    return _serialize_rate_request(req)


# ── 원본문서 열람 + 접근 감사 로그 ───────────────────────────────────────────
# 주의: "/documents/access-log"가 "/documents/{document_id}"보다 먼저 등록돼야 한다.
# FastAPI는 등록 순서대로 매칭하므로, {document_id}가 먼저면 "access-log"라는
# 문자열이 document_id로 잘못 파싱 시도된다.

@router.get("/documents/access-log")
def document_access_log(session: Session = Depends(get_session)):
    """전체 원본문서 열람 이력 — 최근 순."""
    return {"entries": recent_access_log(session)}


@router.get("/documents/{document_id}")
def view_document(
    document_id: int, viewed_by: str, session: Session = Depends(get_session)
):
    """원본문서 열람 — 조회할 때마다 접근 로그를 남긴다(v1 §6 2주차).

    viewed_by는 쿼리 파라미터로 받는다(별도 인증 체계 미도입 — 위 ReviewDecision과
    같은 관례). 열람 자체는 조치가 아니므로 별도 confirm 없이 GET 시점에 즉시 기록한다.
    """
    doc = session.get(SourceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document_id={document_id} 없음")

    record_access(session, document_id, viewed_by)

    return {
        "id": doc.id,
        "company_id": doc.company_id,
        "document_type": doc.document_type,
        "original_filename": doc.original_filename,
        "document_date": doc.document_date.isoformat() if doc.document_date else None,
        "extracted_json": doc.extracted_json,
        "verification_status": doc.verification_status,
        "access_history": [
            {"accessed_by": a.accessed_by, "accessed_at": a.accessed_at.isoformat() if a.accessed_at else None}
            for a in access_history(session, document_id)
        ],
    }


# ── 품질 이슈 로그 (v1 Tier 2, owner-admin-flow-spec.md §7) ────────────────────

@router.get("/quality-issues")
def quality_issues(session: Session = Depends(get_session)):
    """업로드 반려·실패 이력 — 열람 전용. 성공한 업로드는 여기 안 남는다
    (SourceDocument로 이미 남으므로). 실패만 원인별로 모아 보여준다."""
    return {"issues": list_ingestion_failures(session)}


# ── 감사 대응 근거 패키지 (v1 Tier 2, owner-admin-flow-spec.md §8) ──────────────

@router.get("/audit-package")
def audit_package(
    company_id: int,
    year: int,
    month_from: int = 1,
    month_to: int = 12,
    format: str = "json",
    session: Session = Depends(get_session),
):
    """기업·기간을 지정하면 trace_logs + classifications.evidence + 원본 전표를
    시계열로 묶어 반환한다. format=csv면 원자료 재검증용 CSV로 내려준다
    (서술형 PDF 감사보고서는 별도 범위, 이번엔 미구현).
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"company_id={company_id} 없음")

    package = build_audit_package(session, company_id, year, month_from, month_to)

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "entry_type", "occurred_at", "voucher_id", "year", "month",
                "item_description", "supply_amount_krw", "scope", "fuel_type",
                "emission_co2e", "status", "evidence", "session_id", "step_type",
                "tool_name", "message",
            ],
        )
        writer.writeheader()
        for entry in package["entries"]:
            writer.writerow({k: entry.get(k, "") for k in writer.fieldnames})
        buffer.seek(0)
        filename = f"audit-package-{company_id}-{year}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return package
