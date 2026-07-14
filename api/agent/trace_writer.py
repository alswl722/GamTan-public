"""트레이스 기록 헬퍼 — 오케스트레이터의 [계획]/[관찰]/[행동] 판단 일지를 trace_logs에 쓴다.

장면② 트레이스 뷰의 데이터 소스. 한 실행 = 한 session_id. created_at은 default now()에
맡겨 /trace/latest 가 시드보다 이 실행을 위로 랭크하도록 한다.
"""
import uuid

from sqlalchemy.orm import Session

from db.models import TraceLog

# 프론트(SceneTrace)가 아는 타입만 허용 — 그 외는 관찰로 폴백되므로 강제한다.
STEP_TYPES = ("계획", "관찰", "행동")


def new_session_id() -> str:
    return str(uuid.uuid4())


def log_step(
    session: Session,
    company_id: int,
    session_id: str,
    step_type: str,
    message: str,
    tool_name: str | None = None,
    detail: dict | None = None,
) -> None:
    """trace_logs 1행 기록 후 커밋. step_type은 계획/관찰/행동만."""
    assert step_type in STEP_TYPES, f"잘못된 step_type: {step_type}"
    session.add(
        TraceLog(
            company_id=company_id,
            session_id=session_id,
            step_type=step_type,
            tool_name=tool_name,
            message=message,
            detail_json=detail,
        )
    )
    session.commit()
