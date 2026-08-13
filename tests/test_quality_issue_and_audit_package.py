"""품질 이슈 로그 + 감사 대응 근거 패키지 테스트 (v1 Tier 2, owner-admin-flow-spec.md §7·§8).

핵심 검증축:
  - 업로드 실패는 DocumentIngestionFailure로 기록되고, 성공한 업로드는 기록되지 않는다.
  - 품질 이슈 로그는 열람 전용(GET만) — 반려 사유별로 그대로 노출한다.
  - 감사 대응 근거 패키지는 trace_logs + classifications.evidence + vouchers를
    기업·기간 기준으로 시계열 조합한다(신규 계산 로직 없음, 조회·조합만).
  - CSV 내보내기는 JSON과 같은 데이터를 그대로 직렬화한다.
"""
import io

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.audit_package import build_audit_package
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
from db.quality_issues import list_ingestion_failures, record_ingestion_failure

YEAR = 2025

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _gas_bill_pdf(*, month="03", amount=800_000, quantity=800) -> bytes:
    """합성 mock이 사라졌으므로 업로드 성공 케이스는 실제로 파싱되는 최소
    텍스트 PDF가 있어야 한다(tests/test_document_extraction.py와 동일 패턴)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    y = 700
    for line in [
        "도시가스 요금고지서",
        f"사용월: 2025-{month}",
        f"사용량(m³) {quantity}",
        f"청구금액(원) {amount}",
    ]:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


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


def test_list_ingestion_failures_includes_company_name_and_label(db):
    session, cid = db
    record_ingestion_failure(
        session, cid, document_type="tax_invoice", original_filename="x.xlsx",
        failure_reason="excel_format", detail="헤더 열이 다릅니다",
    )
    issues = list_ingestion_failures(session)
    assert len(issues) == 1
    assert issues[0]["company_name"] == "○○정밀"
    assert issues[0]["failure_reason_label"] == "엑셀 형식 오류"


def test_list_ingestion_failures_ordered_most_recent_first(db):
    session, cid = db
    record_ingestion_failure(
        session, cid, document_type="gas_bill", original_filename="a.jpg",
        failure_reason="duplicate", detail="첫 실패",
    )
    record_ingestion_failure(
        session, cid, document_type="gas_bill", original_filename="b.jpg",
        failure_reason="parse_error", detail="두번째 실패",
    )
    issues = list_ingestion_failures(session)
    assert issues[0]["detail"] == "두번째 실패"
    assert issues[1]["detail"] == "첫 실패"


# ── API 라우터 — GET /admin/quality-issues ────────────────────────────────────
def test_quality_issues_endpoint_excludes_successful_uploads(db, client):
    """성공한 업로드는 품질 이슈 로그에 안 남는다 — 실패만 모은 열람 전용 로그다."""
    session, cid = db
    ok_res = client.post(
        f"/owner/{cid}/documents/upload",
        files={"file": ("ok.pdf", _gas_bill_pdf(month="03"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )
    assert ok_res.status_code == 200, ok_res.text
    files = {"file": ("dup.pdf", _gas_bill_pdf(month="04"), "application/pdf")}
    data = {"document_type": "gas_bill", "mode": "ocr"}
    first = client.post(f"/owner/{cid}/documents/upload", files=files, data=data)
    assert first.status_code == 200, first.text
    second = client.post(f"/owner/{cid}/documents/upload", files=files, data=data)
    assert second.status_code == 409

    res = client.get("/admin/quality-issues")
    assert res.status_code == 200
    issues = res.json()["issues"]
    assert len(issues) == 1
    assert issues[0]["failure_reason"] == "duplicate"


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
