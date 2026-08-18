"""POST /owner/{company_id}/documents/upload — 라우터 레벨(TestClient) 검증.

GET .../documents/grid, GET .../documents, DELETE .../documents/{id} — "데이터
업로드" 탭(문서종류 × 월 그리드, 파일 목록·삭제)이 쓰는 엔드포인트도 이 파일에서
검증한다(같은 db/client 픽스처 재사용)."""
import io
import os

import openpyxl
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api.db as api_db
from api.db import get_session
from api.document_ingestion import REPO_ROOT
from api.main import app
from db.models import Base, Classification, Company, DocumentUploadJob, FinancialInstitution, InstitutionBorrower, SourceDocument, Voucher

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _minimal_pdf(lines: list[str]) -> bytes:
    """테스트 전용 — 합성 mock이 사라졌으므로 OCR 성공 케이스는 실제로 파싱되는
    최소 텍스트 PDF가 있어야 한다(tests/test_document_extraction.py와 동일 패턴)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    y = 700
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def _electric_bill_pdf(*, month="03", amount=987_654, quantity=1234) -> bytes:
    return _minimal_pdf([
        "전기요금 고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        f"청구월: 2025-{month} 계약종별: 산업용(을) 고압A",
        f"사용량(kWh) {quantity}",
        f"청구금액(원) {amount}",
    ])


def _gas_bill_pdf(*, month="04", amount=555_555, quantity=321) -> bytes:
    return _minimal_pdf([
        "도시가스 요금고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        f"사용월: 2025-{month}",
        f"사용량(m³) {quantity}",
        f"청구금액(원) {amount}",
    ])


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
def client(db, monkeypatch):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    # 업로드는 이제 접수(요청 스코프 get_session)와 처리(BackgroundTasks 안에서
    # api.db.new_session()으로 여는 별도 세션)로 나뉜다 — new_session()은 기본적으로
    # 앱 전역 엔진(DATABASE_URL)을 쓰므로, 이 테스트의 파일 기반 sqlite 엔진을 직접
    # 바꿔치기해야 백그라운드 처리 결과가 이 테스트의 session에서도 바로 보인다.
    # TestClient는 BackgroundTasks가 끝난 뒤에야 응답을 반환하므로(확인됨) 아래
    # client.post() 호출 시점엔 이미 처리가 끝나 있다.
    engine = session.get_bind()
    monkeypatch.setattr(api_db, "_engine", engine)
    monkeypatch.setattr(
        api_db, "_SessionLocal",
        sessionmaker(bind=engine, class_=Session, expire_on_commit=False),
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload_and_wait(client, company_id: int, **kwargs) -> dict:
    """업로드 접수 응답(job_id)을 받은 뒤 잡 상세를 조회해 돌려준다 — TestClient가
    BackgroundTasks 완료까지 기다린 뒤 응답하므로 접수 응답 직후 조회해도 안전하다.
    실패 케이스(422였던 것들 포함)도 이제 이 dict의 status가 "failed"로 남는다."""
    accepted = client.post(f"/owner/{company_id}/documents/upload", **kwargs)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    job_res = client.get(f"/owner/{company_id}/documents/jobs/{job_id}")
    assert job_res.status_code == 200, job_res.text
    return job_res.json()


def test_ocr_upload_electric_bill_succeeds(db, client):
    _, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _electric_bill_pdf(), "application/pdf")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert job["status"] == "done", job
    assert job["vouchers_created"] == 1


def test_ocr_upload_without_document_type_auto_detects(db, client):
    """"그냥 업로드" — document_type 필드 자체를 안 보내도 OCR이 스스로 종류를
    판별해 처리한다(사장님이 어느 칸인지 몰라도 올릴 수 있어야 함)."""
    _, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="05"), "application/pdf")},
        data={"mode": "ocr"},
    )
    assert job["status"] == "done", job
    assert job["result_document_type"] == "gas_bill"
    assert job["result_month"] == 5

    grid = client.get(f"/owner/{company_id}/documents/grid?year=2025").json()
    gas_row = next(r for r in grid["document_types"] if r["document_type"] == "gas_bill")
    assert gas_row["months"]["5"] == 1


def test_excel_upload_tax_invoice_succeeds(db, client):
    _, company_id = db
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["작성일자", "상호", "품목명", "공급가액"])
    ws.append(["2025-01-18", "구미석유", "경유 외 1종", 654000])
    ws.append(["2025-02-15", "구미석유", "유류대금", 612000])
    buf = io.BytesIO()
    wb.save(buf)

    job = _upload_and_wait(
        client, company_id,
        files={"file": ("hometax.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"document_type": "tax_invoice", "mode": "excel"},
    )
    assert job["status"] == "done", job
    assert job["vouchers_created"] == 2


def test_duplicate_upload_returns_409(db, client):
    """중복 파일은 접수(create_upload_job) 단계에서 동기로 걸러지므로 지금도 즉시
    409다 — 202로 접수되는 건 처리가 필요한 새 파일뿐."""
    _, company_id = db
    files = {"file": ("고지서.pdf", _gas_bill_pdf(month="04"), "application/pdf")}
    data = {"document_type": "gas_bill", "mode": "ocr"}
    first = client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    assert first.status_code == 202, first.text
    second = client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    assert second.status_code == 409


def test_duplicate_upload_is_recorded_as_quality_issue(db, client):
    """실패한 업로드는 품질 이슈 로그(DocumentIngestionFailure)에 기록된다
    (v1 Tier 2 — 이전엔 HTTP 응답으로만 실패가 전달되고 DB엔 아무 것도 안 남았다)."""
    from db.models import DocumentIngestionFailure

    session, company_id = db
    files = {"file": ("고지서.pdf", _gas_bill_pdf(month="06"), "application/pdf")}
    data = {"document_type": "gas_bill", "mode": "ocr"}
    client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)
    client.post(f"/owner/{company_id}/documents/upload", files=files, data=data)

    failures = session.query(DocumentIngestionFailure).filter_by(company_id=company_id).all()
    assert len(failures) == 1
    assert failures[0].failure_reason == "duplicate"


def test_invalid_document_type_returns_400(db, client):
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "not_a_real_type", "mode": "ocr"},
    )
    assert res.status_code == 400


def test_excel_mode_rejected_for_non_tax_invoice(db, client):
    _, company_id = db
    res = client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("x.xlsx", b"x", "application/octet-stream")},
        data={"document_type": "electric_bill", "mode": "excel"},
    )
    assert res.status_code == 400


def test_ocr_non_pdf_returns_202_then_job_fails(db, client):
    """PDF도 아니고 알려진 이미지 포맷(JPEG/PNG/WEBP/HEIC)도 아닌 바이트는 OCR
    래스터화 단계에서 곧장 실패한다(모델 호출 자체가 안 감) — 접수(202) 자체는
    성공하지만 백그라운드 처리가 job.status="failed"로 남는다. 합성값으로
    가리지 않고 명확히 실패한다는 원칙은 그대로 유지된다(실패 가시성 원칙,
    합성 mock 폴백 없음) — 다만 이제 그 실패가 동기 422가 아니라 잡 상태다."""
    _, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert job["status"] == "failed", job


def test_ocr_pdf_with_unrecognized_format_and_failed_ocr_job_fails(db, client, monkeypatch):
    """PDF는 맞지만 알려진 서식이 아니면(제목 줄 불일치 등) OCR 폴백을 타는데,
    그마저 실패하면 값을 지어내지 않고 실패로 남는다 — 예전엔 year/month가
    있으면 합성값으로 통과했었다. OCR 호출은 monkeypatch로 대체해 실 모델 로딩을 안 쓴다."""
    import db.document.document_extraction as document_extraction
    from db.document.document_text_extractor import DocumentParseError

    def _ocr_fails(file_bytes):
        raise DocumentParseError("문서를 정확히 읽지 못했어요 — 더 선명한 사진으로 다시 올려 주세요")

    monkeypatch.setattr(document_extraction, "ocr_extract", _ocr_fails)

    _, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("x.pdf", _minimal_pdf(["아무 문서", "관련 없는 내용"]), "application/pdf")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert job["status"] == "failed", job


def test_ocr_image_upload_succeeds_via_ocr_fallback(db, client, monkeypatch):
    """이미지(JPG/PNG) 업로드는 텍스트 레이어가 없어 곧장 OCR(PaddleOCR, 100% 로컬)
    폴백을 탄다 — 프론트가 이미 `accept="image/*,.pdf"`로 사진 업로드를 받고 있던
    것과 백엔드가 이제 맞아떨어진다. 실 모델 로딩 없이 OCR 재구성 텍스트만
    monkeypatch로 고정하고, 구조화(정규식 파싱)는 실제 경로를 그대로 탄다."""
    import db.document.document_extraction as document_extraction
    from db.document.document_ocr_extractor import OcrResult

    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: OcrResult(
            text=(
                "전기요금 고지서\n청구월: 2025-06\n"
                "사용량(kWh) 1,234\n청구금액(원) 987,654"
            ),
            rows=[],
            confidence=0.93,
        ),
    )

    _, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("사진.jpg", b"\xff\xd8\xff\xe0fake-jpeg-bytes", "image/jpeg")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )
    assert job["status"] == "done", job
    assert job["vouchers_created"] == 1
    assert job["result_year"] == 2025 and job["result_month"] == 6


# ── GET .../documents/grid, GET .../documents — 데이터 업로드 탭 그리드 ─────────
def test_documents_grid_reflects_uploaded_month(db, client):
    _, company_id = db
    client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("고지서.pdf", _electric_bill_pdf(month="03"), "application/pdf")},
        data={"document_type": "electric_bill", "mode": "ocr"},
    )

    res = client.get(f"/owner/{company_id}/documents/grid?year=2025")
    assert res.status_code == 200, res.text
    rows = {r["document_type"]: r for r in res.json()["document_types"]}
    assert rows["electric_bill"]["months"]["3"] == 1
    assert rows["electric_bill"]["months"]["4"] == 0


def test_documents_grid_marks_gas_bill_not_applicable_when_fuel_not_selected(db, client):
    """fuel_types_json 미설정(연료 체크 전) 기업은 도시가스가 not_applicable —
    db/document_requirements.py::required_documents 그대로 재사용됨을 확인."""
    _, company_id = db
    res = client.get(f"/owner/{company_id}/documents/grid?year=2025")
    rows = {r["document_type"]: r["status"] for r in res.json()["document_types"]}
    assert rows["gas_bill"] == "not_applicable"
    assert rows["electric_bill"] == "required"


def test_documents_for_cell_lists_uploaded_file(db, client):
    _, company_id = db
    client.post(
        f"/owner/{company_id}/documents/upload",
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="04"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )

    res = client.get(
        f"/owner/{company_id}/documents?document_type=gas_bill&year=2025&month=4"
    )
    assert res.status_code == 200, res.text
    docs = res.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["original_filename"] == "고지서.pdf"


def test_documents_for_cell_empty_when_no_upload(db, client):
    _, company_id = db
    res = client.get(
        f"/owner/{company_id}/documents?document_type=gas_bill&year=2025&month=5"
    )
    assert res.json()["documents"] == []


# ── DELETE .../documents/{id} — 연쇄 삭제 ────────────────────────────────────
def test_delete_document_removes_voucher_and_physical_file(db, client):
    """이 문서를 만든 DocumentUploadJob(result_source_document_id로 참조)이 아직
    남아있는 상태에서 삭제한다 — 실측 확인된 회귀: sqlite는 기본적으로 FK를
    강제하지 않아 여기선 조용히 통과하지만, 실제 Postgres에선 job이 문서를
    참조 중이면 삭제가 IntegrityError로 막혔다(2026-08-18). 이제
    delete_source_document()가 참조를 먼저 끊으므로(job 자체는 유지) 성공해야
    하고, job의 참조도 null로 남아야 한다."""
    session, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="06"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )
    doc_id = job["result_source_document_id"]
    job_id = job["job_id"]

    doc = session.get(SourceDocument, doc_id)
    abs_path = os.path.join(REPO_ROOT, doc.file_path)
    assert os.path.exists(abs_path)

    voucher = session.query(Voucher).filter_by(source_document_id=doc_id).one()
    voucher_id = voucher.id
    # 분류까지 끝난 상태를 흉내내 연쇄 삭제가 Classification까지 지우는지 같이 확인.
    session.add(Classification(
        voucher_id=voucher_id, scope=1, category="고정연소", fuel_type="도시가스",
        amount_krw=555_555, emission_co2e=100.0, confidence=0.9,
        evidence="테스트", method="rule", status="auto",
    ))
    session.commit()

    res = client.delete(f"/owner/{company_id}/documents/{doc_id}")
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is True

    # 삭제된 ORM 인스턴스(voucher)를 다시 건드리지 않고 미리 뽑아둔 id로만 재조회 —
    # bulk delete() 이후 세션이 그 인스턴스를 만료시켜 속성 접근 시 ObjectDeletedError가 난다.
    assert session.get(SourceDocument, doc_id) is None
    assert session.query(Voucher).filter_by(id=voucher_id).one_or_none() is None
    assert session.query(Classification).filter_by(voucher_id=voucher_id).one_or_none() is None
    assert not os.path.exists(abs_path)

    # job 레코드(처리 이력) 자체는 남아있되, 지워진 문서에 대한 참조만 끊겨야 한다.
    remaining_job = session.get(DocumentUploadJob, job_id)
    assert remaining_job is not None
    assert remaining_job.result_source_document_id is None


def test_delete_document_returns_404_for_other_company(db, client):
    session, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="07"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )
    doc_id = job["result_source_document_id"]

    other = Company(name="타사", industry_code="C251")
    session.add(other)
    session.commit()

    res = client.delete(f"/owner/{other.id}/documents/{doc_id}")
    assert res.status_code == 404
    assert session.get(SourceDocument, doc_id) is not None  # 안 지워졌어야 함


def test_delete_document_returns_404_when_not_found(db, client):
    _, company_id = db
    res = client.delete(f"/owner/{company_id}/documents/99999")
    assert res.status_code == 404


# ── GET .../documents/{id}/review-status ─────────────────────────────────────

def test_review_status_counts_review_required_classification(db, client):
    """업로드 완료 모달용 — 방금 올린 문서에서 만들어진 전표가 담당자 검토
    대기(review_required)로 분류되면 건수로 잡힌다."""
    session, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="08"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )
    doc_id = job["result_source_document_id"]
    voucher = session.query(Voucher).filter_by(source_document_id=doc_id).one()
    session.add(Classification(voucher_id=voucher.id, scope=1, status="review_required"))
    session.commit()

    res = client.get(f"/owner/{company_id}/documents/{doc_id}/review-status")
    assert res.status_code == 200, res.text
    assert res.json() == {"pending_review_count": 1}


def test_review_status_zero_before_classification_runs(db, client):
    session, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="09"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )
    doc_id = job["result_source_document_id"]

    res = client.get(f"/owner/{company_id}/documents/{doc_id}/review-status")
    assert res.status_code == 200, res.text
    assert res.json() == {"pending_review_count": 0}


def test_review_status_returns_404_for_other_company(db, client):
    session, company_id = db
    job = _upload_and_wait(
        client, company_id,
        files={"file": ("고지서.pdf", _gas_bill_pdf(month="10"), "application/pdf")},
        data={"document_type": "gas_bill", "mode": "ocr"},
    )
    doc_id = job["result_source_document_id"]

    other = Company(name="타사", industry_code="C251")
    session.add(other)
    session.commit()

    res = client.get(f"/owner/{other.id}/documents/{doc_id}/review-status")
    assert res.status_code == 404
