"""데모 시나리오 — 여러 상황의 전표 세트를 company에 로드해 에이전트 행동을 관찰.

synth_generator(파라미터형)로 상황별 전표를 찍고, 대상 company의 기존
전표·분류·트레이스를 리셋한 뒤 재적재한다. 프론트 드롭다운/POST로 전환.

시나리오별로 에이전트가 다르게 판단:
- gas_gap     : 3~5월 도시가스 결손 → 결손 감지·사장 알림
- normal      : 결손·이상치 없음 → 알림 없이 분류·계산만
- diesel_spike: 7월 경유 급증(+'증차' 문구) → 이상치 의심·재검증·정상 판정
- multi_gap   : 다중 결손(3~5·10~11월 가스) → 다중 알림
"""
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db.models import Classification, TraceLog, Voucher
from db.synth_generator import GenConfig, generate

YEAR = 2024  # unit_prices 시딩 연도와 일치 (연도 정렬은 Excel 확정 후 Phase 3)

# 연료 → 거래처(공급자) 이름 합성용
_SUPPLIER = {"경유": "구미석유", "도시가스": "대성에너지", "전기": "한국전력공사"}


SCENARIOS: dict[str, dict] = {
    "gas_gap": {
        "label": "기본 · 3~5월 가스 결손",
        "config": GenConfig(count=0, year=YEAR, gap_months=[3, 4, 5], anomaly=None),
    },
    "normal": {
        "label": "정상 · 결손·이상치 없음",
        "config": GenConfig(count=0, year=YEAR, gap_months=[], anomaly=None),
    },
    "diesel_spike": {
        "label": "경유 이상치 · 7월 급증",
        "config": GenConfig(count=0, year=YEAR, gap_months=[],
                            anomaly={"month": 7, "fuel": "경유", "multiplier": 3.2}),
        # 이상치 재검증 시 에이전트가 읽을 '정상 사유' 문구를 해당 전표에 주입
        "justify": {"month": 7, "fuel": "경유", "text": "지게차 경유 (2대 증차분)"},
    },
    "multi_gap": {
        "label": "다중 결손 · 3~5·10~11월 가스",
        "config": GenConfig(count=0, year=YEAR, gap_months=[3, 4, 5, 10, 11], anomaly=None),
    },
}


def list_scenarios() -> list[dict]:
    return [{"name": k, "label": v["label"]} for k, v in SCENARIOS.items()]


def _reset_company(session: Session, company_id: int) -> None:
    """대상 company의 전표·분류·트레이스 삭제(FK 순서). company 행 자체는 유지."""
    vids = [r[0] for r in session.execute(
        select(Voucher.id).where(Voucher.company_id == company_id))]
    if vids:
        session.execute(delete(Classification).where(Classification.voucher_id.in_(vids)))
    session.execute(delete(Voucher).where(Voucher.company_id == company_id))
    session.execute(delete(TraceLog).where(TraceLog.company_id == company_id))
    session.commit()


def _to_voucher(rec: dict, company_id: int) -> Voucher:
    fuel = rec["label"]["fuel"]
    month = rec["month"]
    return Voucher(
        company_id=company_id,
        source=rec["source"],
        issue_date=datetime(rec["year"], month, 15, tzinfo=timezone.utc),
        year=rec["year"],
        month=month,
        supplier_name=_SUPPLIER.get(fuel, "미상"),
        item_description=rec["item_description"],
        supply_amount_krw=rec["supply_amount_krw"],
        raw_json=rec,
    )


def load_scenario(session: Session, company_id: int, name: str) -> dict:
    """시나리오를 company에 로드(기존 데이터 리셋 후 재적재). 반환 {name, loaded}."""
    if name not in SCENARIOS:
        raise ValueError(f"알 수 없는 시나리오: {name} (가능: {list(SCENARIOS)})")
    sc = SCENARIOS[name]
    records = generate(sc["config"])

    # 이상치 시나리오: 해당 월·연료 전표에 '정상 사유' 문구 주입(재검증 대상)
    just = sc.get("justify")
    if just:
        for r in records:
            if r["month"] == just["month"] and r["label"]["fuel"] == just["fuel"]:
                r["item_description"] = just["text"]

    _reset_company(session, company_id)
    vouchers = [_to_voucher(r, company_id) for r in records]
    session.add_all(vouchers)
    session.commit()
    return {"name": name, "loaded": len(vouchers)}
