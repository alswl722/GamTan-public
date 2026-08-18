"""기업마당 API 클라이언트 파싱 로직(db/gov_support/bizinfo_client.py) 골든 케이스.
docs/gov-support-matching-plan.md §3·§3-1 정본 — 2026-08-18 실측으로 확인된
케이스(신청기간이 날짜 범위가 아닌 경우, hashtags 지역 토큰 등)를 회귀 방지용으로 남긴다.
"""
from db.gov_support.bizinfo_client import (
    extract_region_tags,
    matches_keywords,
    normalize_item,
    parse_apply_period,
    strip_html,
)


def test_strip_html_removes_tags_and_collapses_whitespace():
    raw = "<p>국토교통부와  <br/>대구광역시</p>"
    assert strip_html(raw) == "국토교통부와 대구광역시"


def test_strip_html_handles_none():
    assert strip_html(None) == ""


def test_matches_keywords_finds_hits_in_title():
    item = {"pblancNm": "2026년 에너지효율시장 조성사업", "bsnsSumryCn": "", "trgetNm": ""}
    assert "에너지효율" in matches_keywords(item)


def test_matches_keywords_finds_hits_in_summary_html():
    item = {"pblancNm": "무관한 제목", "bsnsSumryCn": "<p>탄소중립 정책 대응</p>", "trgetNm": ""}
    assert "탄소중립" in matches_keywords(item)


def test_matches_keywords_empty_when_no_hit():
    item = {"pblancNm": "수출입 애로 바우처 지원사업", "bsnsSumryCn": "", "trgetNm": ""}
    assert matches_keywords(item) == []


def test_extract_region_tags_single_region():
    item = {"hashtags": "기술,경기,중소기업"}
    assert extract_region_tags(item) == "경기"


def test_extract_region_tags_national_all_regions():
    item = {"hashtags": "서울,부산,대구,인천,전남광주,대전,울산,세종,경기,강원,충북,충남,전북,경북,경남,제주"}
    tags = extract_region_tags(item)
    assert "경북" in tags and "대구" in tags


def test_extract_region_tags_none_when_no_region_words():
    item = {"hashtags": "기술,중소기업,2026"}
    assert extract_region_tags(item) is None


def test_extract_region_tags_missing_hashtags_field():
    assert extract_region_tags({}) is None


def test_parse_apply_period_valid_range():
    start, end = parse_apply_period("2026-08-14 ~ 2026-08-28")
    assert start == "2026-08-14"
    assert end == "2026-08-28"


def test_parse_apply_period_non_date_text_returns_none():
    # 실측(2026-08-18): "모집 완료시"·"예산 소진시까지" 등 날짜로 안 파싱되는 값 존재
    assert parse_apply_period("모집 완료시") == (None, None)
    assert parse_apply_period("예산 소진시까지") == (None, None)


def test_parse_apply_period_none_input():
    assert parse_apply_period(None) == (None, None)


def test_normalize_item_maps_bizinfo_fields():
    item = {
        "pblancId": "PBLN_000000000125497",
        "pblancNm": "김포시 에너지효율시장 조성사업",
        "pldirSportRealmLclasCodeNm": "경영",
        "jrsdInsttNm": "경기도",
        "reqstBeginEndDe": "2026-08-12 ~ 2026-08-28",
        "hashtags": "탄소,경기,에너지효율",
        "pblancUrl": "https://www.bizinfo.go.kr/example",
        "bsnsSumryCn": "<p>에너지 이용효율 향상 지원</p>",
        "trgetNm": "중소기업",
    }
    normalized = normalize_item(item)
    assert normalized["external_id"] == "PBLN_000000000125497"
    assert normalized["program_name"] == "김포시 에너지효율시장 조성사업"
    assert normalized["category"] == "경영"
    assert normalized["agency_name"] == "경기도"
    assert normalized["apply_start_date"] == "2026-08-12"
    assert normalized["apply_end_date"] == "2026-08-28"
    assert normalized["apply_period_raw"] == "2026-08-12 ~ 2026-08-28"
    assert normalized["region_tags"] == "경기"
    assert normalized["detail_url"] == "https://www.bizinfo.go.kr/example"
    assert "에너지 이용효율 향상 지원" in normalized["raw_text"]
    assert "중소기업" in normalized["raw_text"]
