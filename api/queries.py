"""공용 DB 조회 헬퍼 — Mock API·에이전트 도구·trace 라우터가 공통 재사용.

여기 모아두면 "전표/분포를 DB에서 꺼내는" 로직이 한 곳에만 존재한다.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.document_requirements import required_documents
from db.models import (
    Classification,
    Company,
    InstitutionBorrower,
    SourceDocument,
    TraceLog,
    Voucher,
    IndustryDistribution,
    EmissionFactor,
    UnitPrice,
)


# 커버리지 매트릭스용 — 품목 텍스트를 연료 대분류로 러프하게 묶는다.
# (정밀 분류는 도구②(LLM)가 하고, 여기선 결손 감지용 대분류만.)
def _fuel_class(item: str) -> str:
    t = item or ""
    if any(k in t for k in ("전기", "전력", "한전", "한국전력", "kWh")):
        return "전기"
    if "가스" in t or "LNG" in t:
        return "가스"
    if any(k in t for k in ("경유", "유류", "난방유", "휘발유", "지게차", "디젤", "주유")):
        return "경유/유류"
    return "기타"


def _voucher_dict(v: Voucher) -> dict:
    return {
        "voucher_id": v.id,
        "source": v.source,
        "year": v.year,
        "month": v.month,
        "issue_date": v.issue_date.isoformat() if v.issue_date else None,
        "supplier_name": v.supplier_name,
        "item_description": v.item_description,
        "supply_amount_krw": int(v.supply_amount_krw) if v.supply_amount_krw is not None else None,
    }


def get_vouchers(session: Session, company_id: int, source: str | None = None) -> list[dict]:
    stmt = select(Voucher).where(Voucher.company_id == company_id)
    if source:
        stmt = stmt.where(Voucher.source == source)
    stmt = stmt.order_by(Voucher.month, Voucher.issue_date)
    rows = session.execute(stmt).scalars().all()
    return [_voucher_dict(v) for v in rows]


def _selected_coverage_fuels(fuel_types: dict | None) -> set[str] | None:
    """companies.fuel_types_json → get_coverage 결손 판정에 쓸 연료 대분류 집합.

    None(연료 체크 전 상태)이면 필터를 걸지 않는다 — 기존 결손 감지 동작을
    그대로 유지해 데모 시나리오(3~5월 가스 결손)가 회귀되지 않게 한다
    (v1-plan.md 원칙 #8 — "체크하지 않은 연료의 결손은 알림 대상에서 제외").
    """
    if fuel_types is None:
        return None
    selected: set[str] = set()
    if fuel_types.get("electricity", True):
        selected.add("전기")
    if fuel_types.get("city_gas"):
        selected.add("가스")
    if fuel_types.get("diesel") or fuel_types.get("gasoline") or fuel_types.get("lpg") in ("yes", "unsure"):
        selected.add("경유/유류")
    return selected


def get_coverage(session: Session, company_id: int) -> dict:
    """월(1~12) × 연료 대분류 존재 여부 매트릭스 + 결손 목록.

    에이전트가 "3~5월 가스가 0건이네?"를 스스로 관찰하는 재료. matrix는 체크
    여부와 무관하게 전체를 반환하고(참고용), gaps만 선택된 연료로 필터한다.
    """
    vouchers = get_vouchers(session, company_id)
    fuels = ["전기", "가스", "경유/유류"]
    matrix = {f: {m: 0 for m in range(1, 13)} for f in fuels}
    for v in vouchers:
        fc = _fuel_class(v["item_description"])
        if fc in matrix:
            matrix[fc][v["month"]] += 1

    company = session.get(Company, company_id)
    selected_fuels = _selected_coverage_fuels(company.fuel_types_json if company else None)

    gaps = []
    for f in fuels:
        if selected_fuels is not None and f not in selected_fuels:
            continue
        missing = [m for m in range(1, 13) if matrix[f][m] == 0]
        if missing:
            gaps.append({"fuel": f, "missing_months": missing})
    return {"matrix": matrix, "gaps": gaps}


def get_emission_factors(session: Session) -> list[EmissionFactor]:
    """배출계수 전량 — 계산 엔진 index_emission_factors 입력 (테이블 작음)."""
    return session.execute(select(EmissionFactor)).scalars().all()


def get_unit_prices(session: Session) -> list[UnitPrice]:
    """환산단가 전량(연료×12개월) — 계산 엔진 index_unit_prices 입력."""
    return session.execute(select(UnitPrice)).scalars().all()


def get_classifications(session: Session, company_id: int) -> list[dict]:
    """장면③(AI 분류+근거)용 — 담당자가 확정 후 "전송"까지 마친 건만 반환.

    확정(status: confirmed)과 사장님 전송(sent_to_owner_at)은 분리된 별개 동작이다.
    담당자가 HITL 큐에서 개별 건을 확정해도 사장님 화면에는 바로 안 나타나고,
    담당자가 해당 기업의 확정 건을 모아 "전송" 액션(send_classifications_to_owner)을
    실행해야 그 시점의 sent_to_owner_at이 채워지며 이 목록에 나타난다 — 검토 중인
    기업 배치가 건별로 흘러들어가는 것을 막기 위함.
    HITL 대기(review_required) 건과 확정됐지만 미전송인 건은 원문·Scope·판단 근거를
    사장님에게 노출하지 않는다 — 건수만 get_hitl_pending_count()로 별도 안내.
    정렬: 월·발행일순.
    """
    stmt = (
        select(Classification, Voucher)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where(Classification.scope.in_((1, 2)))
        .where(Classification.status == "confirmed")
        .where(Classification.sent_to_owner_at.isnot(None))
        .order_by(Voucher.month, Voucher.issue_date)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "voucher_id": v.id,
            "raw": v.item_description,
            "scope": c.scope,
            "category": c.category,
            "fuel": c.fuel_type,
            "amount_krw": int(c.amount_krw) if c.amount_krw is not None else None,
            "confidence": c.confidence,
            "evidence": c.evidence,
            "method": c.method,
        }
        for c, v in rows
    ]


def get_hitl_pending_count(session: Session, company_id: int) -> int:
    """장면③ 상단 안내("N건은 담당자가 검토 중이에요")용 — 검토 대기 + 확정됐지만
    아직 전송 안 한 건을 합쳐서 반환한다(둘 다 사장님에게는 아직 "검토중"으로 보임).
    """
    stmt = (
        select(func.count())
        .select_from(Classification)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where(
            (Classification.status == "review_required")
            | ((Classification.status == "confirmed") & Classification.sent_to_owner_at.is_(None))
        )
    )
    return session.execute(stmt).scalar_one()


def get_pending_send_count(session: Session, company_id: int) -> int:
    """관리자 "이 기업 전송" 버튼용 — 확정됐지만 아직 전송 안 한 건수(전송 대상)."""
    stmt = (
        select(func.count())
        .select_from(Classification)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where(Classification.status == "confirmed")
        .where(Classification.sent_to_owner_at.is_(None))
    )
    return session.execute(stmt).scalar_one()


def _selected_hitl_fuel_labels(fuel_types: dict | None) -> list[str] | None:
    """companies.fuel_types_json → HITL 연료 드롭다운(FUEL_OPTIONS)에 쓸 세부 연료명 목록.

    None(연료 체크 전 상태)이면 필터를 걸지 않는다 — get_coverage와 동일한 원칙
    (체크하지 않은 연료의 결손은 알림 대상에서 제외, CLAUDE.md §5 원칙6)을
    드롭다운 필터링에도 그대로 적용한다. "전기"는 항상 필수 취급이라 무조건 포함.
    """
    if fuel_types is None:
        return None
    selected: list[str] = ["전기"]
    if fuel_types.get("diesel"):
        selected.append("경유")
    if fuel_types.get("gasoline"):
        selected.append("휘발유")
    if fuel_types.get("city_gas"):
        selected.append("도시가스")
    if fuel_types.get("lpg") in ("yes", "unsure"):
        selected.append("LPG")
    return selected


def get_hitl_queue(session: Session) -> list[dict]:
    """전 기업의 HITL 검토 작업대 — 검토 대기(review_required) + 확정됐지만 아직
    사장님께 전송 안 한(confirmed, sent_to_owner_at is null) 건을 모두 반환한다.

    담당자가 확정해도 이 큐에서 즉시 사라지지 않는다 — status가 'confirmed'로
    바뀐 채 목록에 남아 "검토 완료" 표시만 되고, 담당자가 기업별로 모아서
    "전송" 버튼(POST /admin/companies/{id}/send-classifications)을 눌러야
    사장님 화면에 실제로 노출된다. 전송 이후에는 이 큐에서도 사라진다.
    (데모는 시연 기업 1곳이지만 쿼리는 기업 무관 — 결선 포트폴리오로 그대로 확장.)
    정렬: 기업 → 월 → 발행일.
    """
    stmt = (
        select(Classification, Voucher, Company)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .join(Company, Voucher.company_id == Company.id)
        .where(
            (Classification.status == "review_required")
            | ((Classification.status == "confirmed") & Classification.sent_to_owner_at.is_(None))
        )
        .order_by(Company.id, Voucher.month, Voucher.issue_date)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "voucher_id": v.id,
            "company_id": co.id,
            "company_name": co.name,
            "raw": v.item_description,
            "scope": c.scope,
            "category": c.category,
            "fuel": c.fuel_type,
            "amount_krw": int(c.amount_krw) if c.amount_krw is not None else None,
            "confidence": c.confidence,
            "evidence": c.evidence,
            "calc_failure_reason": c.calc_failure_reason,
            "method": c.method,
            "month": v.month,
            "source_document_id": c.source_document_id,
            "company_fuel_types": _selected_hitl_fuel_labels(co.fuel_types_json),
            "status": c.status,
        }
        for c, v, co in rows
    ]


def resolve_institution_borrower(session: Session, company_id: int) -> tuple[int, int] | None:
    """기업의 기본 금융기관 귀속(financial_institution_id, institution_borrower_id)을 찾는다.

    데모는 단일 금융기관 시나리오로 0006 마이그레이션이 모든 기업을 1:1 백필해뒀으므로,
    가장 먼저 생성된 귀속 레코드를 신뢰한다. v1 하이브리드 입력(마이데이터·업로드·엑셀)이
    새로 만드는 vouchers/source_documents는 전부 이 헬퍼로 기관 귀속을 채운다.
    아직 백필되지 않은 기업이면 None — 호출부는 nullable 컬럼이므로 비워둔 채 저장해도 안전하다.

    consent_status='active'인 레코드만 본다 — 동의가 철회(revoked)·만료(expired)된
    기업의 새 업로드·마이데이터 수집이 여전히 그 기관 귀속으로 계속 쌓이면 동의 기반
    설계 원칙에 어긋난다.
    """
    stmt = (
        select(InstitutionBorrower)
        .where(
            InstitutionBorrower.company_id == company_id,
            InstitutionBorrower.consent_status == "active",
        )
        .order_by(InstitutionBorrower.id)
    )
    ib = session.execute(stmt).scalars().first()
    if ib is None:
        return None
    return ib.financial_institution_id, ib.id


_PROGRESS_ORDER = ("consent", "upload", "trace", "classify", "report")


def get_owner_progress(session: Session, company_id: int) -> dict:
    """5단계 위저드(연동 동의·데이터 수집·결손 감지·AI 분류·리포트) 각 단계의 실제
    완료 여부 — 홈 화면 진행바와 위저드 이어하기가 이 값을 그대로 쓴다. 세션·화면
    상태가 아니라 DB에 실제로 뭐가 쌓였는지만 본다(새로고침·다른 기기에서도 동일).
    """
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company_id={company_id} 없음")

    # 1) 연동 동의 — 마이데이터 소스 문서가 하나라도 있으면 완료(5종을 한 번에 수집)
    consent_done = session.execute(
        select(SourceDocument.id)
        .where(SourceDocument.company_id == company_id, SourceDocument.source_system.like("mydata:%"))
        .limit(1)
    ).first() is not None

    # 2) 데이터 수집 — 연료 체크 기준 "필수" 문서 종류가 전부 실제로 업로드됐는지
    fuel_types = company.fuel_types_json
    if fuel_types:
        required = required_documents(fuel_types)
        uploaded_types = {
            row[0] for row in session.execute(
                select(SourceDocument.document_type)
                .where(SourceDocument.company_id == company_id, SourceDocument.source_system.like("upload:%"))
                .distinct()
            )
        }
        upload_done = all(
            doc_type in uploaded_types for doc_type, status in required.items() if status == "required"
        )
    else:
        upload_done = False  # 연료 체크 자체를 아직 안 함 — 판정 기준이 없어 미완료로 본다

    # 3) 결손 감지 — 에이전트 실행 이력(trace_logs)이 있으면 완료
    trace_done = session.execute(
        select(TraceLog.id).where(TraceLog.company_id == company_id).limit(1)
    ).first() is not None

    # 4) AI 분류 — 전표가 있고, 전부 분류됐으면 완료(미분류 잔여 0건)
    voucher_count = session.execute(
        select(func.count(Voucher.id)).where(Voucher.company_id == company_id)
    ).scalar_one()
    classified_count = session.execute(
        select(func.count(Classification.id))
        .join(Voucher, Voucher.id == Classification.voucher_id)
        .where(Voucher.company_id == company_id)
    ).scalar_one()
    classify_done = voucher_count > 0 and voucher_count == classified_count

    # 5) 리포트 — 분류가 끝나면 바로 조회 가능(계산은 항상 그 자리에서 재구성됨)
    report_done = classify_done

    steps = {
        "consent": consent_done, "upload": upload_done, "trace": trace_done,
        "classify": classify_done, "report": report_done,
    }
    current_step = next(
        (i for i, key in enumerate(_PROGRESS_ORDER) if not steps[key]), len(_PROGRESS_ORDER) - 1
    )
    return {"steps": steps, "current_step": current_step}


def get_distribution(session: Session, industry_code: str, scope: int) -> dict | None:
    stmt = select(IndustryDistribution).where(
        IndustryDistribution.industry_code == industry_code,
        IndustryDistribution.scope == scope,
    )
    d = session.execute(stmt).scalars().first()
    if not d:
        return None
    return {
        "industry_code": d.industry_code,
        "industry_name": d.industry_name,
        "scope": d.scope,
        "min": d.emission_min_co2e,
        "median": d.emission_median_co2e,
        "max": d.emission_max_co2e,
        "median_per_employee": d.emission_median_per_employee,
        "year": d.year,
        "source": d.source,
    }
