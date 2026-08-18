"""기업마당(bizinfo.go.kr) 지원사업정보 API 클라이언트.

docs/gov-support-matching-plan.md §3·§3-1·§6-3 정본. 이 모듈은 API 호출과
필드 매핑만 담당한다 — 저장(upsert)은 scripts/fetch_gov_support_programs.py,
임베딩·유사도 매칭은 db/gov_support/matching.py가 각각 담당한다.

API 키는 공공데이터포털이 아니라 bizinfo.go.kr 자체 발급(BIZINFO_API_KEY,
crtfcKey 파라미터로 전달). 엔드포인트는 searchCnt를 크게 주면 페이지네이션
없이 전체 공고가 한 번에 온다(2026-08-18 실측: 1524건 전체가 한 호출로 옴) —
hashtags 사전 필터는 재현율 손실 위험이 있어 안 쓴다(§3 정정).
"""
import html
import json
import re
import urllib.parse
import urllib.request

ENDPOINT = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"

# §3 실측 확정 키워드 — 탄소중립·설비투자 관련 공고만 후보로 추린다. "그린"은
# "그린바이오"(생명공학, 무관) 오탐이 섞이는 게 확인됐지만(§3), 그 뒤 임베딩
# 유사도 단계가 걸러주므로 이 단계에서는 다소 넓게 잡는다.
KEYWORDS = [
    "탄소", "그린", "온실가스", "탄소중립", "탄소저감", "저탄소", "배출권", "배출량",
    "설비투자", "설비교체", "노후설비", "에너지효율", "에너지진단", "RE100", "친환경",
    "ESG", "클린팩토리",
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    """bsnsSumryCn 등 HTML이 섞인 필드에서 태그를 제거하고 공백을 정리한다."""
    if not text:
        return ""
    unescaped = html.unescape(_TAG_RE.sub(" ", text))
    return _WS_RE.sub(" ", unescaped).strip()


def fetch_raw_items(api_key: str, *, search_cnt: int = 3000, timeout: int = 30) -> list[dict]:
    """전체 공고를 한 번의 호출로 가져온다(§3 실측 — 페이지네이션 불필요)."""
    query = urllib.parse.urlencode({
        "crtfcKey": api_key,
        "dataType": "json",
        "searchCnt": str(search_cnt),
    })
    url = f"{ENDPOINT}?{query}"
    with urllib.request.urlopen(url, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    items = data.get("jsonArray", [])
    return items if isinstance(items, list) else [items]


def matches_keywords(item: dict) -> list[str]:
    """공고명·사업개요·지원대상 텍스트에서 걸리는 키워드 목록(빈 리스트면 후보 제외)."""
    text = " ".join([
        item.get("pblancNm", "") or "",
        strip_html(item.get("bsnsSumryCn")),
        item.get("trgetNm", "") or "",
    ])
    return [k for k in KEYWORDS if k in text]


# 실측(2026-08-18, §3-1): hashtags에 담긴 지역명 토큰. 전체 목록에 "전남광주"처럼
# 통합 표기가 섞여 있어 그대로 유지한다(원본 API 표기 그대로 매칭).
_REGION_WORDS = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
    "충북", "충남", "전북", "전남", "경북", "경남", "제주", "전남광주",
]


def extract_region_tags(item: dict) -> str | None:
    """hashtags에서 지역명 토큰만 추출해 콤마로 이어 반환(없으면 None).
    지역 자격 판정 자체는 db/gov_support/matching.py::is_region_eligible이 한다."""
    hashtags = item.get("hashtags", "") or ""
    tags = [t.strip() for t in hashtags.split(",")]
    region_tags = [t for t in tags if t in _REGION_WORDS]
    return ",".join(region_tags) if region_tags else None


_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")


def parse_apply_period(raw: str | None) -> tuple[str | None, str | None]:
    """reqstBeginEndDe 원문에서 "YYYY-MM-DD ~ YYYY-MM-DD" 형태만 파싱한다.
    "모집 완료시"·"예산 소진시까지" 등은 파싱 실패로 (None, None) — 원문은
    호출부가 apply_period_raw에 그대로 저장한다(§3-1 실측 확인 케이스)."""
    if not raw:
        return None, None
    match = _DATE_RANGE_RE.search(raw)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def normalize_item(item: dict) -> dict:
    """bizinfo 원본 필드를 gov_support_programs 컬럼명으로 매핑(§3-1 정본)."""
    start, end = parse_apply_period(item.get("reqstBeginEndDe"))
    summary = strip_html(item.get("bsnsSumryCn"))
    target = (item.get("trgetNm", "") or "").strip()
    return {
        "external_id": item.get("pblancId"),
        "program_name": item.get("pblancNm"),
        "category": item.get("pldirSportRealmLclasCodeNm"),
        "agency_name": item.get("jrsdInsttNm"),
        "apply_start_date": start,
        "apply_end_date": end,
        "apply_period_raw": item.get("reqstBeginEndDe"),
        "region_tags": extract_region_tags(item),
        "detail_url": item.get("pblancUrl"),
        "raw_text": f"{summary} {target}".strip(),
    }
