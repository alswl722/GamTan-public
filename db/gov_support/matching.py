"""정부 지원사업 매칭 — 기업 프로필과 gov_support_programs 후보 간 코사인 유사도.
docs/gov-support-matching-plan.md §4·§5·§6-2·§6-4·§6-5 정본.

매칭 자체(어떤 사업이 상위로 올라오는지)는 이 모듈의 결정론적 코사인 유사도
계산이 결정한다 — LLM은 evidence 문장만 생성하고(호출부인 api/routers/owner.py가
후보 목록을 받은 뒤 별도로 호출) 목록 자체는 안 바꾼다(CLAUDE.md 원칙1과 동일한 결).

top_k·similarity_threshold는 상수가 아니라 함수 인자로 받는다 — 실 데이터로
튜닝한 값이 바뀌어도 이 로직 코드는 안 건드리고 기본값만 바꾸면 된다(§6-4).
"""
import math
import time
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.gov_support.embeddings import embed_query
from db.models import Company, GovSupportProgram

# 활성 지원사업(임베딩 포함) 인메모리 캐시. 2026-08-18 실측: 이 컬럼(JSON,
# 768차원)을 요청마다 Supabase에서 새로 읽으면 67건 기준 8~10초가 걸린다
# (id+텍스트만 읽으면 0.2초 — 네트워크로 실어나르는 데이터량 자체가 병목,
# DB 왕복 횟수 문제가 아님을 단계별로 격리해서 확인). 이 데이터는 배치가
# 하루 1회만 바꾸므로, 몇 분 정도의 지연은 감수하고 캐싱해 매 요청 DB
# 왕복을 없앤다. DB(엔진 URL) 단위로 캐시를 분리한다 — 안 그러면 테스트마다
# 새로 만드는 SQLite 파일들이 서로 다른데도 같은 프로세스 안에서 캐시를
# 공유해버려 테스트 격리가 깨진다.
_CACHE_TTL_SECONDS = 300
_program_cache: dict[str, tuple[float, list[dict]]] = {}

DEFAULT_TOP_K = 5
# 2026-08-18 실 데이터 튜닝(scripts/tune_gov_support_threshold.py, 시연 기업
# 구미정밀 기준) — 0.65는 진짜 관련 있는 사업(에너지효율 혁신, CBAM 대응,
# 온실가스 국제감축 등)을 다 걸러내고 일반 경쟁력강화 자금 2건만 남겼다.
# 0.60으로 낮추면 21건이 통과하고 상위권이 실제로 그럴듯하다 — docs/
# gov-support-matching-plan.md §6-4 정본.
DEFAULT_SIMILARITY_THRESHOLD = 0.60

# 실측(2026-08-18, §6-5): 지역 한정 공고는 hashtags 지역 토큰이 1개, 전국 대상은
# 대부분의 지역이 다 나열됨(당시 16개 중 다수) — 이 임계값 이상이면 전국으로 간주.
_NATIONAL_REGION_TAG_THRESHOLD = 10

_FUEL_LABELS = {
    "diesel": "경유", "gasoline": "휘발유", "city_gas": "도시가스",
    "lpg": "LPG", "electricity": "전기",
}


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def is_region_eligible(company_region: str | None, program_region_tags: str | None) -> bool:
    """지역 자격 하드 필터(§6-5) — 유사도 계산 전에 결정론적으로 판정한다.

    region_tags가 없으면 통과(태그 자체가 없는 공고는 안전하게 포함), 토큰 수가
    임계값 이상이면 전국 사업으로 간주해 통과, 그 외엔 company.region(예: "경북
    구미")의 앞 토큰이 지역 태그에 포함될 때만 통과한다.
    """
    if not program_region_tags:
        return True
    tags = [t.strip() for t in program_region_tags.split(",") if t.strip()]
    if len(tags) >= _NATIONAL_REGION_TAG_THRESHOLD:
        return True
    if not company_region:
        return True  # 기업 지역 정보가 없으면 배제하지 않음(안전하게 포함)
    company_region_code = company_region.split()[0]  # "경북 구미" → "경북"
    return company_region_code in tags


def company_profile_text(company: Company) -> str:
    """임베딩 쿼리 대상 텍스트 — 업종명·지역·종업원수·연료유형(원칙6과 같은 결로
    사장님이 체크한 연료만 반영)."""
    parts = [company.industry_name or "", company.region or ""]
    if company.employee_count:
        parts.append(f"상시근로자 {company.employee_count}명")
    fuel_types = company.fuel_types_json or {}
    used_fuels = [label for key, label in _FUEL_LABELS.items() if fuel_types.get(key)]
    if used_fuels:
        parts.append(" ".join(used_fuels) + " 사용")
    return " ".join(p for p in parts if p)


def _load_active_programs(session: Session) -> list[dict]:
    """활성 지원사업 스냅숏(캐시 적중 시 DB 왕복 없음). ORM 인스턴스가 아니라
    plain dict로 캐싱한다 — 세션이 닫힌 뒤에도(다음 요청은 새 세션) 안전하게
    재사용하려면 detached-instance 문제를 피해야 한다."""
    key = str(session.get_bind().url)
    now = time.monotonic()
    cached = _program_cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    rows = session.execute(
        select(GovSupportProgram).where(GovSupportProgram.is_active.is_(True))
    ).scalars().all()
    snapshot = [
        {
            "id": p.id,
            "program_name": p.program_name,
            "agency_name": p.agency_name,
            "apply_end_date": p.apply_end_date,
            "detail_url": p.detail_url,
            "region_tags": p.region_tags,
            "raw_text": p.raw_text,
            "embedding": p.embedding,
        }
        for p in rows
    ]
    _program_cache[key] = (now, snapshot)
    return snapshot


def latest_fetched_at(session: Session):
    """배치가 마지막으로 성공 수집한 시각(활성 행 기준 최댓값) — API의 as_of 필드용.
    행이 하나도 없으면 None(배치가 한 번도 안 돎, §7 실패 가시성과 같은 결로
    호출부가 별도 안내 문구를 만들 수 있게 둔다)."""
    return session.execute(
        select(func.max(GovSupportProgram.fetched_at)).where(GovSupportProgram.is_active.is_(True))
    ).scalar()


def raw_text_by_program_id(session: Session, program_ids: list[int]) -> dict[int, str]:
    """근거문장 생성용 raw_text 조회 — 캐시를 그대로 재사용해 후보별로 따로
    session.get()을 호출하지 않는다(그것도 각 호출이 DB 왕복이라 후보 5건이면
    5번 더 왕복이 쌓인다, 2026-08-18 실측으로 확인)."""
    programs = _load_active_programs(session)
    wanted = set(program_ids)
    return {p["id"]: p["raw_text"] or "" for p in programs if p["id"] in wanted}


def match_gov_support_programs(
    session: Session,
    company_id: int,
    *,
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[dict]:
    """기업 프로필 기반 top-K 지원사업 후보. evidence 문장은 안 채운다 —
    호출부(API 라우터)가 이 결과를 받은 뒤 LLM으로 별도 생성한다(§4)."""
    company = session.get(Company, company_id)
    if company is None:
        return []

    today = date.today()
    programs = _load_active_programs(session)
    # 마감일 필터: null(파싱 실패·상시모집)은 마감된 것으로 취급하지 않는다(§6 주의사항)
    not_expired = [p for p in programs if p["apply_end_date"] is None or p["apply_end_date"] >= today]
    eligible = [p for p in not_expired if is_region_eligible(company.region, p["region_tags"])]
    with_embedding = [p for p in eligible if p["embedding"]]
    if not with_embedding:
        return []

    query_embedding = embed_query(company_profile_text(company))
    if query_embedding is None:
        return []  # 임베딩 실패 — 억지로 후보를 채우지 않는다(CLAUDE.md §6 실패 가시성)

    scored = [(p, cosine_similarity(query_embedding, p["embedding"])) for p in with_embedding]
    scored = [(p, sim) for p, sim in scored if sim >= similarity_threshold]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    top = scored[:top_k]

    return [
        {
            "program_id": p["id"],
            "program_name": p["program_name"],
            "agency_name": p["agency_name"],
            "apply_end_date": p["apply_end_date"].isoformat() if p["apply_end_date"] else None,
            "detail_url": p["detail_url"],
            "similarity": round(sim, 4),
        }
        for p, sim in top
    ]
