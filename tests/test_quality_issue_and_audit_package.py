"""업로드 실패 기록 + 감사 대응 근거 패키지 테스트 (v1 Tier 2, owner-admin-flow-spec.md §7·§8).

핵심 검증축:
  - 업로드 실패는 DocumentIngestionFailure로 기록된다(record_ingestion_failure).
    이 기록을 관리자 화면에서 조회하는 경로(GET /admin/quality-issues,
    list_ingestion_failures)는 실무적으로 불필요해 제거했다 — 아래 주석 참고.
  - 감사 대응 근거 패키지는 trace_logs + classifications.evidence + vouchers를
    기업·기간 기준으로 시계열 조합한다(신규 계산 로직 없음, 조회·조합만).
  - CSV·PDF 내보내기는 JSON과 같은 데이터를 그대로 직렬화한다 — 재계산하지 않는다.
"""
import io

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.audit_package import build_audit_package
from db.audit_report_pdf import build_audit_report_pdf
from db.models import (
    Base,
    Classification,
    Company,
    DocumentIngestionFailure,
    FinancialInstitution,
    InstitutionBorrower,
    TraceLog,
    Voucher,
)
from db.quality_issues import record_ingestion_failure

YEAR = 2025


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()
        # 업로드 라우터 테스트는 기관 귀속이 있어야 MissingInstitutionAttributionError
        # 없이 실제로 성공/중복 케이스를 검증할 수 있다(test_owner_document_upload.py와 동일 패턴).
        inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
        session.add(inst)
        session.commit()
        session.add(InstitutionBorrower(
            financial_institution_id=inst.id, company_id=company.id,
            external_customer_id="demo-company-1", consent_status="active",
        ))
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_voucher_with_classification(session, cid, month, item, *, evidence="테스트 근거"):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item, supply_amount_krw=100000,
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=1, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=500.0, confidence=0.9,
        evidence=evidence, method="rule", status="auto",
    ))
    session.commit()
    return v.id


# ── db/quality_issues.py 순수 로직 ───────────────────────────────────────────
def test_record_ingestion_failure_persists(db):
    session, cid = db
    record_ingestion_failure(
        session, cid, document_type="gas_bill", original_filename="고지서.jpg",
        failure_reason="duplicate", detail="이미 업로드된 파일입니다",
    )
    failures = session.query(DocumentIngestionFailure).filter_by(company_id=cid).all()
    assert len(failures) == 1
    assert failures[0].failure_reason == "duplicate"


# GET /admin/quality-issues(관리자측 품질 이슈 로그 탭)와 db/quality_issues.py::
# list_ingestion_failures는 실무적으로 불필요하다고 판단해 제거했다 — 업로드 실패
# 원인은 은행 담당자가 아니라 개발/운영 쪽에서 다룰 정보였다. 실패 기록 자체
# (record_ingestion_failure, DocumentIngestionFailure 테이블)는 그대로 유지하며
# 위 test_record_ingestion_failure_persists가 그 기록 경로를 계속 검증한다.


# ── db/audit_package.py 순수 로직 ─────────────────────────────────────────────
def test_build_audit_package_combines_vouchers_and_traces_sorted(db):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "도시가스", evidence="근거1")
    _add_voucher_with_classification(session, cid, 2, "도시가스", evidence="근거2")
    session.add(TraceLog(
        company_id=cid, session_id="s-1", step_type="관찰",
        message="3월 가스 결손 발견", tool_name="테스트",
    ))
    session.commit()

    package = build_audit_package(session, cid, YEAR)
    assert package["company_id"] == cid
    assert package["entry_count"] == 3
    entry_types = {e["entry_type"] for e in package["entries"]}
    assert entry_types == {"voucher", "trace"}
    voucher_entries = [e for e in package["entries"] if e["entry_type"] == "voucher"]
    assert {e["evidence"] for e in voucher_entries} == {"근거1", "근거2"}


def test_build_audit_package_filters_by_month_range(db):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "도시가스")
    _add_voucher_with_classification(session, cid, 6, "도시가스")
    _add_voucher_with_classification(session, cid, 12, "도시가스")

    package = build_audit_package(session, cid, YEAR, month_from=1, month_to=6)
    months = {e["month"] for e in package["entries"] if e["entry_type"] == "voucher"}
    assert months == {1, 6}


def test_build_audit_package_empty_when_no_data(db):
    session, cid = db
    package = build_audit_package(session, cid, YEAR)
    assert package["entry_count"] == 0
    assert package["entries"] == []


# ── API 라우터 — GET /admin/audit-package ─────────────────────────────────────
def test_audit_package_endpoint_returns_json_by_default(db, client):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "도시가스", evidence="근거1")

    res = client.get(f"/admin/audit-package?company_id={cid}&year={YEAR}")
    assert res.status_code == 200
    body = res.json()
    assert body["company_id"] == cid
    assert body["entry_count"] == 1


def test_audit_package_endpoint_csv_export(db, client):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "도시가스", evidence="근거1")

    res = client.get(f"/admin/audit-package?company_id={cid}&year={YEAR}&format=csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    body = res.text
    assert "근거1" in body
    assert "voucher" in body


def test_audit_package_endpoint_unknown_company_returns_404(db, client):
    res = client.get(f"/admin/audit-package?company_id=99999&year={YEAR}")
    assert res.status_code == 404


def test_audit_package_endpoint_pdf_export(db, client):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "도시가스", evidence="근거1")

    res = client.get(f"/admin/audit-package?company_id={cid}&year={YEAR}&format=pdf")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert "attachment" in res.headers["content-disposition"]
    assert f"audit-report-{cid}-{YEAR}.pdf" in res.headers["content-disposition"]

    with pdfplumber.open(io.BytesIO(res.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "○○정밀" in text
    assert "근거1" in text


# ── db/audit_report_pdf.py 순수 로직 ──────────────────────────────────────────
def test_build_audit_report_pdf_returns_nonempty_bytes(db):
    session, cid = db
    _add_voucher_with_classification(session, cid, 1, "도시가스", evidence="근거1")
    package = build_audit_package(session, cid, YEAR)

    pdf_bytes = build_audit_report_pdf(package, "○○정밀")
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")


def test_build_audit_report_pdf_handles_empty_entries(db):
    session, cid = db
    package = build_audit_package(session, cid, YEAR)

    pdf_bytes = build_audit_report_pdf(package, "○○정밀")
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "해당 기간에 표시할 근거가 없습니다" in text
