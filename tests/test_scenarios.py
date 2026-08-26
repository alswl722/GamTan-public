"""데모 시나리오 로더(db/scenarios.py) — K택소노미 설비 신호 공통 주입 검증.

배경: 실제 개발 DB의 9개 회사 중 8곳이 k_taxonomy_facility_type 매칭 0건이었다
(2026-08-25 실측 확인). 원인은 synth_generator.FUEL_EXPRESSIONS가 경유·도시가스·
전기 3연료만 다뤄 태양광·전동지게차 같은 설비 어휘가 애초에 없었던 것 — 이 공백은
감축 실천 ToDo뿐 아니라 은행 설비금융 리드·사장님 설비금융 카드·K-택소노미 우대금리
자격 판정까지 전부 항상 빈 상태로 만들고 있었다. 모든 시나리오에 설비 신호 전표
2건(R05x 계열 1건 + R058 유지보수비)을 공통으로 얹어 해결한다.

2026-08-26: R05x 계열 전표를 company_id별로 다르게 배정하도록 바꿨다 — 처음엔
전 기업이 "고효율 압축기"(R031) 하나로 고정돼 있었는데, 그 결과 4개 기업의
감축 ToDo 화면이 항목까지 완전히 똑같이 떴다(사용자 지적). company_id가
_FACILITY_SIGNAL_BY_COMPANY에 없으면 기존 문구("고효율 공조설비", R031
계열)로 폴백한다 — 이 테스트 fixture의 company는 자동 생성 id를 쓰므로
대부분 폴백 경로를 탄다.

핵심 검증축:
  - load_scenario()가 만드는 전표 수에 설비 신호 전표 2건이 항상 포함된다
    (기존 synth_generator 산출량 + 2).
  - 설비 신호 전표는 시나리오 종류(demo/gas_gap/normal/...)와 무관하게 공통으로
    들어간다 — 결손·이상치 시나리오 고유의 현상을 방해하지 않는지 확인.
  - classify_vouchers()를 거치면 실제로 k_taxonomy_facility_type이 채워진다
    (R031, finance_lead_type 있음 → 은행 리드·감축 ToDo 둘 다 이 신호를 씀).
  - R058(유지보수비) 매칭 건은 evidence에 "(참고: R058)" 마커가 남는다 — 감축
    ToDo의 노후설비 신호(aging_equipment_signal)가 바로 이 마커로 식별한다.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.agent.tools import classify_vouchers
from db.init_db import seed_emission_factors, seed_industry_distributions, seed_unit_prices
from db.models import Base, Classification, Company, Voucher
from db.pcaf_engine.reduction_actions import aging_equipment_signal, facility_signals
from db.scenarios import _FACILITY_SIGNAL_BY_COMPANY, SCENARIOS, load_scenario


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """룰 매칭 결과만 검증하면 되므로 LLM 호출을 막는다(네트워크 의존 제거)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        company = Company(
            name="테스트기업", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12,
        )
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.mark.parametrize("scenario_name", list(SCENARIOS))
def test_every_scenario_includes_equipment_signal_vouchers(db, scenario_name):
    """어느 시나리오를 로드하든 설비 신호 전표 2건(company_id별 R05x 계열 +
    공통 R058)이 포함된다. 이 fixture의 company_id는 매핑에 없으므로
    폴백 문구("고효율 공조설비")로 들어간다."""
    session, cid = db
    result = load_scenario(session, cid, scenario_name)

    items = [
        v.item_description
        for v in session.query(Voucher).filter_by(company_id=cid).all()
    ]
    assert "고효율 공조설비" in items  # 매핑 없는 company_id → 폴백
    assert "공조설비 유지보수비" in items
    # loaded 카운트도 이 2건을 포함한 총합이어야 한다(반환값이 실제 적재 건수와
    # 어긋나면 관리자 화면의 "N건 로드됨" 안내가 거짓말을 하게 된다).
    assert result["loaded"] == len(items)


@pytest.mark.parametrize("company_id,expected_item", list(_FACILITY_SIGNAL_BY_COMPANY.items()))
def test_mapped_company_gets_its_own_facility_signal(db, company_id, expected_item):
    """_FACILITY_SIGNAL_BY_COMPANY에 매핑된 company_id는 폴백이 아니라 자기
    고유의 R05x 문구를 받는다 — 4개 기업의 감축 ToDo 항목이 서로 달라지는
    근거가 이 매핑이다."""
    session, _ = db
    load_scenario(session, company_id, "normal")

    items = [
        v.item_description
        for v in session.query(Voucher).filter_by(company_id=company_id).all()
    ]
    assert expected_item["item_description"] in items
    assert "공조설비 유지보수비" in items  # R058은 여전히 공통


def test_demo_scenario_still_has_its_own_signature(db):
    """공통 설비 신호를 얹어도 demo 시나리오 고유 현상(3~5월 가스 결손 + 7월
    경유 이상치 '증차' 문구)은 그대로 유지된다 — 부가 정보가 기존 시나리오를
    가리지 않는다."""
    session, cid = db
    load_scenario(session, cid, "demo")

    vouchers = session.query(Voucher).filter_by(company_id=cid).all()
    gas_months = {v.month for v in vouchers if "가스" in (v.item_description or "")}
    assert not ({3, 4, 5} & gas_months)  # 3~5월 가스 결손 유지

    july_diesel = [v for v in vouchers if v.month == 7 and "증차" in (v.item_description or "")]
    assert len(july_diesel) == 1  # 7월 이상치 정상 사유 주입 유지


def test_equipment_signal_produces_k_taxonomy_facility_type_after_classification(db):
    """설비 신호 전표가 실제 분류 파이프라인을 거치면 k_taxonomy_facility_type이
    채워진다 — 은행 리드·감축 ToDo 둘 다 이 컬럼을 그대로 재조회하므로, 이 값이
    채워지는 것 자체가 그 두 기능이 데이터를 받는다는 뜻이다."""
    session, cid = db
    load_scenario(session, cid, "normal")
    classify_vouchers(session, cid)

    signals = facility_signals(session, cid)
    assert "공조설비 등" in signals["facility_types"]  # R031 매칭 결과


def test_equipment_signal_produces_aging_equipment_marker_after_classification(db):
    """유지보수비 전표가 분류되면 evidence에 R058 마커가 남고, 감축 ToDo의
    노후설비 신호가 True가 된다."""
    session, cid = db
    load_scenario(session, cid, "normal")
    classify_vouchers(session, cid)

    assert aging_equipment_signal(session, cid) is True
