"""판단 근거(evidence)와 계산 실패 사유(calc_failure_reason) 필드 분리 골든 케이스.

핵심 검증축:
  - Classification.evidence 에는 AI/룰의 순수 분류 판단 근거만 들어간다 — 계산 실패
    사유(LPG 단위 미확정, 데이터 갭 등)를 " | "로 이어붙이지 않는다.
  - 계산 실패 사유는 별도 컬럼 calc_failure_reason 에 저장된다.
  - 계산이 정상적으로 성공하면 calc_failure_reason 은 null 이다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.agent.rules import match_rule
from api.agent.tools import _build_classification
from db.init_db import seed_emission_factors, seed_unit_prices
from db.models import Base, Company, Voucher
from api.queries import get_emission_factors, get_unit_prices
from db.calc_engine import index_emission_factors, index_unit_prices

YEAR = 2025


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()
        yield session, company.id


def _indexes(session):
    return (
        index_unit_prices(get_unit_prices(session)),
        index_emission_factors(get_emission_factors(session)),
    )


def _decided_from_rule(item_text: str) -> dict:
    rule = match_rule(item_text)
    return {
        "scope": rule["scope"],
        "category": rule["category"],
        "fuel_type": rule["fuel_type"],
        "evidence": f"[{rule['rule_id']}] {rule['reasoning']}",
        "method": "rule",
        "mixed_item": rule["mixed_item"],
        "confidence": 0.5,
        "rule_id": rule["rule_id"],
    }


def test_lpg_needs_review_keeps_evidence_pure_and_sets_calc_failure_reason(db):
    """LPG는 단위(kg/L/Nm3) 문제로 자동계산 제외 대상 — evidence에는 원래 판단
    근거만 남고, 계산 실패 사유는 calc_failure_reason에 별도로 들어간다."""
    session, cid = db
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=1,
        supplier_name="테스트", item_description="LPG 사용료", supply_amount_krw=100000,
    )
    session.add(v)
    session.commit()

    price_index, factor_index = _indexes(session)
    decided = _decided_from_rule("LPG 사용료")
    classification = _build_classification(v, decided, price_index, factor_index)

    assert classification.evidence == decided["evidence"]
    assert " | " not in classification.evidence
    assert classification.calc_failure_reason is not None
    assert "LPG" in classification.calc_failure_reason
    assert classification.status == "review_required"


def test_successful_calc_leaves_calc_failure_reason_null(db):
    """계산이 정상 성공하면(도시가스, 수량 명시) calc_failure_reason은 비어 있다."""
    session, cid = db
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=1,
        supplier_name="테스트", item_description="도시가스 요금", supply_amount_krw=1_000_000,
        raw_json={"quantity": 500},
    )
    session.add(v)
    session.commit()

    price_index, factor_index = _indexes(session)
    decided = {
        "scope": 1, "category": "고정연소", "fuel_type": "도시가스",
        "evidence": "품목명에 '도시가스' 명시",
        "method": "rule", "mixed_item": False, "confidence": 0.9,
    }
    classification = _build_classification(v, decided, price_index, factor_index)

    assert classification.calc_failure_reason is None
    assert classification.evidence == "품목명에 '도시가스' 명시"
    assert classification.emission_co2e is not None and classification.emission_co2e > 0
