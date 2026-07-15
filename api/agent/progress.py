"""분류 진행률 — 프로세스 메모리 전역 딕셔너리.

classify_vouchers 는 동기 호출(POST 응답까지 블로킹)이라, 진행 중 상태를
프론트가 폴링하려면 별도 저장소가 필요하다. 단일 프로세스(uvicorn 1워커) 데모
규모에 한해 유효 — 멀티워커·재시작 넘어가는 영속성은 필요 없음(CLAUDE.md 범위 밖).
"""
import threading

_lock = threading.Lock()
_progress: dict[int, dict] = {}  # company_id -> {done, total, done_at: bool}


def reset(company_id: int, total: int) -> None:
    with _lock:
        _progress[company_id] = {"done": 0, "total": total, "finished": total == 0}


def tick(company_id: int, done: int, total: int) -> None:
    with _lock:
        _progress[company_id] = {"done": done, "total": total, "finished": done >= total}


def get(company_id: int) -> dict:
    with _lock:
        return dict(_progress.get(company_id, {"done": 0, "total": 0, "finished": True}))
