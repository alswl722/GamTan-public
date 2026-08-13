"""우대금리·설비금융 승인요청 큐 (v1 §6 2주차).

db/pcaf_quality.py::quality_upgrade_candidate은 "안내 후보" 여부를 계산만 할 뿐 저장하지
않는 읽기 전용 함수다. 여기서는 그 계산을 재사용해 사장님의 명시적 요청을
RateApprovalRequest 행으로 만들고, 은행 담당자의 승인/반려를 기록한다.

승인/반려는 여신 결정이 아니다(CLAUDE.md §9) — "우대금리 안내 대상으로 확인했다"는
은행 담당자의 수동 확인이며, 금리·여신 자동판정과 무관하다. 그래서 승인 응답에도
비보장 문구를 그대로 유지한다(원칙6 — 등급 상승·자격 보장 아님).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Company, RateApprovalRequest
from db.pcaf_quality import default_reporting_year
from db.rate_products import rate_product_status_for_scope

DISCLAIMER_TEXT = (
    "본 안내는 데이터 완전성 개선을 제안할 뿐 PCAF 등급 상승이나 우대금리·설비금융 "
    "자격을 보장하지 않습니다. 최종 승인은 은행 담당자가 별도 심사를 거쳐 결정합니다."
)


class CompanyNotFoundError(Exception):
    """company_id에 해당하는 기업이 없을 때."""


class NoUpgradeCandidateError(Exception):
    """해당 Scope에 활동자료(전표) 자체가 없어 요청 근거가 없을 때.

    "이미 최고 등급"은 더 이상 이 예외의 사유가 아니다 — db/rate_products.py 도입
    이후 이미 등급 조건을 충족한 상태도 "이미 대상" 요청으로 허용한다."""


class InvalidScopeError(Exception):
    """rate_upgrade 요청에 scope_group이 없거나 scope_1/scope_2가 아닐 때."""


class AlreadyProcessedError(Exception):
    """이미 처리된 요청을 다시 처리하려 할 때 — 새 decision이 이전과 같아도 예외다.

    이전엔 이미 처리된 요청에 같은 decision을 다시 보내면(예: A가 승인한 걸 B가 또
    승인) 조용히 200을 반환하며 req.reviewed_by가 A로 남아, B는 자기 처리가 반영된
    줄 착각할 수 있었다(리뷰 지적사항, PR #28). 항상 예외로 명확히 실패시킨다."""

    def __init__(self, request: "RateApprovalRequest"):
        self.request = request
        super().__init__(f"request_id={request.id}는 이미 {request.status} 처리됨")


def create_rate_request(
    session: Session,
    company_id: int,
    *,
    request_type: str = "rate_upgrade",
    scope_group: str | None = None,
    missing_summary: str | None = None,
) -> RateApprovalRequest:
    """사장님이 안내 카드를 보고 "요청" 버튼을 눌렀을 때 승인요청 큐에 항목을 만든다.

    current_grade/target_grade/missing_summary는 생성 시점 스냅샷 — 이후 재산정으로
    등급이 바뀌어도 요청 당시 근거가 감사 가능하게 그대로 남는다. disclaimer_text도
    생성 시점에 고정해 문구 정책이 바뀌어도 과거 요청은 요청 당시 그대로 보존된다.

    request_type="rate_upgrade"는 db/rate_products.py::rate_product_status_for_scope
    (정식 엔진 db/pcaf_quality.py 기준) 판정을 쓴다 — 한 기업이 Scope1·Scope2 각각
    독립적으로 후보일 수 있어 scope_group을 반드시 지정해야 한다. status가 "eligible"
    (이미 등급 조건 충족)이면 current_grade=target_grade로 스냅샷하고 matched_product_name을
    채운다 — "이미 대상"이어도 은행 확인을 요청할 수 있다. "upgrade_needed"면 기존과
    동일하게 목표 등급·결손 안내를 스냅샷한다. 이 경로는 missing_summary를 서버가
    계산하므로 인자로 받은 값은 무시한다.

    request_type="equipment_finance"(설비금융)는 등급 스냅샷 없이도 요청을 만들 수 있다
    — missing_summary는 호출부가 채운다(사장님 리포트의 K택소노미 리드 카드는
    db/k_taxonomy.py::k_taxonomy_leads_for_company의 설비유형·전표 원문으로 채워서 보낸다,
    그 외 자유 텍스트로 직접 채우는 경로도 계속 허용).
    """
    company = session.get(Company, company_id)
    if company is None:
        raise CompanyNotFoundError(f"company_id={company_id} 없음")

    if request_type == "rate_upgrade":
        if scope_group not in ("scope_1", "scope_2"):
            raise InvalidScopeError(
                f"scope_group은 scope_1|scope_2여야 함(전달값: {scope_group!r})"
            )
        year = default_reporting_year(session, company_id)
        status = rate_product_status_for_scope(session, company_id, year, scope_group)
        if status is None:
            raise NoUpgradeCandidateError(
                f"company_id={company_id} scope_group={scope_group} 활동자료 없음 "
                "— 우대금리 안내 요청 근거 없음"
            )
        if status["status"] == "eligible":
            req = RateApprovalRequest(
                company_id=company_id,
                request_type=request_type,
                scope_group=scope_group,
                current_grade=status["candidate_score"],
                target_grade=status["candidate_score"],
                missing_summary="이미 조건을 충족했어요 — 확인을 요청합니다",
                matched_product_name=", ".join(p["product_name"] for p in status["products"]),
                disclaimer_text=DISCLAIMER_TEXT,
            )
        else:
            req = RateApprovalRequest(
                company_id=company_id,
                request_type=request_type,
                scope_group=scope_group,
                current_grade=status["current_grade"],
                target_grade=status["target_grade"],
                missing_summary=status["missing"],
                disclaimer_text=DISCLAIMER_TEXT,
            )
    else:
        req = RateApprovalRequest(
            company_id=company_id,
            request_type=request_type,
            missing_summary=missing_summary,
            disclaimer_text=DISCLAIMER_TEXT,
        )

    session.add(req)
    session.commit()
    return req


def list_rate_requests(session: Session, *, status: str | None = None) -> list[RateApprovalRequest]:
    stmt = select(RateApprovalRequest).order_by(RateApprovalRequest.created_at.desc())
    if status:
        stmt = stmt.where(RateApprovalRequest.status == status)
    return list(session.execute(stmt).scalars().all())


def review_rate_request(
    session: Session,
    request_id: int,
    *,
    decision: str,
    reviewed_by: str,
    note: str | None = None,
) -> RateApprovalRequest | None:
    """승인/반려 처리 — 이미 처리된 요청은 재처리하지 않는다(멱등 조치 방지, 상태 이력 보존).

    decision: "approved" | "rejected". 승인도 여신 결정이 아니라 안내 대상 확정
    수동 확인일 뿐이라 disclaimer_text는 건드리지 않는다 — 이미 생성 시점에 고정됨.

    이미 처리된 요청이면 새 decision이 이전과 같든 다르든 항상 AlreadyProcessedError를
    던진다 — 원래 처리자(reviewed_by)를 그대로 보존하고, 두 번째 호출자에게는 자기
    처리가 반영되지 않았음을 명확히 알린다.
    """
    req = session.get(RateApprovalRequest, request_id)
    if req is None:
        return None
    if req.status != "pending":
        raise AlreadyProcessedError(req)

    req.status = decision
    req.reviewed_by = reviewed_by
    req.reviewed_at = datetime.now(timezone.utc)
    req.review_note = note
    session.commit()
    return req
