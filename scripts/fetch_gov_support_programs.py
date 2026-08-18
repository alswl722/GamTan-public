"""정부 지원사업(기업마당 bizinfo) 배치 수집 — 1일 1회, GitHub Actions
(.github/workflows/fetch-gov-support.yml)에서 돈다. docs/gov-support-matching-plan.md
§6-3 정본.

1. bizinfo API 전체 공고 조회(hashtags 사전 필터 없음 — §3 정정, 재현율 손실 위험)
2. 로컬 키워드 필터(db/gov_support/bizinfo_client.py::matches_keywords)
3. (source, external_id) 기준 upsert — raw_text_hash가 바뀐 행만 재임베딩
4. 이번 배치에 안 보인 기존 행은 is_active=false (하드 delete 안 함, 이력 보존)
5. 부분 실패해도 성공한 행만 fetched_at 갱신(실패 가시성 원칙 — CLAUDE.md §6)

사용: .venv/bin/python scripts/fetch_gov_support_programs.py
"""
import hashlib
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_engine
from db.gov_support.bizinfo_client import fetch_raw_items, matches_keywords, normalize_item
from db.gov_support.embeddings import embed_document
from db.models import GovSupportProgram

SOURCE = "bizinfo"


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def run() -> None:
    api_key = os.getenv("BIZINFO_API_KEY")
    if not api_key:
        print("[FAIL] BIZINFO_API_KEY가 .env에 없습니다")
        sys.exit(1)

    print("[i] bizinfo API 전체 공고 조회 중...")
    raw_items = fetch_raw_items(api_key)
    print(f"[i] 전체 {len(raw_items)}건 수신")

    candidates = [item for item in raw_items if matches_keywords(item)]
    print(f"[i] 키워드 매칭 {len(candidates)}건")

    seen_external_ids: set[str] = set()
    upserted = 0
    reembedded = 0
    failed = 0

    stale = []
    with Session(get_engine()) as session:
        for item in candidates:
            external_id = item.get("pblancId")
            if not external_id:
                failed += 1
                continue
            seen_external_ids.add(external_id)

            try:
                normalized = normalize_item(item)
                raw_text_hash = hashlib.sha256(normalized["raw_text"].encode("utf-8")).hexdigest()

                existing = session.execute(
                    select(GovSupportProgram).where(
                        GovSupportProgram.source == SOURCE,
                        GovSupportProgram.external_id == external_id,
                    )
                ).scalar_one_or_none()

                needs_embedding = existing is None or existing.raw_text_hash != raw_text_hash
                embedding = embed_document(normalized["raw_text"]) if needs_embedding else (
                    existing.embedding if existing else None
                )
                if needs_embedding and embedding is not None:
                    reembedded += 1

                now = datetime.now(timezone.utc)
                if existing is None:
                    existing = GovSupportProgram(source=SOURCE, external_id=external_id, created_at=now)
                    session.add(existing)

                existing.program_name = normalized["program_name"]
                existing.category = normalized["category"]
                existing.agency_name = normalized["agency_name"]
                existing.apply_start_date = _parse_date(normalized["apply_start_date"])
                existing.apply_end_date = _parse_date(normalized["apply_end_date"])
                existing.apply_period_raw = normalized["apply_period_raw"]
                existing.region_tags = normalized["region_tags"]
                existing.detail_url = normalized["detail_url"]
                existing.raw_text = normalized["raw_text"]
                existing.raw_text_hash = raw_text_hash
                existing.embedding = embedding
                existing.is_active = True
                existing.fetched_at = now
                existing.updated_at = now

                session.commit()
                upserted += 1
            except Exception as e:
                session.rollback()
                print(f"[FAIL] {external_id} 처리 실패: {e}")
                failed += 1

        # 이번 배치에 안 보인 기존 활성 행은 is_active=false (하드 delete 안 함).
        # seen_external_ids가 비어있으면(이번 배치에서 매칭 0건) 전체를 비활성화하지
        # 않는다 — 일시적 API 실패로 후보가 0건일 수 있어(§7 실패 가시성), 그 경우
        # 기존 데이터를 그대로 유지하는 쪽이 안전하다.
        stale_query = select(GovSupportProgram).where(
            GovSupportProgram.source == SOURCE,
            GovSupportProgram.is_active.is_(True),
        )
        if seen_external_ids:
            stale_query = stale_query.where(GovSupportProgram.external_id.notin_(seen_external_ids))
            stale = session.execute(stale_query).scalars().all()
            for row in stale:
                row.is_active = False
            session.commit()

    print(f"[OK] upsert {upserted}건 (재임베딩 {reembedded}건), 실패 {failed}건, 비활성화 {len(stale)}건")


if __name__ == "__main__":
    run()
