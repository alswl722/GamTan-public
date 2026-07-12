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
from dataclasses import dataclass, field

# 연료 → 비정형 표현들 + 정답 라벨 + (사람도 애매한 표현)
FUEL_EXPRESSIONS = {
    "경유": {
        "exprs": ["경유", "경유 외 1종", "유류대금", "지게차 경유 외 1종", "동절기 난방유"],
        "label": {"scope": 1, "category": "이동연소", "fuel": "경유"},
        "ambiguous": {"유류대금"},  # 경유/휘발유 구분 불가 → HITL 기대
    },
    "도시가스": {
        "exprs": ["도시가스", "도시가스 요금", "도시가스 (동절기 난방)"],
        "label": {"scope": 1, "category": "고정연소", "fuel": "도시가스"},
        "ambiguous": set(),
    },
    "전기": {
        "exprs": ["전기요금 (산업용 을)", "전기료", "공장 전력 사용료"],
        "label": {"scope": 2, "category": "간접배출", "fuel": "전기"},
        "ambiguous": set(),
    },
}
SOURCE = {"경유": "hometax", "도시가스": "hometax", "전기": "kepco"}
BASE_AMOUNT = {"경유": 650_000, "도시가스": 900_000, "전기": 3_500_000}  # 월 기준 공급가액
# 도시가스 계절 가중 (동절기↑, 하절기↓)
GAS_SEASON = {1: 1.5, 2: 1.4, 3: 1.1, 4: 0.8, 5: 0.6, 6: 0.4,
              7: 0.4, 8: 0.4, 9: 0.5, 10: 0.8, 11: 1.2, 12: 1.5}


@dataclass
class GenConfig:
    count: int = 50
    year: int = 2024
    gap_months: list = field(default_factory=lambda: [3, 4, 5])  # 도시가스 결손 월
    anomaly: dict | None = None  # {"month":7, "fuel":"경유", "multiplier":3.2}
    seed: int = 42


def generate(cfg: GenConfig, expressions: dict | None = None) -> list[dict]:
    # 표현 사전: Excel 제공분이 있으면 내장 위에 덮어쓰기 (없는 연료는 내장으로 폴백)
    expr_map = FUEL_EXPRESSIONS if not expressions else {**FUEL_EXPRESSIONS, **expressions}
    rnd = random.Random(cfg.seed)
    records: list[dict] = []
    for month in range(1, 13):
        for fuel in ("전기", "도시가스", "경유"):
            # 결손 시나리오: 지정 월의 도시가스는 생성하지 않음
            if fuel == "도시가스" and month in cfg.gap_months:
                continue
            base = BASE_AMOUNT[fuel]
            if fuel == "도시가스":
                base = int(base * GAS_SEASON.get(month, 0.6))
            amount = int(base * rnd.uniform(0.9, 1.1))
            # 이상치 시나리오: 지정 월×연료 금액에 배수 적용
            if cfg.anomaly and cfg.anomaly["month"] == month and cfg.anomaly["fuel"] == fuel:
                amount = int(amount * cfg.anomaly["multiplier"])

            info = expr_map[fuel]
            expr = rnd.choice(info["exprs"])
            label = dict(info["label"])
            label["expected_hitl"] = expr in info["ambiguous"]

            records.append({
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


def main():
    p = argparse.ArgumentParser(description="합성 전표 생성기 (파라미터형)")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--gap", default="3,4,5", help="도시가스 결손 월 (콤마)")
    p.add_argument("--anomaly", default="7:경유:3.2", help="이상치 '월:연료:배수'")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default=None, help="JSON 저장 경로 (없으면 stdout)")
    p.add_argument("--from-excel", nargs="?", const="DEFAULT", default=None,
                   help="회계 Excel의 전표_샘플 표현 사용 (경로 생략 시 data/ 기본 파일)")
    a = p.parse_args()

    cfg = GenConfig(
        count=a.count,
        year=a.year,
        gap_months=[int(x) for x in a.gap.split(",") if x.strip()],
        anomaly=_parse_anomaly(a.anomaly),
        seed=a.seed,
    )

    expressions = None
    if getattr(a, "from_excel", None) is not None:
        from db.excel_loader import DEFAULT_XLSX, load_expressions
        path = DEFAULT_XLSX if a.from_excel == "DEFAULT" else a.from_excel
        try:
            expressions = load_expressions(path)
            print(f"[i] Excel 표현 사용: {path} (연료 {list(expressions)})")
        except (FileNotFoundError, LookupError) as e:
            print(f"[i] Excel 표현 미사용({e}) → 내장 사전")

    recs = generate(cfg, expressions)
    out = json.dumps(recs, ensure_ascii=False, indent=2)
    if a.out:
        import os
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fp:
            fp.write(out)
        gaps = sorted({r["month"] for r in recs if r["source"] == "hometax" and "가스" in r["item_description"]})
        print(f"[OK] {len(recs)}건 생성 → {a.out}")
        print(f"     도시가스 존재 월: {gaps} (결손 {cfg.gap_months} 확인)")
    else:
        print(out)


if __name__ == "__main__":
    main()
