"""제조업 트랙 "전년 대비 감축" fixture(C004·C005, 2024-01~2026-08)를 업로드
파이프라인으로 적재한다.

scripts/ingest_small_business_fixtures.py(S001·S002)와 같은 설계 — fixture는 파일일
뿐이고 DB 적재는 원래 업로드 경로(create_upload_job + process_upload_job)를 그대로
탄다(텍스트 레이어 → OCR → LLM 라우터). 차이점은 제조업 트랙이라 전기고지서
(electric_bill) 뿐 아니라 세금계산서(tax_invoice, 경유)도 같이 적재해야 Scope1+2
합산치가 나온다는 것.

C004·C005는 이미 db/seed_mock.py::EXTRA_COMPANIES에 등록돼 있는 기존 데모 기업이라
(external_id="C004"/"C005") 새로 만들지 않고 그 행을 재사용한다 — S001·S002 스크립트가
신규 기업을 만드는 것과의 차이.

사용:
    python3 scripts/ingest_manufacturing_fixtures.py --company C004 --dry-run
    python3 scripts/ingest_manufacturing_fixtures.py --company C004 C005
    python3 scripts/ingest_manufacturing_fixtures.py --company C004 --doc-types electric_bill

주의: 공유 DB에 쓴다. --dry-run으로 대상 파일을 먼저 확인할 것. company_goals(목표
설정)는 이 스크립트가 만들지 않는다 — 적재 후 앱 화면(또는 POST
/owner/{company_id}/goals)에서 실제 위저드 플로우로 목표를 세워야 한다(스냅숏이라
과거 목표를 소급 생성하면 "언제 목표를 세웠는지"가 거짓이 된다).
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

# fixture 회사코드 → data/fixtures/{electricity_bills,tax_invoices}/{code} 하위 파일을
# 업로드할 문서종류. db/seed_mock.py::EXTRA_COMPANIES에 이미 등록된 기업이라 name만
# 맞으면 된다(신규 컬럼 없음).
COMPANIES = {
    "C004": {"name": "칠곡소재"},
    "C005": {"name": "포항이엔지"},
}
DOC_TYPE_DIRS = {
    "electric_bill": "electricity_bills",
    "tax_invoice": "tax_invoices",
}


def ensure_company(session: Session, code: str) -> Company:
    """기업 조회 + 기관 귀속(동의 active) 보장.

    C004·C005는 db/seed_mock.py의 EXTRA_COMPANIES 시드가 이미 만들어뒀어야 한다
    (db/init_db.py 실행 시점). 없으면 seed_mock을 먼저 돌리라고 안내하고 중단한다 —
    이 스크립트가 대신 만들지 않는다(기업 마스터 데이터는 seed_mock.py가 정본).
    """
    spec = COMPANIES[code]
    company = session.execute(
        select(Company).where(Company.name == spec["name"])
    ).scalar_one_or_none()
    if company is None:
        raise SystemExit(
            f"기업 '{spec['name']}'({code})이 DB에 없다 — "
            f"db/seed_mock.py의 EXTRA_COMPANIES 시드를 먼저 적재해야 한다."
        )
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


def ingest(session: Session, company: Company, code: str, doc_type: str, formats: set[str], dry_run: bool) -> None:
    fixture_dir = f"data/fixtures/{DOC_TYPE_DIRS[doc_type]}/{code}"
    if not os.path.isdir(fixture_dir):
        print(f"  {fixture_dir} 없음 — 건너뜀")
        return
    files = sorted(
        f for f in os.listdir(fixture_dir)
        if not f.startswith("_") and f.rsplit(".", 1)[-1].lower() in formats
    )
    print(f"  [{doc_type}] 대상 파일 {len(files)}건 ({', '.join(sorted(formats))})")
    if dry_run:
        for f in files[:5]:
            print(f"    - {f}")
        if len(files) > 5:
            print(f"    ... 외 {len(files) - 5}건")
        return

    ok = dup = fail = 0
    for i, name in enumerate(files, 1):
        path = f"{fixture_dir}/{name}"
        with open(path, "rb") as fh:
            data = fh.read()
        started = time.time()
        try:
            job = create_upload_job(session, company.id, data, name, doc_type)
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
    print(f"  [{doc_type}] 결과 — 성공 {ok} / 중복 {dup} / 실패 {fail}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", nargs="+", default=["C004", "C005"], choices=sorted(COMPANIES))
    ap.add_argument("--doc-types", nargs="+", default=["electric_bill", "tax_invoice"], choices=sorted(DOC_TYPE_DIRS))
    ap.add_argument("--formats", nargs="+", default=["pdf", "jpg", "png"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)
    formats = {f.lower() for f in args.formats}
    with Session(engine) as session:
        for code in args.company:
            print(f"\n=== {code} {COMPANIES[code]['name']} ===")
            company = ensure_company(session, code)
            for doc_type in args.doc_types:
                ingest(session, company, code, doc_type, formats, args.dry_run)


if __name__ == "__main__":
    main()
