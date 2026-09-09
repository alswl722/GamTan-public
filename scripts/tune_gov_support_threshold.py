"""유사도 임계값·top-K 튜닝 — 실 데이터 확보 후 회계·도메인 최종 검토용.
docs/gov-support-matching-plan.md §6-4·§10 정본.

시연 기업(○○정밀 등) 프로필로 전체 후보의 유사도 순위와 threshold별 통과
건수를 뽑는다 — 회계·도메인이 이 출력을 보고 "그럴듯한 사업이 상위에
오는지, 엉뚱한 게 안 섞이는지" 판단해서 db/gov_support/matching.py의
DEFAULT_TOP_K·DEFAULT_SIMILARITY_THRESHOLD 기본값을 확정한다. 이 스크립트
자체는 아무것도 쓰지 않는다(읽기 전용 — DB에 반영하려면 matching.py 기본값을
직접 고친다).

사용: .venv/bin/python scripts/tune_gov_support_threshold.py [company_id]
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_engine
from db.gov_support.embeddings import embed_query
from db.gov_support.matching import company_profile_text, cosine_similarity, is_region_eligible
from db.models import Company, GovSupportProgram

THRESHOLD_CANDIDATES = [0.55, 0.60, 0.65, 0.70, 0.75]


def run(company_id: int) -> None:
    with Session(get_engine()) as session:
        company = session.get(Company, company_id)
        if company is None:
            print(f"기업 {company_id}를 찾을 수 없습니다")
            return

        profile = company_profile_text(company)
        print(f"기업: {company.name} | 프로필: {profile}\n")

        query_embedding = embed_query(profile)
        if query_embedding is None:
            print("쿼리 임베딩 실패 (GEMINI_API_KEY 확인)")
            return

        today = date.today()
        programs = session.execute(
            select(GovSupportProgram).where(GovSupportProgram.is_active.is_(True))
        ).scalars().all()
        not_expired = [p for p in programs if p.apply_end_date is None or p.apply_end_date >= today]
        eligible = [p for p in not_expired if is_region_eligible(company.region, p.region_tags)]
        with_embedding = [p for p in eligible if p.embedding]

        print(
            f"전체 {len(programs)}건 → 마감제외 {len(not_expired)}건 → "
            f"지역자격 {len(eligible)}건 → 임베딩보유 {len(with_embedding)}건\n"
        )

        scored = sorted(
            [(p, cosine_similarity(query_embedding, p.embedding)) for p in with_embedding],
            key=lambda pair: pair[1],
            reverse=True,
        )

        print("=== 전체 유사도 순위 (상위 20) ===")
        for p, sim in scored[:20]:
            print(f"{sim:.4f}  {p.program_name}  ({p.agency_name})")

        print("\n=== threshold별 통과 건수 ===")
        for threshold in THRESHOLD_CANDIDATES:
            count = len([1 for _, sim in scored if sim >= threshold])
            print(f"threshold={threshold}: {count}건 통과")


if __name__ == "__main__":
    company_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    run(company_id)
