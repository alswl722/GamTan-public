"""소상공인 트랙 fixture(S001·S002)를 업로드 파이프라인으로 적재한다.

fixture는 파일일 뿐이고 DB 적재는 원래 업로드 경로를 타야 한다(별도 시딩 스크립트를 두지
않는 게 이 프로젝트의 설계다) — 그래서 이 스크립트도 DB에 직접 INSERT하지 않고
`create_upload_job()` + `process_upload_job()`을 그대로 호출한다. 즉 실제 사장님이 올린
것과 완전히 같은 경로(텍스트 레이어 → OCR → LLM 라우터)를 지난다.

사용:
    python3 scripts/ingest_small_business_fixtures.py --company S001 --dry-run
    python3 scripts/ingest_small_business_fixtures.py --company S001 --formats pdf
    python3 scripts/ingest_small_business_fixtures.py --company S001 S002

주의: 공유 DB에 쓴다. --dry-run으로 대상 파일을 먼저 확인할 것.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from api.document_ingestion import (
    DuplicateDocumentError,
    create_upload_job,
    process_upload_job,
)
from db.models import Company, FinancialInstitution, InstitutionBorrower

# fixture 회사코드 → DB에 만들 기업 정보. 업종코드는 통계청 표준산업분류.
COMPANIES = {
    "S001": {"name": "동성로카페", "industry_code": "I56191", "industry_name": "커피 전문점",
             "region": "대구 중구", "employee_count": 3},
    "S002": {"name": "반월당분식", "industry_code": "I56111", "industry_name": "한식 일반 음식점업",
             "region": "대구 중구", "employee_count": 2},
}
FIXTURE_ROOT = "data/fixtures/electricity_bills"


def ensure_company(session: Session, code: str) -> Company:
    """기업 + 기관 귀속(동의 active)을 준비한다.

    `source_documents.financial_institution_id`가 NOT NULL이고 업로드 경로가
    `resolve_institution_borrower()`로 귀속을 찾으므로, InstitutionBorrower가 없으면
    업로드 자체가 MissingInstitutionAttributionError로 막힌다.
    """
    spec = COMPANIES[code]
    company = session.execute(
        select(Company).where(Company.name == spec["name"])
    ).scalar_one_or_none()
    if company is None:
        company = Company(**spec)
        session.add(company)
        session.commit()
        print(f"  기업 생성: {spec['name']} (id={company.id})")
    else:
        print(f"  기업 재사용: {spec['name']} (id={company.id})")

    inst = session.execute(select(FinancialInstitution).order_by(FinancialInstitution.id)).scalars().first()
    if inst is None:
        raise SystemExit("financial_institutions가 비어 있다 — db/init_db.py를 먼저 돌려야 한다")

    ib = session.execute(
        select(InstitutionBorrower)
        .where(InstitutionBorrower.company_id == company.id)
        .where(InstitutionBorrower.consent_status == "active")
    ).scalar_one_or_none()
    if ib is None:
        session.add(InstitutionBorrower(
            financial_institution_id=inst.id,
            company_id=company.id,
            external_customer_id=f"fixture-{code.lower()}",
            consent_status="active",
        ))
        session.commit()
        print(f"  기관 귀속 생성: {inst.name}")
    return company


def ingest(session: Session, company: Company, code: str, formats: set[str], dry_run: bool) -> None:
    files = sorted(
        f for f in os.listdir(f"{FIXTURE_ROOT}/{code}")
        if not f.startswith("_") and f.rsplit(".", 1)[-1].lower() in formats
    )
    print(f"  대상 파일 {len(files)}건 ({', '.join(sorted(formats))})")
    if dry_run:
        for f in files[:5]:
            print(f"    - {f}")
        if len(files) > 5:
            print(f"    ... 외 {len(files) - 5}건")
        return

    ok = dup = fail = 0
    for i, name in enumerate(files, 1):
        path = f"{FIXTURE_ROOT}/{code}/{name}"
        with open(path, "rb") as fh:
            data = fh.read()
        started = time.time()
        try:
            job = create_upload_job(session, company.id, data, name, "electric_bill")
        except DuplicateDocumentError:
            dup += 1
            print(f"    [{i}/{len(files)}] 중복 건너뜀: {name}")
            continue
        process_upload_job(job.id, session)
        session.refresh(job)
        elapsed = time.time() - started
        if job.status == "done":
            ok += 1
            print(f"    [{i}/{len(files)}] OK {name} ({job.result_year}-{job.result_month:02d}, {elapsed:.1f}s)")
        else:
            fail += 1
            print(f"    [{i}/{len(files)}] 실패 {name}: {job.error_message}")
    print(f"  결과 — 성공 {ok} / 중복 {dup} / 실패 {fail}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", nargs="+", default=["S001", "S002"], choices=sorted(COMPANIES))
    ap.add_argument("--formats", nargs="+", default=["pdf", "jpg", "png"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)
    formats = {f.lower() for f in args.formats}
    with Session(engine) as session:
        for code in args.company:
            print(f"\n=== {code} {COMPANIES[code]['name']} ===")
            company = ensure_company(session, code)
            ingest(session, company, code, formats, args.dry_run)


if __name__ == "__main__":
    main()
