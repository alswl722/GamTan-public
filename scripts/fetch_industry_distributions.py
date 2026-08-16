"""업종별 배출량 분포(industry_distributions) 실데이터 스냅숏 생성.

한국에너지공단 "에너지 사용 및 온실가스 배출량 통계-마이크로데이터"
(공공데이터포털, GHG_LIST_04_03 — 업종별 CO2·GHG 배출량 현황)에서 사업장 단위
익명 마이크로데이터를 전량 수집해, (업종코드×Scope×종사자규모×연도) 조합별
min/median/max/표본수를 계산하고 `data/industry_distributions.xlsx`에 저장한다.

라이브 API를 매번 부르지 않고 스냅숏 파일을 커밋해두는 이유는 배출계수·환산단가와
같은 원칙(CLAUDE.md §5-4) — 재현성·비용, API 장애가 서비스 가동에 영향을 주지
않게 하기 위함이다. `data/industry_distributions.xlsx`는 이 스크립트 재실행으로만
갱신하고 손으로 고치지 않는다(회계 담당이 관리하는 배출계수·단가 시트와는 성격이
다름 — 그쪽은 사람이 관리하는 원천, 이쪽은 공공데이터의 기계적 재가공 결과).

한 사업장이 에너지원(전력/기타연료 등)별로 여러 행을 가질 수 있어, 사업장 단위
Scope 합계를 먼저 만든 뒤(1차 그룹핑) 그 합계들로 분포를 계산한다(2차 그룹핑) —
그렇지 않으면 같은 사업장의 여러 행이 서로 다른 "회사"인 것처럼 분포에 섞여 든다.

100toe 이상 배출 사업장은 실측치 대신 100분위 등수만 내려오므로(GHG_EMSN_QNTY_YN=1)
등수를 배출량인 척 섞지 않도록 제외한다 — 우리 타깃(SME)은 대부분 그 문턱 아래다.

사용:  .venv/bin/python scripts/fetch_industry_distributions.py
"""
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = "https://apis.data.go.kr/B553530/GHG_LIST_040/GHG_LIST_04_03_20220831_VIEW01"
# 요청 numOfRows와 무관하게 서버가 실제로는 최대 100건만 돌려준다(응답 메타의
# numOfRows는 요청값을 그대로 echo할 뿐 실제 반환 건수와 다름 — 실측으로 확인).
PAGE_SIZE = 100
OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "industry_distributions.xlsx"
)

# C251/C259는 기존 시연 기업이 쓰는 업종명과 맞춘다(db/init_db.py 옛 하드코딩 값과 동일).
# 그 외 업종코드는 그룹 안에서 가장 많이 등장한 5자리 KSIC명을 대표명으로 쓴다.
CANONICAL_NAMES = {
    "C251": "구조용 금속제품 제조",
    "C259": "기타 금속가공제품 제조",
}

# emission_median_per_employee(참고용) 계산에 쓰는 밴드 중간값 근사치 — 실제 인원이
# 아니라 밴드 대표값이라 참고용 필드로만 채운다.
BAND_MIDPOINT = {
    "5인 미만": 3,
    "5인 ~ 9인": 7,
    "10인 ~ 19인": 15,
    "20인 ~ 49인": 35,
    "50인 ~ 99인": 75,
    "100인 ~ 299인": 200,
    "300인 ~ 499인": 400,
    "500인 ~ 999인": 750,
    "1000인 이상": 1500,
}


def _fetch_page(key: str, page_no: int) -> dict:
    url = f"{ENDPOINT}?ServiceKey={key}&apiType=JSON&numOfRows={PAGE_SIZE}&pageNo={page_no}"
    with urllib.request.urlopen(url, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def fetch_all_rows(key: str) -> list[dict]:
    """전량 페이지네이션 수집. 개별 페이지 실패는 건너뛰고 계속 진행(실패 가시성)."""
    first = _fetch_page(key, 1)
    body = first.get("response", {}).get("body", {})
    total = body.get("totalCount", 0)
    print(f"[i] 전체 {total}건, 페이지당 {PAGE_SIZE}건")

    rows: list[dict] = []
    items = body.get("items") or {}
    item_list = items.get("item", [])
    if isinstance(item_list, dict):
        item_list = [item_list]
    rows.extend(item_list)

    page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
    for page_no in range(2, page_count + 1):
        try:
            data = _fetch_page(key, page_no)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  [FAIL] page {page_no}: {e}")
            continue
        body = data.get("response", {}).get("body", {})
        items = body.get("items") or {}
        item_list = items.get("item", [])
        if isinstance(item_list, dict):
            item_list = [item_list]
        rows.extend(item_list)
        if page_no % 10 == 0 or page_no == page_count:
            print(f"  [OK] page {page_no}/{page_count} (누적 {len(rows)}건)")

    return rows


def build_distributions(rows: list[dict]) -> list[dict]:
    # 1차 그룹핑 — 사업장 1곳의 Scope별 총 배출량
    company_scope_total: dict[tuple, float] = defaultdict(float)
    company_meta: dict[tuple, dict] = {}
    for r in rows:
        if str(r.get("GHG_EMSN_QNTY_YN")) == "1":
            continue  # 100toe 이상 — 실측치 아닌 등수, 배출량 분포에서 제외
        ksic_cd = (r.get("KSIC_CD") or "").strip()
        if len(ksic_cd) < 3:
            continue
        industry_code = "C" + ksic_cd[:3]
        scope = 2 if r.get("ENGSRC_DVSN_NM") == "전력" else 1
        band = r.get("WRKPLC_WRKR_VOL_NM")
        year = r.get("TRGT_YEAR")
        fanm = r.get("WRKPLC_FANM")
        try:
            emsn = float(r.get("GHG_EMSN_QNTY_NIDVAL") or 0)
        except (TypeError, ValueError):
            continue

        key = (fanm, industry_code, scope, band, year)
        company_scope_total[key] += emsn
        company_meta[key] = {"ksic_nm": r.get("KSIC_NM")}

    # 2차 그룹핑 — 밴드별 분포 + 전체 규모 통합(worker_band=None) 분포
    banded: dict[tuple, list[float]] = defaultdict(list)
    pooled: dict[tuple, list[float]] = defaultdict(list)
    ksic_name_votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for (fanm, industry_code, scope, band, year), total in company_scope_total.items():
        banded[(industry_code, scope, band, year)].append(total)
        pooled[(industry_code, scope, year)].append(total)
        ksic_nm = company_meta[(fanm, industry_code, scope, band, year)]["ksic_nm"]
        if ksic_nm:
            ksic_name_votes[industry_code][ksic_nm] += 1

    def _industry_name(code: str) -> str:
        if code in CANONICAL_NAMES:
            return CANONICAL_NAMES[code]
        votes = ksic_name_votes.get(code)
        return max(votes, key=votes.get) if votes else code

    out = []
    source = "한국에너지공단 에너지사용 및 온실가스배출량 통계-마이크로데이터 (공공데이터포털 B553530/GHG_LIST_040)"

    for (industry_code, scope, band, year), values in banded.items():
        values.sort()
        out.append(
            dict(
                industry_code=industry_code,
                industry_name=_industry_name(industry_code),
                scope=scope,
                worker_band=band,
                emission_min_co2e=values[0],
                emission_median_co2e=statistics.median(values),
                emission_max_co2e=values[-1],
                emission_median_per_employee=(
                    statistics.median(values) / BAND_MIDPOINT[band] if band in BAND_MIDPOINT else None
                ),
                sample_size=len(values),
                year=int(year) if year else None,
                source=source,
            )
        )

    for (industry_code, scope, year), values in pooled.items():
        values.sort()
        out.append(
            dict(
                industry_code=industry_code,
                industry_name=_industry_name(industry_code),
                scope=scope,
                worker_band=None,  # 전체 규모 통합 — 좁은 밴드 표본 부족시 폴백용
                emission_min_co2e=values[0],
                emission_median_co2e=statistics.median(values),
                emission_max_co2e=values[-1],
                emission_median_per_employee=None,
                sample_size=len(values),
                year=int(year) if year else None,
                source=source,
            )
        )

    return out


def write_xlsx(dist_rows: list[dict], path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "업종분포"
    headers = [
        "업종코드", "업종명", "Scope", "종사자규모", "최소_tCO2e", "중앙값_tCO2e",
        "최대_tCO2e", "인당_중앙값_tCO2e", "표본수", "연도", "출처",
    ]
    ws.append(headers)
    for r in sorted(dist_rows, key=lambda x: (x["industry_code"], x["scope"], x["worker_band"] or "")):
        ws.append([
            r["industry_code"], r["industry_name"], r["scope"], r["worker_band"],
            round(r["emission_min_co2e"], 4), round(r["emission_median_co2e"], 4),
            round(r["emission_max_co2e"], 4),
            round(r["emission_median_per_employee"], 4) if r["emission_median_per_employee"] is not None else None,
            r["sample_size"], r["year"], r["source"],
        ])

    note = wb.create_sheet("안내")
    note.append(["이 파일은 scripts/fetch_industry_distributions.py 재실행으로만 갱신합니다."])
    note.append(["직접 수정하지 마세요 — 공공데이터(한국에너지공단 마이크로데이터) 기계 재가공 결과입니다."])

    wb.save(path)


def main() -> int:
    key = os.getenv("KEA_GHG_API_KEY")
    if not key:
        print("[!] KEA_GHG_API_KEY 미설정 — 적재 불가 (.env 확인)")
        return 1

    rows = fetch_all_rows(key)
    print(f"[i] 원본 {len(rows)}행 수집 완료")

    dist_rows = build_distributions(rows)
    print(f"[i] 분포 {len(dist_rows)}행 산출(밴드별 + 전체규모 통합 포함)")

    write_xlsx(dist_rows, OUT_PATH)
    print(f"[OK] {OUT_PATH} 저장 완료")

    codes = sorted({r["industry_code"] for r in dist_rows})
    print(f"[i] 업종코드 {len(codes)}종: {', '.join(codes[:20])}{' ...' if len(codes) > 20 else ''}")
    for target in ("C251", "C259"):
        matched = [r for r in dist_rows if r["industry_code"] == target]
        if matched:
            print(f"  [OK] {target}: {len(matched)}행 (표본수 예 {[m['sample_size'] for m in matched[:4]]})")
        else:
            print(f"  [!] {target}: 실데이터에 없음 — seed 폴백(하드코딩)이 계속 쓰일 수 있음")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
