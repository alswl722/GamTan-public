"""사장님 전용 API — /owner 장면이 쓰는 자기 기업 데이터 조회·입력.

- GET   /owner/alerts/{company_id}              자기 기업의 이상 신호 알림
- PATCH /owner/{company_id}/fuel-types          2단계(연료 유형 체크) 저장 + 3단계 필수서류 안내
- POST  /owner/{company_id}/documents/upload    3~4단계 업로드(세금계산서 OCR|엑셀, 전기·도시가스 OCR)
- GET   /owner/{company_id}/rate-candidate      우대금리 등급 상승 후보 여부(있으면 요청 버튼 노출)
- POST  /owner/{company_id}/rate-requests       우대금리·설비금융 안내 요청 생성 → 관리자 승인요청 큐

GET /admin/alerts(은행 담당자용 포트폴리오 전체)와 같은 판정 로직
(db/alerts.py::detect_alerts)을 재사용하되 자기 기업으로만 필터한다 —
은행이 먼저 알고 사장은 모르는 구도를 만들지 않기 위함(CLAUDE.md §9,
"하지 말 것" — 알림은 항상 사장에게 먼저).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db import get_session
from api.document_ingestion import (
    DuplicateDocumentError,
    MissingInstitutionAttributionError,
    ingest_uploaded_document,
)
from api.queries import get_coverage
from db.alerts import detect_alerts
from db.document_requirements import FuelTypes, required_documents
from db.hometax_excel_parser import HometaxExcelFormatError
from db.models import Company
from db.pcaf import upgrade_candidate_for_company
from db.rate_approvals import (
    CompanyNotFoundError,
    DISCLAIMER_TEXT,
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


@router.get("/{company_id}/coverage")
def owner_coverage(company_id: int, session: Session = Depends(get_session)):
    """업로드 화면(3~4단계)의 결손 넛지 카드용 — 연료체크로 필터된 gaps만 반환.

    db/alerts.py(EWS)는 분류 완료 후에나 의미가 있어 업로드 직후엔 비어 보인다.
    이건 voucher 존재 여부만 보는 훨씬 이른 신호라 업로드 직후에도 바로 쓸 수 있다.
    """
    return get_coverage(session, company_id)


@router.post("/{company_id}/documents/upload")
async def upload_document(
    company_id: int,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    mode: str = Form("ocr"),
    year: int | None = Form(None),
    month: int | None = Form(None),
    session: Session = Depends(get_session),
):
    """3단계(세금계산서 OCR|엑셀 택1)·4단계(전기·도시가스고지서 OCR) 공용 업로드.

    실제 처리는 api/document_ingestion.py — source_documents 적재 후 vouchers를
    만들어 기존 classify_vouchers 파이프라인이 그대로 이어받게 한다. mode="excel"은
    document_type="tax_invoice"에서만 의미 있음(대량 홈택스 엑셀 파서 경로).
    """
    if document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid document_type: {document_type}")
    if mode not in ("ocr", "excel"):
        raise HTTPException(status_code=400, detail=f"invalid mode: {mode}")
    if mode == "excel" and document_type != "tax_invoice":
        raise HTTPException(status_code=400, detail="엑셀 업로드는 세금계산서만 지원합니다")
    if mode == "ocr" and (year is None or month is None):
        raise HTTPException(status_code=400, detail="OCR 업로드는 year/month가 필요합니다")

    file_bytes = await file.read()
    try:
        return ingest_uploaded_document(
            session, company_id, file_bytes, file.filename or "upload",
            document_type, mode=mode, year=year, month=month,
        )
    except DuplicateDocumentError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except MissingInstitutionAttributionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HometaxExcelFormatError as e:
        # 실패 가시성 원칙 — 파싱 실패를 목업 데이터로 가리지 않고 그대로 안내(CLAUDE.md §6)
        raise HTTPException(status_code=422, detail=str(e))


class RateRequestIn(BaseModel):
    request_type: str = "rate_upgrade"  # rate_upgrade | equipment_finance


@router.get("/{company_id}/rate-candidate")
def rate_candidate(company_id: int, session: Session = Depends(get_session)):
    """자기 기업이 등급 상승 후보인지 — 후보면 프론트가 "안내 요청" 버튼을 노출한다.

    은행 GET /admin/rate-candidates와 같은 판정(db/pcaf.py::upgrade_candidate_for_company)을
    자기 기업으로 좁혀 재사용한다. 후보가 아니면 candidate: null.
    """
    candidate = upgrade_candidate_for_company(session, company_id)
    return {"candidate": candidate, "disclaimer_text": DISCLAIMER_TEXT}


@router.post("/{company_id}/rate-requests")
def submit_rate_request(
    company_id: int, body: RateRequestIn, session: Session = Depends(get_session)
):
    """사장님이 안내 카드의 "요청" 버튼을 눌러 승인요청 큐에 항목을 만든다.

    여신 결정이 아니다(CLAUDE.md §9) — 이 요청은 관리자 승인요청 큐(GET /admin/rate-requests)로
    가서 담당자가 "안내 대상으로 확인"할 뿐, 금리·여신을 자동으로 확정하지 않는다.
    """
    try:
        req = create_rate_request(session, company_id, request_type=body.request_type)
    except CompanyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NoUpgradeCandidateError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "id": req.id,
        "company_id": req.company_id,
        "request_type": req.request_type,
        "current_grade": req.current_grade,
        "target_grade": req.target_grade,
        "missing_summary": req.missing_summary,
        "disclaimer_text": req.disclaimer_text,
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }
