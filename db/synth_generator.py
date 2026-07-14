"""합성 전표 생성기 (파라미터형) — 뼈대.

파라미터만 바꿔 N건의 전표를 찍어내고, **정답 라벨을 동시에 출력**한다.
- 결손(gap_months)·이상치(anomaly) 시나리오 파라미터화
- 표현 변형(비정형 텍스트) 무작위 삽입 → LLM 분류 강건성 테스트용
- seed 고정 → 항상 같은 데이터(재현성)

⚠️ 생성기 정답은 "분류 강건성 테스트"용이지 최종 신뢰도 증명이 아니다.
   (신뢰도는 공개 실측 대조 = 트랙 A/B). 표현·금액은 최소 세트 — 회계가 확장.

사용:
  python -m db.synth_generator --count 50 --gap 3,4,5 --anomaly 7:경유:3.2 --seed 42 --out db/fixtures/synth_50.json
"""
import argparse
import json
import random
import sys
from dataclasses import dataclass, field

# 연료 → 비정형 표현들 + 정답 라벨 + (사람도 애매한 표현 = HITL 기대)
# 현장 세금계산서 품목명은 제각각 → 최대한 지저분하게. ambiguous 는 사람도 헷갈리는 표기.
FUEL_EXPRESSIONS = {
    "경유": {
        "exprs": [
            "경유", "경유 외 1종", "경유 외 2종", "지게차 경유 외 1종", "동절기 난방유",
            "유류대금", "유류비 정산", "차량 주유대", "면세유(경유)", "경유(산업용)",
            "지게차·화물차 경유", "디젤유", "차량유류비", "경유대금 3월분", "주유대(경유)",
        ],
        "label": {"scope": 1, "category": "이동연소", "fuel": "경유"},
        # 경유/휘발유 구분 불가하거나 항목 불명확 → HITL 기대
        "ambiguous": {"유류대금", "유류비 정산", "차량 주유대", "차량유류비", "주유대(경유)"},
    },
    "도시가스": {
        "exprs": [
            "도시가스", "도시가스 요금", "도시가스 (동절기 난방)", "LNG 도시가스",
            "공장 난방 가스비", "취사·난방 도시가스", "가스요금", "도시가스 정산분",
            "산업용 도시가스", "가스사용료", "동절기 가스대금",
        ],
        "label": {"scope": 1, "category": "고정연소", "fuel": "도시가스"},
        # 'LPG인지 도시가스인지' 불명확한 표기 → HITL 기대
        "ambiguous": {"가스요금", "가스사용료"},
    },
    "전기": {
        "exprs": [
            "전기요금 (산업용 을)", "전기료", "공장 전력 사용료", "한국전력 전기요금",
            "산업용전력(을)고압A", "전력량요금+기본요금", "전기 사용료 정산",
            "한전 전기료", "산업용 전력요금", "전력사용료(공장)",
        ],
        "label": {"scope": 2, "category": "간접배출", "fuel": "전기"},
        "ambiguous": set(),
    },
}
SOURCE = {"경유": "hometax", "도시가스": "hometax", "전기": "kepco"}
BASE_AMOUNT = {"경유": 650_000, "도시가스": 900_000, "전기": 3_500_000}  # 월 기준 공급가액 (규모=1.0 기준)
# 도시가스 계절 가중 (동절기↑, 하절기↓)
GAS_SEASON = {1: 1.5, 2: 1.4, 3: 1.1, 4: 0.8, 5: 0.6, 6: 0.4,
              7: 0.4, 8: 0.4, 9: 0.5, 10: 0.8, 11: 1.2, 12: 1.5}

# 시연 기업들 (이름, 규모배수) — 규모배수로 금액 스케일 다양화. 0번이 데모 기업 ○○정밀
COMPANIES = [
    ("○○정밀", 1.0), ("대성표면처리", 1.4), ("구미정공", 0.7), ("한빛금속", 1.3),
    ("성진열처리", 1.7), ("동양기계공업", 0.9), ("우진테크", 1.1), ("삼도정밀", 0.6),
    ("금성공업", 1.5), ("태창금속", 1.2), ("대한열처리", 0.8), ("신성정공", 1.6),
]


def _company(ci: int) -> tuple[str, float]:
    """인덱스 → (기업명, 규모배수). 목록 초과 시 번호 붙여 순환."""
    if ci < len(COMPANIES):
        return COMPANIES[ci]
    base = COMPANIES[ci % len(COMPANIES)]
    return (f"{base[0]}-{ci // len(COMPANIES) + 1}", base[1])


@dataclass
class GenConfig:
    count: int = 50
    year: int = 2024
    gap_months: list = field(default_factory=lambda: [3, 4, 5])  # 도시가스 결손 월
    anomaly: dict | None = None  # {"month":7, "fuel":"경유", "multiplier":3.2}
    seed: int = 42
    companies: int = 1  # 생성할 기업 수 (1=데모 기업만). 대량 생성 시 늘림


def generate(cfg: GenConfig, expressions: dict | None = None) -> list[dict]:
    # 표현 사전: Excel 제공분이 있으면 내장 위에 덮어쓰기 (없는 연료는 내장으로 폴백)
    expr_map = FUEL_EXPRESSIONS if not expressions else {**FUEL_EXPRESSIONS, **expressions}
    records: list[dict] = []
    for ci in range(max(1, cfg.companies)):
        name, size = _company(ci)
        crnd = random.Random(cfg.seed + ci * 1009)  # 기업별 독립 난수(재현성 유지)
        scenario = ci == 0  # 결손·이상치는 데모 기업(0번)에만 — 나머지는 정상 12개월
        for month in range(1, 13):
            for fuel in ("전기", "도시가스", "경유"):
                # 결손 시나리오: 지정 월의 도시가스는 생성하지 않음
                if fuel == "도시가스" and scenario and month in cfg.gap_months:
                    continue
                base = BASE_AMOUNT[fuel] * size
                if fuel == "도시가스":
                    base *= GAS_SEASON.get(month, 0.6)
                amount = int(base * crnd.uniform(0.88, 1.12))
                # 이상치 시나리오: 지정 월×연료 금액에 배수 적용 (데모 기업만)
                if scenario and cfg.anomaly and cfg.anomaly["month"] == month and cfg.anomaly["fuel"] == fuel:
                    amount = int(amount * cfg.anomaly["multiplier"])

                info = expr_map[fuel]
                expr = crnd.choice(info["exprs"])
                label = dict(info["label"])
                label["expected_hitl"] = expr in info["ambiguous"]

                records.append({
                    "company": name,
                    "source": SOURCE[fuel],
                    "year": cfg.year,
                    "month": month,
                    "item_description": expr,
                    "supply_amount_krw": amount,
                    "label": label,  # 정답지 (엔진과 무관하게 생성 시점에 확정)
                })
    return records[: cfg.count] if 0 < cfg.count < len(records) else records


def _parse_anomaly(s: str | None) -> dict | None:
    if not s:
        return None
    month, fuel, mult = s.split(":")
    return {"month": int(month), "fuel": fuel, "multiplier": float(mult)}


def _flatten(recs):
    """중첩 label 을 컬럼으로 펼침 (CSV·Excel 용)."""
    rows = []
    for r in recs:
        lab = r.get("label", {})
        rows.append({
            "company": r.get("company", ""),
            "source": r["source"], "year": r["year"], "month": r["month"],
            "item_description": r["item_description"],
            "supply_amount_krw": r["supply_amount_krw"],
            "scope": lab.get("scope"), "category": lab.get("category"),
            "fuel": lab.get("fuel"), "expected_hitl": lab.get("expected_hitl"),
        })
    return rows


def _write_records(path, recs):
    """확장자로 형식 분기: .csv / .xlsx / .json."""
    import os
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        import csv
        rows = _flatten(recs)
        with open(path, "w", encoding="utf-8-sig", newline="") as fp:  # BOM → 엑셀 한글 정상
            w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    elif ext == ".xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            raise SystemExit("[!] .xlsx 출력엔 openpyxl 필요 → 'pip install openpyxl' 또는 .csv 사용")
        rows = _flatten(recs)
        wb = Workbook(); ws = wb.active; ws.title = "합성전표"
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
        wb.save(path)
    else:  # json (기본)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(json.dumps(recs, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description="합성 전표 생성기 (파라미터형)")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--gap", default="3,4,5", help="도시가스 결손 월 (콤마)")
    p.add_argument("--anomaly", default="7:경유:3.2", help="이상치 '월:연료:배수'")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--companies", type=int, default=1,
                   help="생성할 기업 수 (1=데모 기업만, 대량 생성 시 늘림. 기업당 최대 36건)")
    p.add_argument("--out", default=None,
                   help="저장 경로. 확장자로 형식 결정: .json / .csv(엑셀에서 열림) / .xlsx (없으면 stdout)")
    p.add_argument("--from-excel", nargs="?", const="DEFAULT", default=None,
                   help="회계 Excel의 전표_샘플 표현 사용 (경로 생략 시 data/ 기본 파일)")
    a = p.parse_args()

    cfg = GenConfig(
        count=a.count,
        year=a.year,
        gap_months=[int(x) for x in a.gap.split(",") if x.strip()],
        anomaly=_parse_anomaly(a.anomaly),
        seed=a.seed,
        companies=a.companies,
    )

    expressions = None
    if getattr(a, "from_excel", None) is not None:
        from db.excel_loader import DEFAULT_XLSX, load_expressions
        path = DEFAULT_XLSX if a.from_excel == "DEFAULT" else a.from_excel
        try:
            expressions = load_expressions(path)
            print(f"[i] Excel 표현 사용: {path} (연료 {list(expressions)})", file=sys.stderr)
        except (FileNotFoundError, LookupError) as e:
            print(f"[i] Excel 표현 미사용({e}) → 내장 사전", file=sys.stderr)

    recs = generate(cfg, expressions)
    if a.count and len(recs) < a.count:
        need = -(-a.count // 33)  # 기업당 약 33~36건
        print(f"[i] {a.count}건 요청했지만 기업 {a.companies}개로는 {len(recs)}건이 최대입니다. "
              f"--companies {need} 이상으로 늘리세요.", file=sys.stderr)
    recs = recs[: a.count] if 0 < a.count < len(recs) else recs
    if a.out:
        _write_records(a.out, recs)
        gaps = sorted({r["month"] for r in recs if r["source"] == "hometax" and "가스" in r["item_description"]})
        print(f"[OK] {len(recs)}건 생성 → {a.out}")
        print(f"     도시가스 존재 월: {gaps} (결손 {cfg.gap_months} 확인)")
    else:
        print(json.dumps(recs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
