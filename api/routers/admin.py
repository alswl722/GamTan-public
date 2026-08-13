"""관리자 API — 은행 ESG·여신 담당자용 대시보드 데이터 소스.

- GET   /admin/portfolio                      포트폴리오 금융배출량 집계 + PCAF 등급 분포
- GET   /admin/companies/{id}/overview        기업 상세 탭 — 등급·결손·HITL대기·최근알림 요약
- GET   /admin/hitl                           전 기업 담당자 검토 큐 (저신뢰 분류 건)
- PATCH /admin/classifications/{id}/confirm   그대로 확정
- PATCH /admin/classifications/{id}           분류 수정 후 확정 (담당자 교정)
- PATCH /admin/classifications/{id}/reject    반려 — 집계에서 제외
- GET   /admin/traces                         에이전트 실행 이력 목록 (드릴다운은 /trace/{sid})
- PATCH /admin/classifications/bulk-confirm   여러 건 일괄 확정 (건별 성공/실패 반환)
- PATCH /admin/classifications/bulk-reject    여러 건 일괄 반려 (건별 성공/실패 반환)
- GET   /admin/review-log                     담당자 조치 이력(감사 로그) — evidence 누적 기록을 노출
                                               (page/page_size/company_name 서버사이드 페이지네이션)
- GET   /admin/documents/{id}                 원본문서 열람 (조회 시 접근 로그 자동 기록)
- GET   /admin/documents/{id}/file            원본문서 파일 바이너리 (PDF, 조회 시 접근 로그 자동 기록)
- GET   /admin/documents/access-log           원본문서 접근 감사 로그 목록 (page/page_size/company_name)
- GET   /admin/audit-package                  감사 대응 근거 패키지 — 기업·기간 지정 시계열 원자료(JSON/CSV/PDF)

여신 결정·스코어링은 하지 않는다(CLAUDE.md §9). AI가 1차 스크리닝한 저신뢰 건을
사람이 최종 확정하는 HITL 마감만 담당 — 금융분야 AI 가이드라인의 보조수단성 구현.
모든 담당자 조치는 evidence 에 감사 로그로 남긴다(설명가능성 원칙).
"""
import csv
import io
import os
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.db import get_session
from api.document_ingestion import REPO_ROOT
from api.queries import get_coverage, get_emission_factors, get_hitl_queue, get_unit_prices
from db.alerts import detect_alerts
from db.calc_engine import CalcDataGap, ClassifiedItemInput, compute_emission, \
    index_emission_factors, index_unit_prices
from db.audit_package import build_audit_package
from db.audit_report_pdf import build_audit_report_pdf
from db.document_access_log import access_history, record_access, recent_access_log
from db.models import Classification, Company, SourceDocument, TraceLog, Voucher
from db.pcaf import company_pcaf_summary, portfolio_summary

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


@router.get("/companies/{company_id}/overview")
def company_overview(company_id: int, session: Session = Depends(get_session)):
    """기업 상세 탭 — 등급·측정 여부·결손·HITL 대기·최근 알림을 한 응답으로 묶는다.

    실행 이력(traces)·변경 이력(review-log)·문서 열람(access-log)·품질 이슈는
    각자 페이지네이션이 있는 기존 엔드포인트를 프론트가 company_id로 필터해
    재사용한다 — 여기서는 그 자체로 계산이 필요한 항목만 담아 중복 로직을
    만들지 않는다.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"company_id={company_id} 없음")

    summary = company_pcaf_summary(session, company_id)
    after = summary["after"]
    used = after or summary["before"]

    hitl_count = session.execute(
        select(func.count(Classification.id))
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id, Classification.status == "review_required")
    ).scalar_one()

    return {
        "company_id": company.id,
        "company_name": company.name,
        "industry_name": company.industry_name,
        "grade": used["grade"],
        "measured": after is not None,
        "scope1": round(used.get("scope1", 0.0) or 0.0, 2),
        "scope2": round(used.get("scope2", 0.0) or 0.0, 2),
        "hitl_count": hitl_count,
        "coverage": get_coverage(session, company_id),
        "alerts": detect_alerts(session, company_id=company_id),
    }


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
def review_log(
    page: int = 1,
    page_size: int = 50,
    company_name: str | None = None,
    session: Session = Depends(get_session),
):
    """담당자 조치 이력(감사 로그) — 확정/반려된 건을 최근 조치순으로.

    별도 감사 테이블을 새로 두지 않는다 — confirm/edit/reject 가 이미 evidence 에
    "무엇을 했는지"를 원본 판단 근거 뒤에 누적해서 남긴다(설계 원칙: 모든 판단에
    evidence 저장). 이 엔드포인트는 그 기록을 조회용으로 노출만 한다.

    company_name을 넘기면 기업명 부분일치(대소문자 무시)로 필터한다. total은
    필터 적용 후 전체 건수 — 프론트가 "N건 중 M~K" 페이지 표시에 쓴다.
    """
    base = (
        select(Classification, Voucher, Company)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .join(Company, Voucher.company_id == Company.id)
        .where(Classification.reviewed_at.isnot(None))
    )
    if company_name:
        base = base.where(Company.name.ilike(f"%{company_name}%"))

    total = session.execute(
        select(func.count()).select_from(base.with_only_columns(Classification.id).subquery())
    ).scalar_one()

    stmt = (
        base.order_by(Classification.reviewed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
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
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
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
    session_id별 메시지는 별도 재조회 없이 아래 한 쿼리 결과를 Python에서
    그룹핑해 만든다(세션 수만큼 쿼리가 반복되던 N+1 제거).
    """
    rows = session.execute(
        select(
            TraceLog.session_id,
            TraceLog.company_id,
            Company.name,
            TraceLog.created_at,
            TraceLog.message,
        )
        .join(Company, Company.id == TraceLog.company_id)
        .order_by(TraceLog.session_id, TraceLog.created_at)
    ).all()

    grouped: dict[str, dict] = {}
    for sid, company_id, company_name, created_at, message in rows:
        g = grouped.setdefault(sid, {
            "company_id": company_id,
            "company_name": company_name,
            "ran_at": created_at,
            "step_count": 0,
            "messages": [],
        })
        if created_at is not None and (g["ran_at"] is None or created_at < g["ran_at"]):
            g["ran_at"] = created_at
        g["step_count"] += 1
        g["messages"].append(message or "")

    runs = []
    for sid, g in grouped.items():
        blob = " ".join(g["messages"])

        badges = [label for needle, label in _BADGE_RULES if needle in blob]
        # 실행 중단은 오케스트레이터가 예외 시 남기는 문구 — 그 외는 완료로 본다
        failed = "실행 중단" in blob
        if not badges and not failed:
            badges = ["정상"]

        runs.append({
            "session_id": sid,
            "company_id": g["company_id"],
            "company_name": g["company_name"],
            "ran_at": g["ran_at"].isoformat() if g["ran_at"] else None,
            "step_count": g["step_count"],
            "status": "실패" if failed else "완료",
            "result_badges": badges,
        })
    runs.sort(key=lambda r: r["ran_at"] or "", reverse=True)
    return {"runs": runs}


# ── 원본문서 열람 + 접근 감사 로그 ───────────────────────────────────────────
# 주의: "/documents/access-log"가 "/documents/{document_id}"보다 먼저 등록돼야 한다.
# FastAPI는 등록 순서대로 매칭하므로, {document_id}가 먼저면 "access-log"라는
# 문자열이 document_id로 잘못 파싱 시도된다.

@router.get("/documents/access-log")
def document_access_log(
    page: int = 1,
    page_size: int = 50,
    company_name: str | None = None,
    session: Session = Depends(get_session),
):
    """전체 원본문서 열람 이력 — 최근 순."""
    return recent_access_log(session, page=page, page_size=page_size, company_name=company_name)


@router.get("/documents/{document_id}")
def view_document(
    document_id: int, viewed_by: str, session: Session = Depends(get_session)
):
    """원본문서 열람 — 조회할 때마다 접근 로그를 남긴다(v1 §6 2주차).

    viewed_by는 쿼리 파라미터로 받는다(별도 인증 체계 미도입). 열람 자체는 조치가
    아니므로 별도 confirm 없이 GET 시점에 즉시 기록한다.
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


@router.get("/documents/{document_id}/file")
def download_document_file(
    document_id: int, viewed_by: str, session: Session = Depends(get_session)
):
    """원본문서 파일 바이너리 — <iframe>/<embed>가 직접 src로 거는 엔드포인트.

    view_document(메타데이터 JSON)와 분리한다 — 브라우저가 PDF를 렌더링하려면
    이 URL을 그대로 src에 꽂아야 하므로 JSON을 반환하는 엔드포인트와 섞지 않는다.
    열람 시점에 즉시 접근 로그를 남기는 관례는 view_document와 동일.
    """
    doc = session.get(SourceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document_id={document_id} 없음")
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="원본 파일이 저장되어 있지 않습니다")

    abs_path = os.path.normpath(os.path.join(REPO_ROOT, doc.file_path))
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다")

    record_access(session, document_id, viewed_by)

    # filename= 인자를 쓰면 FileResponse가 Content-Disposition: attachment로 강제해
    # 브라우저가 다운로드를 시도한다 — <iframe>이 인라인 렌더링하도록 명시적으로
    # inline을 지정한다. HTTP 헤더는 latin-1만 허용해 한글 파일명을 그대로 못
    # 넣으므로, filename*=UTF-8''(RFC 6266) 형식으로 퍼센트 인코딩한다.
    display_name = quote(doc.original_filename or "document.pdf")
    return FileResponse(
        abs_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{display_name}"},
    )


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
    시계열로 묶어 반환한다. format=csv는 원자료 재검증용, format=pdf는 서술형
    감사보고서(요약 통계 + 판단 근거 시계열 표)를 내려준다. 둘 다 build_audit_package()가
    만든 package를 그대로 직렬화할 뿐 재계산하지 않는다.
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

    if format == "pdf":
        pdf_bytes = build_audit_report_pdf(package, company.name)
        filename = f"audit-report-{company_id}-{year}.pdf"
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return package
