"""recompute_emission_goal_baseline_trailing — 데이터 전용 revision. 스키마 변경 없음.

배출량 감축 목표(emission_reduction)의 기준값을 "설정월부터 **미래** 12개월"이 아니라
"설정월까지의 **최근** 12개월"로 재계산한다(2026-08-25).

왜 필요한가. 0028이 기준 구간을 달력년도에서 "설정월부터 롤링 12개월"로 바꿨는데 그
방향이 미래였다. 목표를 세우는 순간 미래 구간에 존재할 수 있는 데이터는 이번 달 하나뿐
이라, 기준값이 사실상 "이번 달 한 달치"로 저장됐다. 실측(대경부품, goal id 24):
2026-08에 세운 목표의 baseline_value가 1.5tCO2e로 저장됐는데 이는 2026-08 한 달
(1.506)이고 실제 최근 1년 총량은 17.37tCO2e였다 — 화면에 "목표 배출량 1.35tCO2e"로
연간 목표인 것처럼 표시되지만 11배 이상 작은 값이다.

기준값·목표값은 저장 스냅숏이라(진행률과 달리 조회 때 다시 계산되지 않는다) 코드만
고쳐도 기존 행은 틀린 채로 남는다. 그래서 여기서 한 번 다시 계산한다.

범위: goal_type='emission_reduction' AND status IN ('active','achieved') 만.
cancelled/superseded는 지나간 기록이므로 손대지 않는다. 사용자가 실제로 입력한 값
(target_reduction_pct)은 그대로 두고, 그로부터 파생되는 두 값만 다시 만든다.

집계 규칙은 db/pcaf_engine/company_goals.py::_emission_in_months와 일치시킨다:
  - Classification.fuel_type을 연료 대분류로 매핑해 Scope1(도시가스·경유·휘발유·LPG)
    / Scope2(전기)에 드는 건만 대상(pcaf_quality.py::_FUEL_TYPE_TO_BUCKET +
    FUEL_BUCKET_SCOPE를 이 시점 스냅숏으로 인라인 — 마이그레이션은 과거 시점에
    고정돼야 하므로 엔진을 import하지 않는다)
  - status='rejected' 또는 emission_co2e IS NULL 인 건은 0으로 더한다(단, 그 Scope에
    전표가 "있다"는 사실은 인정 — GROUP BY가 그 역할을 한다)
  - Scope별로 먼저 round(2)한 뒤 합산(화면의 Scope1+Scope2와 총량이 어긋나지 않게)

멱등하다 — vouchers/classifications에서 매번 다시 계산하므로 재실행해도 같은 값이다.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-25 11:42:08.117433

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0033'
down_revision: Union[str, Sequence[str], None] = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# db/pcaf_engine/pcaf_quality.py::_FUEL_TYPE_TO_BUCKET + FUEL_BUCKET_SCOPE의
# 2026-08-25 시점 스냅숏. 전기만 Scope 2, 나머지 연료는 Scope 1.
_SCOPE_2_FUEL = '전기'
_SCOPE_1_FUELS = ('도시가스', '경유', '휘발유', 'LPG')

# 기준 구간의 (year*12+month) 범위만 바꿔 끼우면 upgrade/downgrade가 같은 쿼리를 쓴다.
# :offset_from ~ :offset_to 는 목표 시작월 인덱스에 더할 값이다.
#   최근 12개월(upgrade)  : -11 ~ 0   (설정월이 마지막 칸)
#   미래 12개월(downgrade): 0 ~ +11   (설정월이 첫 칸 — 0028의 원래 동작)
_RECOMPUTE_SQL = """
WITH scope_totals AS (
    SELECT g.id AS goal_id,
           CASE WHEN c.fuel_type = :scope_2_fuel THEN 2 ELSE 1 END AS scope_group,
           SUM(CASE WHEN c.status = 'rejected' OR c.emission_co2e IS NULL
                    THEN 0 ELSE c.emission_co2e END) AS kg
    FROM company_goals g
    JOIN vouchers v ON v.company_id = g.company_id
    JOIN classifications c ON c.voucher_id = v.id
    WHERE g.goal_type = 'emission_reduction'
      AND g.status IN ('active', 'achieved')
      AND c.fuel_type IN :all_fuels
      AND (v.year * 12 + v.month) BETWEEN
              (g.baseline_reporting_year * 12 + g.baseline_start_month + :offset_from)
          AND (g.baseline_reporting_year * 12 + g.baseline_start_month + :offset_to)
    GROUP BY g.id, 2
),
baselines AS (
    SELECT goal_id, SUM(ROUND(CAST(kg / 1000.0 AS numeric), 2)) AS baseline
    FROM scope_totals
    GROUP BY goal_id
)
UPDATE company_goals g
SET baseline_value = CAST(ROUND(b.baseline, 2) AS double precision),
    target_value = CAST(
        ROUND(b.baseline * (1 - CAST(COALESCE(g.target_reduction_pct, 0) AS numeric) / 100), 2)
        AS double precision
    )
FROM baselines b
WHERE g.id = b.goal_id
  AND b.baseline > 0
"""


def _recompute(offset_from: int, offset_to: int) -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(_RECOMPUTE_SQL).bindparams(
            sa.bindparam("all_fuels", expanding=True),
        ),
        {
            "scope_2_fuel": _SCOPE_2_FUEL,
            "all_fuels": list(_SCOPE_1_FUELS) + [_SCOPE_2_FUEL],
            "offset_from": offset_from,
            "offset_to": offset_to,
        },
    )


def upgrade() -> None:
    """기준값을 "설정월까지의 최근 12개월"로 재계산."""
    _recompute(offset_from=-11, offset_to=0)


def downgrade() -> None:
    """0028의 원래 동작("설정월부터 미래 12개월")으로 되돌린다 — 같은 쿼리에 구간만
    앞으로 밀어 넣는다. 되돌리면 다시 "이번 달 한 달치" 기준값이 된다는 점은 의도된
    것이다(그게 되돌리려는 그 동작이므로)."""
    _recompute(offset_from=0, offset_to=11)
