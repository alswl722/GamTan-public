"""관리자 대시보드 백엔드 테스트 — 포트폴리오 집계 / HITL 큐 / 확정 전이.

네트워크 없이 sqlite 로 시드 → 분류 몇 건 직접 심고 집계·큐·확정을 검증한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.queries import get_hitl_queue
from db.init_db import (
    seed_emission_factors,
    seed_industry_distributions,
    seed_unit_prices,
)
from db.models import Base, Classification, Company, Voucher
from db.pcaf import company_pcaf_summary, portfolio_summary


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add(session, cid, month, item, *, scope, emission, status, conf=0.9):
    v = Voucher(company_id=cid, source="hometax", year=2025, month=month,
                supplier_name="테스트", item_description=item,
                supply_amount_krw=100000, raw_json={"quantity": 100})
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=emission, confidence=conf,
        evidence="테스트", method="rule", status=status,
    ))
    session.commit()
    return v.id


def test_portfolio_matches_per_company_summary(db):
    """포트폴리오 집계는 기업별 company_pcaf_summary(after 우선)와 일치해야 한다."""
    session, cid = db
    _add(session, cid, 1, "도시가스", scope=1, emission=1000.0, status="auto")
    _add(session, cid, 2, "전기요금", scope=2, emission=2000.0, status="auto")

    per = company_pcaf_summary(session, cid)["after"]
    assert per is not None                      # 분류가 있으니 실측 경로
    summ = portfolio_summary(session)

    assert summ["company_count"] == 1
    co = summ["companies"][0]
    assert co["measured"] is True
    assert co["scope1"] == pytest.approx(per["scope1"], abs=0.01)
    assert co["scope2"] == pytest.approx(per["scope2"], abs=0.01)
    assert co["grade"] == per["grade"]          # 집계가 등급을 왜곡하지 않음
    # 등급 분포 합 == 기업 수, 총합 == Scope 합
    assert sum(summ["grade_distribution"].values()) == summ["company_count"]
    assert summ["total"] == pytest.approx(
        summ["scope1_total"] + summ["scope2_total"], abs=0.01
    )


def test_hitl_queue_lists_only_review_required(db):
    """HITL 큐는 review_required 건만, auto/confirmed는 제외."""
    session, cid = db
    _add(session, cid, 3, "유류대금", scope=1, emission=0.0, status="review_required", conf=0.5)
    _add(session, cid, 4, "도시가스", scope=1, emission=500.0, status="auto")

    queue = get_hitl_queue(session)
    assert len(queue) == 1
    assert queue[0]["raw"] == "유류대금"
    assert queue[0]["company_name"] == "○○정밀"
    assert queue[0]["confidence"] == pytest.approx(0.5)


def test_confirm_transitions_and_leaves_queue(db):
    """확정 시 status review_required→confirmed, 큐에서 빠진다."""
    session, cid = db
    vid = _add(session, cid, 5, "유류대금", scope=1, emission=0.0,
               status="review_required", conf=0.5)

    assert len(get_hitl_queue(session)) == 1
    obj = session.query(Classification).filter_by(voucher_id=vid).one()
    obj.status = "confirmed"
    session.commit()

    assert get_hitl_queue(session) == []
