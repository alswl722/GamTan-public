"""실행 직렬화 — 같은 company에 대한 분류·에이전트 동시 실행 방지.

두 요청이 같은 미분류 전표를 집어 중복 insert(voucher_id unique 충돌) 하거나
트레이스 세션이 섞이는 것을 막는다. 단일 프로세스(uvicorn 1워커) 데모 규모 전제
— api/agent/progress.py 와 동일한 범위 제한.
"""
import threading
from collections import defaultdict
from contextlib import contextmanager

from fastapi import HTTPException

_guard = threading.Lock()
_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)


@contextmanager
def company_run_lock(company_id: int):
    """비블로킹 획득 — 이미 실행 중이면 409. 더블클릭·동시 호출을 충돌 대신 안내로."""
    with _guard:
        lock = _locks[company_id]
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="이미 실행 중입니다 — 완료 후 다시 시도하세요")
    try:
        yield
    finally:
        lock.release()
