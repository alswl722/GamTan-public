"""generate_upload_docs.py가 data/업로드서류/ 아래 만든 PDF를 실제 업로드 API
(POST /owner/{company_id}/documents/upload)로 태워 source_documents·vouchers를 채운다.

generate_upload_docs.py는 파일만 만들 뿐 DB에는 아무것도 쓰지 않는다 — 이 스크립트가
그 결과물을 실제 파이프라인(db/document_ingestion.py: OCR/텍스트 추출 → vouchers 변환)에
태우는 후속 단계다. HITL 워크스페이스(web/components/admin/HitlWorkspace.tsx)가
"원본 파일을 찾을 수 없어요" 대신 실제 PDF를 렌더링하려면 이 스크립트로 채워진
source_document_id가 있어야 한다.

사용 전 API 서버가 떠 있어야 한다(docker compose up, 기본 http://localhost:8010).

python -m scripts.ingest_upload_docs 로 실행. 이미 업로드된 파일(file_hash 동일)은
서버가 409로 거부하므로 재실행해도 안전하다(중복 업로드 안 됨).
"""
import os
import time

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from scripts.generate_upload_docs import COMPANIES, DOCS_DIR

load_dotenv()

API_BASE = os.environ.get("GAMTAN_API_BASE", "http://localhost:8010")

DOC_TYPE_MAP = {
    "전기고지서": "electric_bill",
    "도시가스고지서": "gas_bill",
}


def _resolve_document_type(doc_type: str) -> str:
    if doc_type in DOC_TYPE_MAP:
        return DOC_TYPE_MAP[doc_type]
    if doc_type.startswith("세금계산서_"):
        return "tax_invoice"
    raise ValueError(f"알 수 없는 doc_type: {doc_type}")


def _load_company_ids() -> dict[str, int]:
    engine = create_engine(os.environ["DATABASE_URL"])
    names = [c["name"] for c in COMPANIES.values()]
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name FROM companies WHERE name = ANY(:names)"),
            {"names": names},
        ).fetchall()
    by_name = {name: cid for cid, name in rows}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise RuntimeError(
            f"DB에 없는 회사: {missing} — 먼저 db/seed_mock.py의 seed_extra_companies()를 실행하세요"
        )
    return {co_id: by_name[co["name"]] for co_id, co in COMPANIES.items()}


def _upload_one(company_db_id: int, file_path: str, document_type: str) -> tuple[str, str]:
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{API_BASE}/owner/{company_db_id}/documents/upload",
            files={"file": (filename, f, "application/pdf")},
            data={"document_type": document_type, "mode": "ocr"},
            timeout=30,
        )
    if resp.status_code == 202:
        return "accepted", str(resp.json().get("job_id"))
    if resp.status_code == 409:
        return "duplicate", resp.text
    return "error", f"{resp.status_code} {resp.text}"


def main():
    company_ids = _load_company_ids()

    counts = {"accepted": 0, "duplicate": 0, "error": 0}
    for co_id, co in COMPANIES.items():
        company_db_id = company_ids[co_id]
        co_dir = os.path.join(DOCS_DIR, f"{co_id}_{co['name']}")
        if not os.path.isdir(co_dir):
            print(f"[SKIP] {co['name']}: {co_dir} 없음 (generate_upload_docs.py 먼저 실행)")
            continue

        for fname in sorted(os.listdir(co_dir)):
            if not fname.lower().endswith(".pdf"):
                continue
            doc_label = fname.split("_")[0]
            try:
                document_type = _resolve_document_type(
                    "세금계산서_" + fname.split("_")[1] if doc_label == "세금계산서" else doc_label
                )
            except ValueError as e:
                print(f"[SKIP] {co['name']}/{fname}: {e}")
                continue

            status, detail = _upload_one(company_db_id, os.path.join(co_dir, fname), document_type)
            counts[status] += 1
            print(f"[{status.upper():9s}] {co['name']} (id={company_db_id}) / {fname} → {detail}")

    print(f"\n완료: accepted={counts['accepted']} duplicate={counts['duplicate']} error={counts['error']}")
    if counts["accepted"]:
        print("백그라운드 OCR/추출 처리가 이어서 진행됩니다 — GET /owner/{company_id}/documents/jobs 로 상태 확인 가능.")


if __name__ == "__main__":
    main()
