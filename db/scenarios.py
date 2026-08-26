"""데모 시나리오 — 여러 상황의 전표 세트를 company에 로드해 에이전트 행동을 관찰.

synth_generator(파라미터형)로 상황별 전표를 찍고, 대상 company의 기존
전표·분류·트레이스를 리셋한 뒤 재적재한다. 프론트 드롭다운/POST로 전환.

시나리오별로 에이전트가 다르게 판단:
- demo        : 3~5월 가스 결손 + 7월 경유 급증 → 킬러씬 A 전체(결손 감지 + 자가검증)
- gas_gap     : 3~5월 도시가스 결손 → 결손 감지·사장 알림
- normal      : 결손·이상치 없음 → 알림 없이 분류·계산만
- diesel_spike: 7월 경유 급증(+'증차' 문구) → 이상치 의심·재검증·정상 판정
- multi_gap   : 다중 결손(3~5·10~11월 가스) → 다중 알림

모든 시나리오에 K택소노미 설비 신호 전표를 공통으로 얹는다(2026-08-25).
synth_generator.FUEL_EXPRESSIONS는 경유·도시가스·전기 3연료만 다뤄 태양광·
전동지게차 같은 설비 어휘가 애초에 없었다 — 그 결과 실제 개발 DB의 9개 회사
중 8곳이 k_taxonomy_facility_type 매칭 0건이었다(실측 확인). 이 공백은 감축
실천 ToDo(db/pcaf_engine/reduction_todo.py)뿐 아니라 은행 설비금융 리드
목록(k_taxonomy_leads)·사장님 설비금융 안내 카드·K-택소노미 우대금리 상품
자격 판정(RateProduct.requires_k_taxonomy_leads)까지 전부 항상 빈 상태로
만들고 있었다. 결손·이상치는 시나리오마다 다른 게 설계 의도지만, 설비 신호는
"부가 정보"라 어느 시나리오에 섞여 있어도 그 시나리오 고유의 현상(결손·
이상치)을 가리지 않는다 — 그래서 모든 시나리오 공통으로 둔다.

2026-08-26: 설비 신호를 company_id별로 다르게 만든다. 처음엔 모든 기업에
같은 전표 2건(R031 압축기+R058 유지보수비)을 그대로 적재했는데, 그 결과
성서테크·칠곡소재·포항이엔지·대구정공 4곳이 감축 ToDo 화면에서 항목까지
완전히 동일하게 떴다(사용자 지적 — "지금 모든 기업이 [...] 내용은 같고
순서만 다른거야?"). R058(유지보수비 → 노후설비 의심)은 특정 설비 종류가
아니라 "일반적 유지보수 상태" 신호라 공통으로 유지하되(사용자 확정),
R031 대신 기업마다 다른 R05x 룰(전동지게차·히트펌프·집진기 등)을 하나씩
배정해 todos 내용 자체가 갈리게 한다. 완전 무공통을 원하는 정도는 아니고
"좀 겹쳐도 됨"이 최종 확인 — R058 공통 유지는 그대로 두고 나머지만 갈랐다.
"""
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db.models import Classification, TraceLog, Voucher
from db.synth_generator import GenConfig, generate

YEAR = 2025  # 회계 엑셀(월별단가·전표) 연도와 일치

# 연료 → 거래처(공급자) 이름 합성용
_SUPPLIER = {"경유": "구미석유", "도시가스": "대성에너지", "전기": "한국전력공사"}

# K택소노미 설비 신호 전표 — 모든 시나리오에 공통으로 얹는다(위 모듈 docstring
# 참고). R058("유지보수비")은 company_id와 무관하게 전 기업 공통 — auto_action이
# "사람검토"라 finance_lead_type은 안 채워지지만, 감축 ToDo의 노후설비 의심
# 신호(evidence LIKE '%(참고: R058)%')가 이 건 하나로 채워진다.
_AGING_EQUIPMENT_VOUCHER = {
    "source": "hometax", "month": 12, "supplier_name": "구미설비정비",
    "item_description": "공조설비 유지보수비", "supply_amount_krw": 1_200_000,
}

# company_id별로 다른 R05x 룰을 하나씩 배정 — 4개 기업이 감축 ToDo 화면에서
# 항목까지 완전히 똑같이 뜨던 문제(위 docstring 참고) 대응. item_description은
# db/excel_loader.py::load_classification_rules()가 반환하는 각 룰의
# include_keywords에 실제로 걸리는 문구를 그대로 쓴다(exclude_keywords와
# 안 겹치는지도 확인 완료, 2026-08-26 실측):
#   6(성서테크): R031 "고효율 공조설비"(finance_lead_type 있음 — 은행
#       리드·설비금융 카드·우대금리 자격까지 전부 채우는 유일한 조합, 기존
#       검증 기업이라 그대로 유지)
#   7(칠곡소재): R053 "전동지게차 리스료"
#   8(포항이엔지): R054 "히트펌프 설치"
#   9(대구정공): R055 "집진기 설치"
# 다른 기업(4·5·10 등)은 아직 이 매핑에 없다 — 실제 업로드 테스트 데이터를
# 덮어쓰지 않으려고 의도적으로 시나리오 재적재 대상에서 제외했다(§12.5
# 참고). 매핑에 없는 company_id는 기존처럼 R031 문구로 폴백한다.
_FACILITY_SIGNAL_BY_COMPANY: dict[int, dict] = {
    6: {"source": "hometax", "supplier_name": "대성설비",
        "item_description": "고효율 공조설비", "supply_amount_krw": 5_000_000},
    7: {"source": "hometax", "supplier_name": "구미리스",
        "item_description": "전동지게차 리스료", "supply_amount_krw": 3_500_000},
    8: {"source": "hometax", "supplier_name": "대성설비",
        "item_description": "히트펌프 설치", "supply_amount_krw": 6_000_000},
    9: {"source": "hometax", "supplier_name": "구미환경설비",
        "item_description": "집진기 설치", "supply_amount_krw": 4_500_000},
}
_DEFAULT_FACILITY_SIGNAL = {
    "source": "hometax", "supplier_name": "대성설비",
    "item_description": "고효율 공조설비", "supply_amount_krw": 5_000_000,
}


SCENARIOS: dict[str, dict] = {
    # 첫 항목 = 프론트 기본 선택. 킬러씬 A의 두 축(결손 감지 + 이상치 자가검증)을
    # 한 실행에서 모두 보여주는 시연 기본 시나리오.
    "demo": {
        "label": "시연 · 3~5월 가스 결손 + 7월 경유 이상치",
        "config": GenConfig(count=0, year=YEAR, gap_months=[3, 4, 5],
                            anomaly={"month": 7, "fuel": "경유", "multiplier": 3.2}),
        "justify": {"month": 7, "fuel": "경유", "text": "지게차 경유 (2대 증차분)"},
    },
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


def _equipment_signal_vouchers(company_id: int, year: int) -> list[Voucher]:
    """company_id별 설비 신호 전표 2건(R05x 계열 1건 + R058 1건)을 실제
    Voucher로 변환. synth_generator 산출물과 달리 label/fuel 구조가 없다 —
    설비투자 전표는 원래 Scope·연료가 없다(R03x/R05x/R058 전부
    fuel_type="설비투자"|"없음", CLAUDE.md 원칙1과 같은 결로 분류 엔진이
    결정할 몫이지 여기서 미리 정하지 않는다). 둘 다 12월(마지막 달)에
    배치해 monthly_by_fuel()의 "가장 최근 달" 판정에 실수요 전표들과
    자연스럽게 섞이게 한다."""
    facility = _FACILITY_SIGNAL_BY_COMPANY.get(company_id, _DEFAULT_FACILITY_SIGNAL)
    raw = [facility, _AGING_EQUIPMENT_VOUCHER]
    return [
        Voucher(
            company_id=company_id,
            source=v["source"],
            issue_date=datetime(year, 12, 20, tzinfo=timezone.utc),
            year=year,
            month=12,
            supplier_name=v["supplier_name"],
            item_description=v["item_description"],
            supply_amount_krw=v["supply_amount_krw"],
        )
        for v in raw
    ]


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
    vouchers += _equipment_signal_vouchers(company_id, sc["config"].year)
    session.add_all(vouchers)
    session.commit()
    return {"name": name, "loaded": len(vouchers)}
