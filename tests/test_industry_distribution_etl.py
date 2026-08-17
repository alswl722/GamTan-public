"""업종 분포 실데이터 파이프라인 골든 케이스.

핵심 검증축:
  - data/industry_distributions.xlsx(scripts/fetch_industry_distributions.py 산출물)가
    excel_loader.load_industry_distributions()로 정상 파싱되고, 우리 시연 기업이 쓰는
    업종코드(C251/C259)가 Scope1·2 각각 존재한다.
  - api/queries.py::_worker_band_for()가 종사자수를 실데이터가 쓰는 밴드 문자열로
    정확히 매핑한다.
  - get_distribution()은 employee_count를 주면 그 규모 밴드를 우선 쓰고, 밴드가
    없거나 표본이 부족하면 전체 규모 통합(worker_band=NULL)으로 폴백한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.queries import _worker_band_for, get_distribution
from db.excel_loader import load_industry_distributions
from db.models import Base, IndustryDistribution


def test_load_industry_distributions_has_target_industries():
    rows = load_industry_distributions()
    assert rows, "data/industry_distributions.xlsx가 비어있음 — ETL 재실행 필요"

    by_code_scope = {(r["industry_code"], r["scope"]) for r in rows}
    for code in ("C251", "C259"):
        for scope in (1, 2):
            assert (code, scope) in by_code_scope, f"{code} scope{scope} 실데이터 없음"

    # 전체 규모 통합(worker_band=None) 행이 밴드별 행과 함께 반드시 존재해야
    # get_distribution()의 표본 부족 폴백이 항상 걸릴 곳이 있다.
    pooled = [r for r in rows if r["industry_code"] == "C259" and r["scope"] == 1 and r["worker_band"] is None]
    assert len(pooled) == 1
    assert pooled[0]["sample_size"] and pooled[0]["sample_size"] > 0


@pytest.mark.parametrize(
    "employee_count,expected_band",
    [
        (1, "5인 미만"),
        (4, "5인 미만"),
        (5, "5인 ~ 9인"),
        (12, "10인 ~ 19인"),  # ○○정밀(12명) 기준 케이스
        (19, "10인 ~ 19인"),
        (20, "20인 ~ 49인"),
        (1500, "1000인 이상"),
        (None, None),
    ],
)
def test_worker_band_for(employee_count, expected_band):
    assert _worker_band_for(employee_count) == expected_band


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _add(session, **kwargs):
    session.add(IndustryDistribution(**kwargs))
    session.commit()


def test_get_distribution_uses_matched_band_when_sample_sufficient(db):
    _add(
        db, industry_code="C900", scope=1, worker_band="10인 ~ 19인",
        emission_min_co2e=1.0, emission_median_co2e=5.0, emission_max_co2e=10.0,
        sample_size=10, year=2019, source="test",
    )
    _add(
        db, industry_code="C900", scope=1, worker_band=None,
        emission_min_co2e=0.5, emission_median_co2e=50.0, emission_max_co2e=500.0,
        sample_size=999, year=2019, source="test",
    )

    result = get_distribution(db, "C900", 1, employee_count=12)
    assert result["median"] == 5.0  # 밴드 매칭값을 썼다(전체 통합값 50.0이 아님)
    assert result["scale_matched"] is True


def test_get_distribution_falls_back_when_band_sample_too_small(db):
    _add(
        db, industry_code="C901", scope=1, worker_band="10인 ~ 19인",
        emission_min_co2e=1.0, emission_median_co2e=5.0, emission_max_co2e=10.0,
        sample_size=1,  # _MIN_BAND_SAMPLE_SIZE(3) 미만 — 폴백 대상
        year=2019, source="test",
    )
    _add(
        db, industry_code="C901", scope=1, worker_band=None,
        emission_min_co2e=0.5, emission_median_co2e=50.0, emission_max_co2e=500.0,
        sample_size=999, year=2019, source="test",
    )

    result = get_distribution(db, "C901", 1, employee_count=12)
    assert result["median"] == 50.0
    assert result["scale_matched"] is False


def test_get_distribution_falls_back_when_band_missing_entirely(db):
    _add(
        db, industry_code="C902", scope=1, worker_band=None,
        emission_min_co2e=0.5, emission_median_co2e=50.0, emission_max_co2e=500.0,
        sample_size=999, year=2019, source="test",
    )

    result = get_distribution(db, "C902", 1, employee_count=12)
    assert result["median"] == 50.0
    assert result["scale_matched"] is False


def test_get_distribution_without_employee_count_uses_pooled_directly(db):
    """employee_count 생략 시(기존 호출부 호환) 처음부터 전체 규모 통합만 본다."""
    _add(
        db, industry_code="C903", scope=1, worker_band="10인 ~ 19인",
        emission_min_co2e=1.0, emission_median_co2e=5.0, emission_max_co2e=10.0,
        sample_size=10, year=2019, source="test",
    )
    _add(
        db, industry_code="C903", scope=1, worker_band=None,
        emission_min_co2e=0.5, emission_median_co2e=50.0, emission_max_co2e=500.0,
        sample_size=999, year=2019, source="test",
    )

    result = get_distribution(db, "C903", 1)
    assert result["median"] == 50.0
