"""공용 DB 조회 헬퍼 — Mock API·에이전트 도구·trace 라우터가 공통 재사용.

여기 모아두면 "전표/분포를 DB에서 꺼내는" 로직이 한 곳에만 존재한다.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.document.document_requirements import required_documents
from db.models import (
    BorrowerEmissionInventory,
    CarbonNeutralPointApplication,
    Classification,
    Company,
    InstitutionBorrower,
    OwnerNotification,
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
    """기업의 전표 전량 — 기간 필터 없음, 연대순 정렬.

    year를 정렬 키에 넣는 이유(2026-08-22 수정): 종전엔 `(month, issue_date)`로만
    정렬해서 여러 해 데이터가 섞이면 결과가 연대순이 아니었다. 월이 1차 키라 모든
    1월이 먼저 묶이고, 2차 키인 issue_date는 nullable이라(마이데이터 mock 경로 등)
    NULLS LAST로 밀려 2021년 전표가 2026년 뒤에 오는 일이 실제로 있었다.
    v0.1이 "12개월치 전표" 단일 연도만 다뤘을 때는 드러나지 않던 전제다.

    소상공인 탄소중립포인트 트랙은 24개월(과거 2년) 사용량을 월 시계열로 다루므로
    (CLAUDE.md §7 예외) 이 순서에 의존한다. 기존 호출부(get_coverage·collect_vouchers·
    mock 라우터)는 집계·건수 용도라 순서에 의존하지 않아 영향이 없다.
    """
    stmt = select(Voucher).where(Voucher.company_id == company_id)
    if source:
        stmt = stmt.where(Voucher.source == source)
    stmt = stmt.order_by(Voucher.year, Voucher.month, Voucher.issue_date)
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


def get_coverage(session: Session, company_id: int, year: int | None = None, *, as_of: datetime | None = None) -> dict:
    """월(1~12) × 연료 대분류 존재 여부 매트릭스 + 결손 목록.

    에이전트가 "3~5월 가스가 0건이네?"를 스스로 관찰하는 재료. matrix는 체크
    여부와 무관하게 전체를 반환하고(참고용), gaps만 선택된 연료로 필터한다.

    year 생략 시 달력상 올해(as_of 기준)로 검사한다. 올해를 보는 경우 아직 오지
    않은 달(예: 지금이 8월이면 9~12월)은 결손으로 잡지 않는다 — 아직 발행되지도
    않은 전표를 "빠졌다"고 알리게 되는 걸 막기 위함(실측 2026-08-17). 과거 연도를
    명시하면 그 해 12개월 전부를 본다.
    """
    today = as_of or datetime.now(timezone.utc)
    target_year = year if year is not None else today.year
    applicable_months = today.month if target_year == today.year else 12

    vouchers = get_vouchers(session, company_id)
    fuels = ["전기", "가스", "경유/유류"]
    matrix = {f: {m: 0 for m in range(1, 13)} for f in fuels}
    for v in vouchers:
        if v["year"] != target_year:
            continue
        fc = _fuel_class(v["item_description"])
        if fc in matrix:
            matrix[fc][v["month"]] += 1

    company = session.get(Company, company_id)
    selected_fuels = _selected_coverage_fuels(company.fuel_types_json if company else None)

    gaps = []
    for f in fuels:
        if selected_fuels is not None and f not in selected_fuels:
            continue
        missing = [m for m in range(1, applicable_months + 1) if matrix[f][m] == 0]
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
    """장면③(AI 분류+근거)용 — "auto"(HITL 안 거친 확정 케이스) 건 + 담당자가
    확정 후 "전송"까지 마친 건을 반환.

    status: auto는 룰/고신뢰 LLM으로 애초에 사람 검토가 필요 없다고 판정된
    건이라(CLAUDE.md §5-3 "확정 케이스는 LLM 안 태움"과 같은 결 — 여기서는 검토
    게이트 자체가 불필요) 이 목록에 바로 나타난다. 반면 review_required로 갔다가
    담당자가 확정(status: confirmed)한 건은 사장님 전송(sent_to_owner_at)까지
    별개 동작으로 분리돼 있다 — 담당자가 HITL 큐에서 개별 건을 확정해도 사장님
    화면에는 바로 안 나타나고, 담당자가 해당 기업의 확정 건을 모아 "전송" 액션
    (send_classifications_to_owner)을 실행해야 이 목록에 나타난다 — 검토 중인
    기업 배치가 건별로 흘러들어가는 것을 막기 위함.
    HITL 대기(review_required) 건과 확정됐지만 미전송인 건은 원문·Scope·판단 근거를
    사장님에게 노출하지 않는다 — 건수만 get_hitl_pending_count()로 별도 안내.
    정렬: 연·월·발행일순(2026-08-22 — 종전 "월·발행일순"은 다년 데이터에서 연대순이
    깨졌다, get_vouchers 참고).

    ⚠️ 반환 dict에 year·month가 없다 — 이 목록은 "무엇을 어떻게 분류했나"를 보여주는
    화면용이고 월 시계열이 아니다. 소상공인 탄소중립포인트 감축률처럼 월별 사용량
    시계열이 필요한 계산은 이 함수를 쓸 수 없고 별도 조회 함수가 필요하다.
    """
    stmt = (
        select(Classification, Voucher, SourceDocument)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .outerjoin(SourceDocument, Voucher.source_document_id == SourceDocument.id)
        .where(Voucher.company_id == company_id)
        .where(Classification.scope.in_((1, 2)))
        .where(
            (Classification.status == "auto")
            | (
                (Classification.status == "confirmed")
                & Classification.sent_to_owner_at.isnot(None)
            )
        )
        # get_vouchers와 같은 이유로 year를 1차 키에 넣는다(2026-08-22) — 여러 해
        # 데이터가 섞이면 월 우선 정렬이 연대순을 깨뜨린다.
        .order_by(Voucher.year, Voucher.month, Voucher.issue_date)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "voucher_id": v.id,
            # 세금계산서 원문("지게차 경유 외 1종")은 분류 판단의 실제 근거라
            # evidence로서 의미가 있지만, 전기/가스고지서는 문서종류만으로
            # Scope가 정해져 판단 근거가 아니다. 값도 결정론적 파서/LLM 라우터가
            # 실제로 못 읽으면 고정 문구("전기요금 (산업용 을)" 등)로 채워지는
            # 자리표시자라 "읽어온 값"처럼 보이면 오해의 소지가 있다 — 세금계산서
            # 건에서만 노출한다.
            "raw": v.item_description if sd is not None and sd.document_type == "tax_invoice" else None,
            "scope": c.scope,
            "category": c.category,
            "fuel": c.fuel_type,
            "amount_krw": int(c.amount_krw) if c.amount_krw is not None else None,
            # 탄소량은 이 값(사용량) × 배출계수로 계산된다(db/calc_engine.py::
            # compute_emission) — amount_krw(청구금액)는 계산에 안 쓰이는 참고
            # 정보일 뿐이라, 실제 근거인 사용량을 화면에 같이 보여준다.
            "activity_amount": c.activity_amount,
            "activity_unit": c.activity_unit,
            "confidence": c.confidence,
            "evidence": c.evidence,
            "method": c.method,
        }
        for c, v, sd in rows
    ]


def get_unclassified_count(session: Session, company_id: int) -> int:
    """분류를 아직 한 번도 안 돈 전표(Classification 행 자체가 없는 Voucher) 수.

    api/agent/tools.py::_unclassified_vouchers와 같은 조건(카운트만). "데이터
    업로드" 탭의 "분류 다시 실행" 버튼을 조건부로 보여줄 때 쓴다 — 예전엔 항상
    떠 있었는데, "이미 업로드된 파일입니다"(409)로 전량 실패하면 자동 재분류
    호출 자체가 안 일어나 미분류 잔여 건이 생겨도 아무 안내가 안 뜨는 경우가
    있어(2026-08-17) 버튼을 늘 노출해 뒀었다. 이제 이 값으로 실제 남은 건이
    있을 때만 보여준다."""
    stmt = (
        select(func.count())
        .select_from(Voucher)
        .where(Voucher.company_id == company_id)
        .where(Voucher.id.notin_(select(Classification.voucher_id)))
    )
    return session.execute(stmt).scalar_one()


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


def get_pending_anomaly_checks(session: Session, company_id: int) -> list[dict]:
    """이상치 되묻기(docs/tasks.md) — 사장님이 아직 답하지 않은 이상치 확인 요청.

    anomaly_check_status가 'pending'인 건만 — 이미 답한 건(confirmed_normal|
    disputed|unknown)은 이 목록에서 빠진다. 분류 상세(scope·evidence)는
    노출하지 않는다 — 예/아니오/모르겠어요로만 답하면 되는 질문이라 그 이상의
    정보는 불필요(사장님 화면 원칙과 동일, get_classifications() 참고).
    """
    stmt = (
        select(Classification, Voucher)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where(Classification.anomaly_check_status == "pending")
        # get_vouchers와 같은 이유로 year를 1차 키에(2026-08-22) — 되묻기 큐에 여러
        # 해 건이 섞이면 "몇 월 건인지"만 보여주는 화면에서 순서가 뒤엉킨다.
        .order_by(Voucher.year, Voucher.month, Voucher.issue_date)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "voucher_id": v.id,
            "month": v.month,
            "fuel": c.fuel_type,
            "ratio": c.anomaly_ratio,
        }
        for c, v in rows
    ]


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
    정렬: 사장님이 이상치를 "아니요/모르겠어요"로 답한 건(disputed|unknown)을
    최우선으로, 그다음 기업 → 월 → 발행일(docs/tasks.md — 사장님이 명시적으로
    "이상하다"고 답한 건을 그냥 묻히게 두지 않는다).
    """
    stmt = (
        select(Classification, Voucher, Company)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .join(Company, Voucher.company_id == Company.id)
        .where(
            (Classification.status == "review_required")
            | ((Classification.status == "confirmed") & Classification.sent_to_owner_at.is_(None))
        )
        .order_by(
            Classification.anomaly_check_status.in_(("disputed", "unknown")).desc(),
            Company.id, Voucher.month, Voucher.issue_date,
        )
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
            "anomaly_check_status": c.anomaly_check_status,
            "anomaly_check_reason": c.anomaly_check_reason,
            "anomaly_ratio": c.anomaly_ratio,
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


# scripts/fetch_industry_distributions.py가 실데이터에서 실제로 쓰는 밴드 문자열과
# 정확히 일치해야 한다(data/industry_distributions.xlsx 참고, 손으로 바꾸지 말 것).
_WORKER_BAND_UPPER_BOUNDS = [
    (4, "5인 미만"),
    (9, "5인 ~ 9인"),
    (19, "10인 ~ 19인"),
    (49, "20인 ~ 49인"),
    (99, "50인 ~ 99인"),
    (299, "100인 ~ 299인"),
    (499, "300인 ~ 499인"),
    (999, "500인 ~ 999인"),
]
_WORKER_BAND_TOP = "1000인 이상"
_MIN_BAND_SAMPLE_SIZE = 3  # 이 밑이면 규모 밴드 대신 전체 규모 통합(worker_band=NULL)으로 폴백


def _worker_band_for(employee_count: int | None) -> str | None:
    if employee_count is None:
        return None
    for upper, label in _WORKER_BAND_UPPER_BOUNDS:
        if employee_count <= upper:
            return label
    return _WORKER_BAND_TOP


def get_distribution(
    session: Session, industry_code: str, scope: int, employee_count: int | None = None
) -> dict | None:
    """업종×Scope 배출량 분포 조회 — employee_count를 주면 그 규모 밴드를 우선
    매칭하고, 밴드가 없거나 표본이 너무 적으면(<_MIN_BAND_SAMPLE_SIZE) 전체 규모
    통합(worker_band=NULL) 값으로 폴백한다. employee_count 생략 시엔 처음부터
    전체 규모 통합 값만 본다(기존 호출부 호환).
    """
    band = _worker_band_for(employee_count)
    d = None
    scale_matched = False
    if band is not None:
        stmt = select(IndustryDistribution).where(
            IndustryDistribution.industry_code == industry_code,
            IndustryDistribution.scope == scope,
            IndustryDistribution.worker_band == band,
        )
        candidate = session.execute(stmt).scalars().first()
        if candidate is not None and (candidate.sample_size or 0) >= _MIN_BAND_SAMPLE_SIZE:
            d, scale_matched = candidate, True

    if d is None:
        stmt = select(IndustryDistribution).where(
            IndustryDistribution.industry_code == industry_code,
            IndustryDistribution.scope == scope,
            IndustryDistribution.worker_band.is_(None),
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
        "sample_size": d.sample_size,
        "scale_matched": scale_matched,
    }


def _owner_visible_classification_filter():
    """사장님 화면에 노출 가능한 분류 건 조건 — get_classifications()와 동일 기준.

    review_required(HITL 대기)나 confirmed인데 아직 전송 안 한 건은 제외한다.
    캘린더·브리핑도 사장님 화면이므로 이 필터를 그대로 따른다(다른 원칙 없음,
    기존 get_classifications()의 필터를 재사용)."""
    return (Classification.status == "auto") | (
        (Classification.status == "confirmed") & Classification.sent_to_owner_at.isnot(None)
    )


def get_calendar_events(session: Session, company_id: int, year: int, month: int) -> list[dict]:
    """탄소 캘린더용 — 그 달의 날짜별 구매·탄소 배출·리포트·신청 내역.

    entry_type별로 날짜 산정 기준이 다르다:
      - "voucher": issue_date(전표가 다루는 거래/사용월) 기준. nullable — 없으면
        정확한 날짜에 못 꽂으므로 제외(실패 가시성 원칙). 사장님에게 노출 가능한
        분류(_owner_visible_classification_filter)가 붙은 건만 반환. 건별로 그대로
        나열(voucher_id가 개별 전표를 가리켜야 상세 조회가 되므로 묶지 않음).
      - "report": 탄소리포트(PCAF 품질평가) 생성 시점(BorrowerEmissionInventory.created_at).
        조회할 때마다 Scope별로 새 버전이 저장되는 구조라(db/pcaf_engine/pcaf_quality.py::
        save_quality_assessment_version) 같은 날 여러 Scope가 갱신될 수 있는데,
        캘린더에서는 날짜당 1개로 완전히 통합한다(건수는 count, 배출량은 그날
        마지막으로 저장된 버전 값을 대표로 노출).
      - "carbon_point_application": 탄소중립포인트 신청서 초안이 생성된 시점
        (CarbonNeutralPointApplication.created_at). 실제 포털 제출일이 아니라
        초안 생성일 — 제출일을 담는 컬럼은 아직 없다(CLAUDE.md §5 원칙10, status는
        draft 이후 사장님이 수동 갱신하는 필드일 뿐 감탄이 추적하지 않음).

    에이전트 트레이스(결손 감지·이상치 검증 등 내부 판단 로그)는 여기 포함하지
    않는다 — 사장님이 캘린더에서 보고 싶은 건 "이날 뭘 샀고 탄소가 얼마나
    나왔는지"이지 에이전트가 어떤 판단을 했는지가 아니다(2026-08-19 사용자
    피드백). 트레이스는 여전히 관리자 실행 이력 탭(admin)에서 확인 가능 —
    이 함수의 스코프에서만 뺀 것이지 데이터 자체를 지운 게 아니다.

    정렬: 날짜 오름차순.
    """
    voucher_rows = session.execute(
        select(Voucher, Classification)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where(Voucher.issue_date.isnot(None))
        .where(func.extract("year", Voucher.issue_date) == year)
        .where(func.extract("month", Voucher.issue_date) == month)
        .where(_owner_visible_classification_filter())
        .order_by(Voucher.issue_date)
    ).all()

    events = []
    for v, c in voucher_rows:
        events.append({
            "date": v.issue_date.date().isoformat(),
            "entry_type": "voucher",
            "voucher_id": v.id,
            "scope": c.scope,
            "fuel_type": c.fuel_type,
            "item_description": v.item_description,
            "supply_amount_krw": int(v.supply_amount_krw) if v.supply_amount_krw is not None else None,
            # emission_co2e는 kg 단위 저장 — 표시 단위(tCO2e)로 환산(모델 주석 관례,
            # api/queries.py::get_monthly_briefing_stats와 동일)
            "emission_tco2e": round(c.emission_co2e / 1000, 3) if c.emission_co2e is not None else None,
            "source": v.source,
            "count": 1,
        })

    report_rows = session.execute(
        select(BorrowerEmissionInventory)
        .where(BorrowerEmissionInventory.company_id == company_id)
        .where(func.extract("year", BorrowerEmissionInventory.created_at) == year)
        .where(func.extract("month", BorrowerEmissionInventory.created_at) == month)
        .order_by(BorrowerEmissionInventory.created_at)
    ).scalars().all()

    reports_by_day: dict[str, list[BorrowerEmissionInventory]] = {}
    for inv in report_rows:
        reports_by_day.setdefault(inv.created_at.date().isoformat(), []).append(inv)

    for day, invs in reports_by_day.items():
        latest = invs[-1]  # order_by(created_at) 유지 순서라 마지막이 그날 최신
        events.append({
            "date": day,
            "entry_type": "report",
            "voucher_id": None,
            "scope": None,
            "fuel_type": None,
            "item_description": f"{latest.reporting_year}년 탄소리포트 갱신",
            "supply_amount_krw": None,
            "emission_tco2e": round(latest.emission_tco2e, 3) if latest.emission_tco2e is not None else None,
            "source": "report",
            "count": len(invs),
        })

    application_rows = session.execute(
        select(CarbonNeutralPointApplication)
        .where(CarbonNeutralPointApplication.company_id == company_id)
        .where(func.extract("year", CarbonNeutralPointApplication.created_at) == year)
        .where(func.extract("month", CarbonNeutralPointApplication.created_at) == month)
        .order_by(CarbonNeutralPointApplication.created_at)
    ).scalars().all()

    applications_by_day: dict[str, list[CarbonNeutralPointApplication]] = {}
    for app in application_rows:
        applications_by_day.setdefault(app.created_at.date().isoformat(), []).append(app)

    for day, apps in applications_by_day.items():
        latest = apps[-1]
        events.append({
            "date": day,
            "entry_type": "carbon_point_application",
            "voucher_id": None,
            "scope": None,
            "fuel_type": None,
            "item_description": f"탄소중립포인트 신청서 초안 ({latest.target_year}년)",
            "supply_amount_krw": None,
            "emission_tco2e": None,
            "source": "carbon_point",
            "count": len(apps),
        })

    events.sort(key=lambda e: e["date"])
    return events


def get_monthly_briefing_stats(session: Session, company_id: int, year: int, month: int) -> dict:
    """월간 AI 브리핑용 — 이번 달 vs 지난달 연료별 tCO2e 합계.

    편지 문단 조립(db/owner_briefing.py)에 넘길 원자료만 만든다 — 문장 생성은
    이 함수의 책임이 아니다(계산과 문장 템플릿 분리).

    반환: {has_previous_month, fuel_totals: [{fuel_type, this_month_co2e,
           last_month_co2e}]}
    직전월에 사장님 노출 가능 분류가 하나도 없으면 has_previous_month=False —
    "첫 달"로 취급해 비교 문장 대신 시작 안내를 쓰게 한다(db/owner_briefing.py
    참고).
    """
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)

    def _fuel_totals(y: int, m: int) -> dict[str, float]:
        rows = session.execute(
            select(Classification.fuel_type, func.sum(Classification.emission_co2e))
            .join(Voucher, Classification.voucher_id == Voucher.id)
            .where(Voucher.company_id == company_id)
            .where(Voucher.year == y)
            .where(Voucher.month == m)
            .where(Classification.fuel_type.isnot(None))
            .where(Classification.emission_co2e.isnot(None))
            .where(_owner_visible_classification_filter())
            .group_by(Classification.fuel_type)
        ).all()
        # emission_co2e는 kgCO2e로 저장 — 표시 단위(tCO2e)로 환산(모델 주석 관례)
        return {fuel: float(total) / 1000 for fuel, total in rows}

    this_month_totals = _fuel_totals(year, month)
    last_month_totals = _fuel_totals(prev_year, prev_month)
    has_previous_month = len(last_month_totals) > 0

    fuel_types = sorted(set(this_month_totals) | set(last_month_totals))
    fuel_stats = [
        {
            "fuel_type": f,
            "this_month_co2e": this_month_totals.get(f, 0.0),
            "last_month_co2e": last_month_totals.get(f) if has_previous_month else None,
        }
        for f in fuel_types
    ]

    return {"has_previous_month": has_previous_month, "fuel_totals": fuel_stats}


def get_owner_notifications(session: Session, company_id: int, *, unread_only: bool = False) -> list[dict]:
    """사장님 메인 화면 배너용 — 확정 전송 알림 목록 (v1 §6-2, docs/tasks.md).

    최신순 정렬. unread_only=True면 아직 안 읽은(read_at is null) 것만 —
    배너 폴링이 "새 알림 있음"만 감지하면 되는 경우에 쓴다.
    """
    stmt = select(OwnerNotification).where(OwnerNotification.company_id == company_id)
    if unread_only:
        stmt = stmt.where(OwnerNotification.read_at.is_(None))
    stmt = stmt.order_by(OwnerNotification.created_at.desc())
    rows = session.execute(stmt).scalars().all()
    return [
        {
            "id": n.id,
            "type": n.type,
            "message": n.message,
            "payload": n.payload,
            "created_at": n.created_at,
            "read_at": n.read_at,
        }
        for n in rows
    ]
