"""cnp_application_applicant_fields

탄소중립포인트 사업자 참여신청서에서 **사장님이 직접 입력해야 하는 항목**을
`carbon_neutral_point_applications`의 컬럼으로 받는다 — 신청서 초안 화면이 4단계
위저드(측정완료 → 있는 데이터 확인 → 없는 데이터 입력 → 다운로드)로 바뀌면서 3단계
입력값을 어딘가 영속화해야 하는데, 여태 이 테이블엔 감탄이 계산한 값(사용량·감축률)만
있었다.

왜 컬럼이고 JSON이 아닌가: 서식이 정부 고시 양식이라 필드 집합이 닫혀 있고,
`incentive_type`은 `carbon_neutral_point_enrollments.point_type`과 어휘를 공유해야 해서
CHECK를 걸 수 있는 쪽이 낫다. 사용량 스냅숏(`baseline_usage_json`)이 JSON인 건 에너지원이
계속 늘어나는 열린 집합이기 때문이고, 이 필드들은 성격이 다르다.

전부 nullable이다 — 초안은 부분 입력 상태로도 저장돼야 하고(3단계를 중간에 이탈해도
날아가지 않아야 한다), 기존 레코드엔 값이 없다. 백필하지 않는다.

⚠️ **비밀번호 컬럼은 의도적으로 없다.** 서식에 비밀번호 칸이 있지만 그건 탄소중립포인트
포털 계정의 비밀번호이고, 우리가 대신 보관할 이유가 없는 타 기관 자격증명이다. 가입 처리
후 포털이 임시번호를 문자로 보내주는 흐름이라(`REMAINING_FIELDS` 안내 문구 참고) 감탄이
값을 들고 있어야 할 단계 자체가 없다. 화면도 이 칸을 입력받지 않고 직접 적으라고 안내한다.

`거주 면적`·`세대원 수`·`전입일자`도 컬럼을 만들지 않는다 — 상업시설 신청에는 해당 없어
`db/carbon_neutral_point.py::BLANK_BY_POLICY`가 초안에서 아예 제외하는 항목이다.
반면 `영업개시일자`는 사업자에게 유효한 항목인데 마이데이터 사업자등록증명 mock에 개업일자가
없어(2026-08-25 확인) 사장님 입력으로 받는다.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0032'
down_revision: Union[str, Sequence[str], None] = '0031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'carbon_neutral_point_applications'

# (컬럼명, 타입) — 전부 nullable. 순서는 서식 1페이지를 읽는 순서를 따른다.
_COLUMNS = (
    # 서식 최상단 체크박스: □가입신청 / □정보변경신청
    ('application_kind', sa.String(20)),
    # 아이디(ID) — 영문·숫자 조합. 비밀번호는 받지 않는다(위 주석).
    ('portal_id', sa.String(20)),
    # 법인번호 — "법인사업자만 해당". 개인사업자는 null이 정상이다.
    ('corporate_registration_no', sa.String(20)),
    ('applicant_phone', sa.String(30)),
    ('applicant_email', sa.String(255)),
    # 주소 — 우편번호/도로명/상세를 쪼개서 받는다. 서식이 우편번호 칸을 따로 두고 있고,
    # 사업자등록증명에는 우편번호가 없어(마이데이터 mock 주석) 직접 입력 대상이다.
    ('postal_code', sa.String(10)),
    ('road_address', sa.String(255)),
    ('address_detail', sa.String(255)),
    # 인센티브 유형 — enrollments.point_type과 같은 5종 어휘.
    ('incentive_type', sa.String(30)),
    ('incentive_type_other', sa.String(100)),
    # 금융정보 — 서식이 "인센티브 유형을 ②현금으로 선택한 분만" 기입하라고 명시한다.
    ('bank_name', sa.String(50)),
    ('account_number', sa.String(50)),
    ('account_holder', sa.String(50)),
    # 고지서 고객번호 4종. 전기는 고지서 파싱으로 채워지지만(_electric_customer_number)
    # 파싱 실패 시 사장님이 덮어쓸 수 있어야 해서 컬럼을 둔다 — 서식의 필수 항목이다.
    ('electric_customer_number', sa.String(50)),
    ('water_customer_number', sa.String(50)),
    ('city_gas_customer_number', sa.String(50)),
    ('district_heating_customer_number', sa.String(50)),
    # 영업개시일자 — 서식에서 '전입일자'와 같은 행에 있으나 사업자에게 유효한 항목이다.
    ('business_open_date', sa.Date()),
    # 사장님이 3단계를 마지막으로 저장한 시각. created_at(초안 생성)과 구분된다.
    ('applicant_input_updated_at', sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, type_ in _COLUMNS:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True))
    # 어휘는 enrollments.point_type과 같아야 한다 — 같은 제도의 같은 선택지라 두 테이블에
    # 다른 값이 들어가면 초안과 가입 기록이 어긋난다. 'local_currency'는 서식에 없어 제외
    # (0030 enrollments 제약과 동일한 판단).
    op.create_check_constraint(
        'ck_cnp_applications_incentive_type',
        TABLE,
        "incentive_type IS NULL OR incentive_type IN "
        "('gift_certificate', 'cash', 'cash_donation', 'green_card_point', 'other')",
    )
    op.create_check_constraint(
        'ck_cnp_applications_application_kind',
        TABLE,
        "application_kind IS NULL OR application_kind IN ('new', 'change')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_cnp_applications_application_kind', TABLE, type_='check')
    op.drop_constraint('ck_cnp_applications_incentive_type', TABLE, type_='check')
    for name, _ in reversed(_COLUMNS):
        op.drop_column(TABLE, name)
