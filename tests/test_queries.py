"""api/queries.py::get_vouchers — 다년 데이터 정렬 회귀 테스트.

v0.1은 "12개월치 전표"(단일 연도)만 다뤘기 때문에 get_vouchers가 `(month,
issue_date)`로만 정렬해도 결과가 연대순이었다. 소상공인 탄소중립포인트 트랙은
24개월(과거 2년) 사용량을 월 시계열로 다루므로(CLAUDE.md §7 예외) 이 전제가
깨진다 — 이 파일은 그 회귀를 잠근다.

2026-08-22 공유 DB 실측(기업 id=5, 62건): 2025-01 → 2026-01 → 2021-01 → 2025-02
순으로 반환됐다. issue_date가 null인 전표 7건이 NULLS LAST로 밀려 2021년이
2026년 뒤에 온 것이다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.queries import get_classifications, get_vouchers
from db.models import Base, Company, Voucher


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def company(db):
    c = Company(name="동성로카페", industry_code="I561", industry_name="음식점업")
    db.add(c)
    db.commit()
    return c


def _add(db, company_id, year, month, *, issue_date=None, source="kepco", amount=100_000):
    db.add(Voucher(
        company_id=company_id, source=source, year=year, month=month,
        issue_date=issue_date, item_description="전기요금", supply_amount_krw=amount,
    ))


def test_orders_chronologically_across_years(db, company):
    """연도가 섞여 들어와도 (year, month) 연대순으로 나와야 한다."""
    for year, month in [(2026, 1), (2024, 3), (2025, 12), (2024, 1), (2026, 8), (2025, 1)]:
        _add(db, company.id, year, month)
    db.commit()

    got = [(v["year"], v["month"]) for v in get_vouchers(db, company.id)]
    assert got == [(2024, 1), (2024, 3), (2025, 1), (2025, 12), (2026, 1), (2026, 8)]


def test_issue_date_null_does_not_break_year_order(db, company):
    """issue_date가 null인 전표(마이데이터 mock 경로 등)가 섞여도 연도 순서가
    유지돼야 한다.

    ⚠️ 이 테스트는 SQLite에서는 옛 정렬로도 통과한다 — SQLite는 ORDER BY ASC에서
    NULL을 먼저 놓고(NULLS FIRST) Postgres는 나중에 놓는다(NULLS LAST). 실제 사고는
    Postgres(공유 DB)에서만 재현됐다. 그래서 이 파일의 회귀 방어는
    test_orders_chronologically_across_years(널과 무관하게 실패)가 담당하고, 이
    테스트는 "널이 섞여도 연도 우선"이라는 의도를 문서화하는 역할이다.
    """
    from datetime import datetime, timezone

    _add(db, company.id, 2026, 1, issue_date=datetime(2026, 1, 31, tzinfo=timezone.utc))
    _add(db, company.id, 2024, 1, issue_date=None)   # 과거 연도인데 issue_date 없음
    _add(db, company.id, 2025, 1, issue_date=datetime(2025, 1, 31, tzinfo=timezone.utc))
    db.commit()

    got = [(v["year"], v["month"]) for v in get_vouchers(db, company.id)]
    assert got == [(2024, 1), (2025, 1), (2026, 1)], (
        "issue_date가 null인 과거 연도 전표가 뒤로 밀리면 안 된다"
    )


def test_24_month_window_is_retrievable(db, company):
    """기간 필터가 없어 24개월 이상도 한 번에 조회된다 — 감축률 계산의 전제
    (develop-plan.md §2.2: 과거 2년치 평균 대비 금년 사용량)."""
    for i in range(24):
        year, month = 2024 + (i // 12), (i % 12) + 1
        _add(db, company.id, year, month)
    db.commit()

    got = get_vouchers(db, company.id)
    assert len(got) == 24
    assert (got[0]["year"], got[0]["month"]) == (2024, 1)
    assert (got[-1]["year"], got[-1]["month"]) == (2025, 12)


def test_source_filter_keeps_chronological_order(db, company):
    """source 필터를 걸어도 정렬 규칙은 같아야 한다."""
    _add(db, company.id, 2026, 1, source="kepco")
    _add(db, company.id, 2024, 5, source="kepco")
    _add(db, company.id, 2025, 6, source="hometax")
    db.commit()

    got = [(v["year"], v["month"]) for v in get_vouchers(db, company.id, source="kepco")]
    assert got == [(2024, 5), (2026, 1)]


def test_get_classifications_orders_chronologically_across_years(db, company):
    """get_classifications도 같은 정렬 규칙을 따라야 한다(같은 근본 원인).

    반환 dict엔 year·month가 없으므로(함수 docstring 참고) 정렬은 리스트 순서로만
    관측된다 — activity_amount를 위치 표식으로 써서 확인한다.
    """
    from db.models import Classification

    plan = [(2026, 1, 111.0), (2024, 3, 222.0), (2025, 12, 333.0), (2024, 1, 444.0)]
    for year, month, kwh in plan:
        v = Voucher(
            company_id=company.id, source="kepco", year=year, month=month,
            item_description="전기요금", supply_amount_krw=100_000,
        )
        db.add(v)
        db.flush()
        db.add(Classification(
            voucher_id=v.id, scope=2, category="간접배출", fuel_type="전기",
            activity_amount=kwh, activity_unit="kWh", status="auto",
        ))
    db.commit()

    got = [c["activity_amount"] for c in get_classifications(db, company.id)]
    assert got == [444.0, 222.0, 333.0, 111.0], "2024-01 → 2024-03 → 2025-12 → 2026-01 순"
