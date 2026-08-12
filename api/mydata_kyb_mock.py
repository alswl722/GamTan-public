"""마이데이터 5종(사업자등록증명·부가세과표증명·표준재무제표증명·중소기업확인서·
전기요금납부내역) mock — 기업 식별·재무 프로필용. 배출량 계산과 무관하다.

⚠️ 한전 마이데이터의 실제 항목은 "전기요금 납부내역"(결제기록) 하나뿐이며 kWh가
없다 — 사용량(kWh)이 필요한 배출량 계산은 db/document_extraction.py의
electric_bill(고지서 업로드) 경로가 담당한다. 이 둘을 혼동하지 않는다.

호출은 멱등이다 — 이미 수집된 기업은 재호출해도 중복 적재하지 않고 기존 값을
반환한다. 표준재무제표증명만 이미 존재하는 borrower_financials 스키마에
정확히 매칭돼 그리로 적재하고, 나머지 4종은 source_documents에만 적재한다
(KYB/전시용, 계산 파이프라인이 읽지 않음).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.document_ingestion import MissingInstitutionAttributionError
from api.queries import resolve_institution_borrower
from db.models import BorrowerFinancial, Company, InstitutionBorrower, SourceDocument
from db.mydata_csv_source import load_mydata_record

MYDATA_SOURCES = (
    "business-registration",
    "vat-tax-base",
    "financial-statement",
    "sme-certificate",
    "kepco-payment-history",
)

_SOURCE_TO_DOCUMENT_TYPE = {
    "business-registration": "business_registration",
    "vat-tax-base": "vat_tax_base",
    "sme-certificate": "sme_certificate",
    "kepco-payment-history": "kepco_payment_history",
}

_FINANCIAL_YEAR = 2025


def _synthetic_business_registration(company: Company) -> dict:
    business_no = f"{200 + company.id:03d}-81-{10000 + company.id:05d}"
    return {"business_registration_no": business_no, "company_name": company.name, "representative": "○○○"}


def _synthetic_vat_tax_base(company: Company) -> dict:
    base = int(company.revenue_krw or 1_000_000_000)
    return {"reporting_year": _FINANCIAL_YEAR, "vat_tax_base_krw": base}


def _synthetic_sme_certificate(company: Company) -> dict:
    return {"is_sme": True, "certificate_type": "중소기업 확인서", "valid_until": f"{_FINANCIAL_YEAR + 1}-12-31"}


def _synthetic_kepco_payment_history(company: Company) -> dict:
    # kWh 없음 — 결제금액만(한전 마이데이터 실제 항목 그대로 재현)
    return {
        "payments": [
            {"year": _FINANCIAL_YEAR, "month": m, "paid_amount_krw": 3_000_000 + company.id * 10_000 + m * 50_000}
            for m in range(1, 13)
        ],
    }


def _synthetic_financial_statement(company: Company) -> dict:
    revenue = int(company.revenue_krw or 2_400_000_000)
    return {"total_equity": round(revenue * 0.35), "total_debt": round(revenue * 0.45)}


_SYNTH = {
    "business-registration": _synthetic_business_registration,
    "vat-tax-base": _synthetic_vat_tax_base,
    "sme-certificate": _synthetic_sme_certificate,
    "kepco-payment-history": _synthetic_kepco_payment_history,
}


def collect_mydata(session: Session, company_id: int, source: str) -> dict:
    """마이데이터 5종 mock 수집 — 멱등(이미 수집됐으면 기존 값을 그대로 반환)."""
    if source not in MYDATA_SOURCES:
        raise ValueError(f"알 수 없는 마이데이터 소스: {source}")

    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company {company_id} not found")

    ib = resolve_institution_borrower(session, company_id)
    if ib is None:
        raise MissingInstitutionAttributionError(
            f"company {company_id}는 아직 금융기관에 귀속되지 않았습니다 (institution_borrowers 없음)"
        )
    financial_institution_id, institution_borrower_id = ib

    # db/seed_mock.py::EXTRA_COMPANIES로 시드된 기업은 external_customer_id가 그대로
    # "C001"~"C006"이라 회계 CSV(data/마이데이터_연동자료_전체기업.csv) 조회 키로 쓸 수
    # 있다 — 없으면(기존 ○○정밀처럼 "demo-company-{id}" 패턴) 합성 데이터만 쓴다.
    ib_row = session.get(InstitutionBorrower, institution_borrower_id)
    csv_record = (
        load_mydata_record(ib_row.external_customer_id, source) if ib_row is not None else None
    )

    if source == "financial-statement":
        return _collect_financial_statement(session, company, financial_institution_id, csv_record)
    return _collect_kyb_document(
        session, company, source, financial_institution_id, institution_borrower_id, csv_record
    )


def _collect_kyb_document(
    session: Session,
    company: Company,
    source: str,
    financial_institution_id: int,
    institution_borrower_id: int,
    csv_record: dict | None = None,
) -> dict:
    document_type = _SOURCE_TO_DOCUMENT_TYPE[source]
    existing = session.execute(
        select(SourceDocument).where(
            SourceDocument.company_id == company.id,
            SourceDocument.document_type == document_type,
        )
    ).scalars().first()
    if existing is not None:
        return {"source": source, "already_collected": True, "extracted": existing.extracted_json}

    # CSV엔 사업자등록번호 같은 필드값이 없다(회계가 관리하는 건 "이 문서를 수집했다"는
    # 메타데이터뿐) — 필드값은 여전히 합성 함수가 채우고, 그 위에 실제 발급기관·용도·
    # 한계 설명만 얹는다.
    payload = _SYNTH[source](company)
    if csv_record is not None:
        payload = {**payload, "_mydata_meta": csv_record}
    doc = SourceDocument(
        financial_institution_id=financial_institution_id,
        company_id=company.id,
        document_type=document_type,
        source_system=f"mydata:{source}" if csv_record is None else f"mydata:{source}:csv",
        # 실제 파일이 없는 mock이라 바이트 해시는 못 만들지만, (기업,문서유형)을
        # 결정론적 문자열로 담아 source_documents의 (company_id, file_hash) 유니크
        # 제약을 그대로 재사용한다 — 동시 수집 요청의 중복 적재 레이스를 막는다.
        file_hash=f"mydata:{company.id}:{document_type}",
        extracted_json=payload,
        verification_status="unverified",
    )

    try:
        # add부터 commit까지 통째로 감싼다 — 중간의 session.get() 등 어떤 쿼리든
        # autoflush로 doc의 pending INSERT를 먼저 내보낼 수 있어, try 블록을
        # commit()에만 좁게 걸면 그 autoflush 시점의 IntegrityError를 놓친다.
        session.add(doc)
        if source == "business-registration":
            ib_row = session.get(InstitutionBorrower, institution_borrower_id)
            if ib_row is not None and not ib_row.external_customer_id.startswith("biz-"):
                ib_row.external_customer_id = f"biz-{payload['business_registration_no']}"
        session.commit()
    except IntegrityError:
        session.rollback()
        existing_after_race = session.execute(
            select(SourceDocument).where(
                SourceDocument.company_id == company.id,
                SourceDocument.document_type == document_type,
            )
        ).scalars().first()
        return {
            "source": source,
            "already_collected": True,
            "extracted": existing_after_race.extracted_json if existing_after_race else payload,
        }
    return {"source": source, "already_collected": False, "extracted": payload}


def _collect_financial_statement(
    session: Session, company: Company, financial_institution_id: int, csv_record: dict | None = None,
) -> dict:
    existing = session.execute(
        select(BorrowerFinancial).where(
            BorrowerFinancial.company_id == company.id,
            BorrowerFinancial.financial_year == _FINANCIAL_YEAR,
        )
    ).scalars().first()
    if existing is not None:
        return {
            "source": "financial-statement",
            "already_collected": True,
            "extracted": {
                "total_equity": float(existing.total_equity),
                "total_debt": float(existing.total_debt),
            },
        }

    payload = _synthetic_financial_statement(company)
    bf = BorrowerFinancial(
        financial_institution_id=financial_institution_id,
        company_id=company.id,
        financial_year=_FINANCIAL_YEAR,
        as_of_date=datetime(_FINANCIAL_YEAR, 12, 31, tzinfo=timezone.utc),
        currency="KRW",
        total_equity=payload["total_equity"],
        total_debt=payload["total_debt"],
        debt_definition="PCAF 방법론상 total_debt — 잠정(회계 확인 전, mock)"
        + (f" | {csv_record['limitation']}" if csv_record else ""),
        source="mydata:financial-statement:csv (mock)" if csv_record else "mydata:financial-statement (mock)",
        verified=False,
    )
    session.add(bf)
    try:
        session.commit()
    except IntegrityError:
        # (company_id, financial_year, version) 유니크 제약(0008)에 걸림 — 동시 수집
        # 요청 레이스. 이미 있는 값을 그대로 반환(멱등 계약 유지).
        session.rollback()
        existing_after_race = session.execute(
            select(BorrowerFinancial).where(
                BorrowerFinancial.company_id == company.id,
                BorrowerFinancial.financial_year == _FINANCIAL_YEAR,
            )
        ).scalars().first()
        return {
            "source": "financial-statement",
            "already_collected": True,
            "extracted": {
                "total_equity": float(existing_after_race.total_equity),
                "total_debt": float(existing_after_race.total_debt),
            } if existing_after_race else payload,
        }
    return {"source": "financial-statement", "already_collected": False, "extracted": payload}
