"""cnp_draft_downloaded_at

탄소 캘린더에 뜨는 탄소중립포인트 신청서 이벤트의 기준 날짜를 **초안 생성일에서
초안 내려받은 날로** 바꾼다(2026-08-26 사용자 결정). 그래서 "내려받은 시각" 컬럼이 필요하다.

종전엔 `created_at`(초안 레코드 생성일)을 캘린더에 꽂았다. 그런데 초안 레코드는 사장님이
위저드 2단계에 들어서기만 하면 생긴다 — 신청서를 실제로 손에 넣지 않아도, 나중에 그만둬도
캘린더에 "신청서" 이벤트가 남는다. 사장님이 한 일이 아닌 걸 사장님 캘린더에 적는 셈이다.

`status='submitted'`를 쓰는 것도 답이 아니다. 그 값은 사장님이 포털에서 직접 제출한 뒤
화면에서 수동으로 눌러줘야 채워지는 필드이고(감탄은 접수 인터페이스가 없다 —
data-plan §3.2), 실제로 눌러줄 이유가 사장님에겐 거의 없다. 감탄이 **직접 관측할 수 있는
행동**은 "초안 PDF를 내려받았다"뿐이고, 그게 캘린더에 적을 수 있는 유일한 사실이다.

**첫 다운로드만 기록한다**(라우터가 null일 때만 채운다). 재다운로드로 날짜를 갱신하면
캘린더의 과거 이벤트가 사라져 이동한다 — 이미 일어난 일이 사라지면 안 된다.

⚠️ **리비전 번호 주의(2026-08-26).** 이 파일은 `0033`에서 갈라진다. 공유 DB는 이미
`0034`(reduction_todo_rerank_cache)로 스탬프돼 있는데 그 리비전은 아직 dev에 병합되지
않은 브랜치(`feat/reduction-todo-catalog`)에만 있다. `0034`에 의존하게 만들면 그 브랜치가
리베이스·폐기될 때 이 파일이 실행 불가가 되므로, 병합되지 않은 것에 기대지 않고 `0033`에서
갈랐다. 두 브랜치가 만나는 시점에 head가 둘이 되므로 **머지 리비전이 필요하다**
(`alembic merge -m "..." 0034 0035`). 갈라짐을 감추지 않고 드러내는 쪽을 택한 것이다.

Revision ID: 0035
Revises: 0033
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0035'
down_revision: Union[str, Sequence[str], None] = '0033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'carbon_neutral_point_applications'
COLUMN = 'draft_downloaded_at'


def upgrade() -> None:
    """Upgrade schema."""
    # nullable — 기존 초안은 내려받은 이력이 없다. 백필하지 않는다: 안 받은 걸 받았다고
    # 적으면 캘린더에 없던 일이 생긴다(원칙7 — 모르는 걸 값으로 채우지 않는다).
    op.add_column(TABLE, sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE, COLUMN)
