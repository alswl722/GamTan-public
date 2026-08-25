"""issue_date 백필 — 원본 파일을 재업로드 없이 재파싱해 Voucher.issue_date를 채운다.

배경: db/document/document_text_extractor.py의 세금계산서·전기·도시가스 파서가
연/월만 반환하고 일자(day)를 버리는 버그가 있었다(2026-08-19 발견 — 탄소
캘린더가 항상 비어 보이는 원인). 파서는 고쳤지만, 이미 DB에 있는 전표는 그
버그가 있을 때 파싱된 결과라 issue_date가 여전히 null로 남아있다.

SourceDocument.file_path(원본 파일의 상대경로)로 실제 파일을 다시 읽어
extract_document()를 재실행하고, 새로 나온 issue_date를 연결된 Voucher에만
갱신한다 — 다른 필드(금액·품목 등)는 이미 확정된 값을 그대로 두고 건드리지
않는다(재분류·재계산 없음, 이 스크립트의 책임은 issue_date 하나뿐).

file_path 경로에 파일이 없으면(2026-08-19 실측: data/uploads/ 아래 상당수가
유실돼 있었음 — 원래 data/fixtures/{electricity_bills,tax_invoices}/{회사코드}/
에서 scripts/generate_upload_docs.py 등이 만들어 업로드용으로 복사했던 합성
문서들) original_filename으로 data/fixtures/ 전체를 검색해 재시도한다. 그마저
없으면(마이데이터 mock 경로로 생긴 전표는 원래 원본 파일이 없음) 건너뛴다 —
실패로 잡지 않는다.

사용: python scripts/backfill_issue_date.py [--dry-run]
"""
import argparse
import glob
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.document.document_extraction import extract_document
from db.document.document_text_extractor import DocumentParseError
from db.models import SourceDocument, Voucher

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(REPO_ROOT, "data", "fixtures")


def _find_in_fixtures(original_filename: str) -> str | None:
    """file_path가 유실된 문서를 original_filename으로 fixtures 전체에서 재탐색.
    이름이 유니크하다는 전제(회사명+날짜+문서종류 조합, 실측상 충돌 없음)로 첫
    매치를 쓴다."""
    if not original_filename:
        return None
    matches = glob.glob(os.path.join(FIXTURES_DIR, "**", original_filename), recursive=True)
    return matches[0] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="갱신 없이 무엇이 바뀔지만 출력")
    parser.add_argument("--company-id", type=int, help="이 기업만 대상으로(먼저 하나로 확인해볼 때)")
    args = parser.parse_args()

    engine = create_engine(os.getenv("DATABASE_URL"))

    updated = skipped_missing_on_disk = failed = 0
    recovered_from_fixtures = 0
    with Session(engine) as session:
        stmt = select(SourceDocument).where(
            # water_bill은 아직 적재되는 경로가 없지만 어휘에 넣어둔다 — 나중에 수도
            # 문서가 쌓인 뒤 이 필터를 고치는 걸 잊으면 조용히 빠진 채로 돈다.
            SourceDocument.document_type.in_(
                ("tax_invoice", "electric_bill", "gas_bill", "water_bill")
            )
        )
        if args.company_id is not None:
            stmt = stmt.where(SourceDocument.company_id == args.company_id)
        docs = session.execute(stmt).scalars().all()
        print(f"[i] 대상 문서(세금계산서·전기·가스·수도) {len(docs)}건" + (f" (company_id={args.company_id})" if args.company_id else ""))

        for doc in docs:
            vouchers = session.execute(
                select(Voucher).where(Voucher.source_document_id == doc.id)
            ).scalars().all()
            if not vouchers:
                continue
            # 이미 issue_date가 있으면(신규 업로드분 등) 재파싱할 이유가 없다
            if all(v.issue_date is not None for v in vouchers):
                continue

            abs_path = None
            if doc.file_path:
                candidate = os.path.normpath(os.path.join(REPO_ROOT, doc.file_path))
                if os.path.isfile(candidate):
                    abs_path = candidate

            if abs_path is None:
                fixture_path = _find_in_fixtures(doc.original_filename)
                if fixture_path is not None:
                    abs_path = fixture_path
                    recovered_from_fixtures += 1
                    print(f"  [FIXTURE] doc={doc.id} ({doc.original_filename}) — data/uploads에 없어 fixtures에서 대신 찾음")

            if abs_path is None:
                skipped_missing_on_disk += 1
                print(f"  [MISS] doc={doc.id} 파일 없음: {doc.file_path} (fixtures에도 없음)")
                continue

            with open(abs_path, "rb") as f:
                file_bytes = f.read()

            try:
                parsed = extract_document(session, file_bytes, doc.document_type)
            except DocumentParseError as e:
                failed += 1
                print(f"  [FAIL] doc={doc.id} ({doc.original_filename}) — {e}")
                continue

            issue_date = parsed.get("issue_date")
            if issue_date is None:
                failed += 1
                print(f"  [FAIL] doc={doc.id} — 재파싱해도 issue_date 없음")
                continue

            for v in vouchers:
                if v.issue_date is not None:
                    continue
                print(f"  [OK]   voucher={v.id} doc={doc.id} ({doc.original_filename}) → issue_date={issue_date}")
                if not args.dry_run:
                    dt = datetime.fromisoformat(issue_date)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    v.issue_date = dt
                updated += 1

        if not args.dry_run:
            session.commit()

    print(
        f"\n[완료] 갱신 {updated} · fixtures에서 복구 {recovered_from_fixtures} · "
        f"파일유실 {skipped_missing_on_disk} · 재파싱실패 {failed}"
        + (" (dry-run — 실제로 커밋 안 됨)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
