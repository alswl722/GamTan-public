"""감축 실천 ToDo — 카탈로그 조립 레이어. 정본: docs/reduction-todo-plan.md §10-4.

── 2026-08-25 재설계 배경 ──
1차 버전은 3층(기준부하) 숫자 카드를 그대로 "이번주 할 일"로 내보냈다. 실사용
화면에서 "10월 수준으로 돌아가면 0.02tCO2e 절감" 같은 결과가 나왔는데, 사용자
피드백 — "뭔가 이번주 할일이라는 느낌이 아니잖아", "단순하게 뭐 하세요가
될거같아서". 문제는 계산 정확도가 아니라 형식이었다: 결과 지표(숫자)를
행동(동사)인 것처럼 보여준 것.

재설계 원칙: **동사형 할 일 문장이 메인, 숫자(3층 목표)는 그 문장을 뒷받침하는
배경 정보로 축소.** 새 최상위 응답 필드 `todos`가 동사형 문장을 담는다.

── 2026-08-26: goals를 API 응답에서 제거 ──
`goals`(3층 숫자 — 연료별 기준부하/현재값/절감여지)는 화면 어디에도
렌더링되지 않는 죽은 응답 필드였다(ReductionTodoCard·GoalSheet 둘 다
todos만 쓴다, 사용자 확인). 사용자 지시로 API 응답에서 goals 키를 뺐다.
다만 이 계산 자체는 아직 살아있다 — `_llm_rerank_todos()`가 이 값(연료별
기준월↔최근월 tCO2e)을 LLM 프롬프트의 유일한 배출량 근거로 쓰기 때문에,
`reduction_todo_for_company()` 내부에서 지역변수로만 계속 계산한다(응답에
안 실릴 뿐 계산 자체는 필요).

── 사업 규모 분기 ──
소상공인(business_scale_hint == "소상공인/상업시설")은 2층(설비 신호)이 원래
잘 안 잡힌다 — 세금계산서보다 전기·가스 고지서 위주라 "전동지게차"·"공조설비"
같은 K택소노미 키워드가 애초에 안 걸린다(2026-08-25 사용자 질문 "만약 소상
공인이면?"에서 확인). 그래서 소상공인은 범용 절전 팁(FALLBACK_TIPS)을 메인
todos로 쓰고, 제조업은 2층 설비 신호를 동사형으로 바꿔 todos를 만든다.

소상공인에게는 이미 탄소중립포인트 트랙(db/carbon_neutral_point.py::
evaluate_eligibility)이 같은 "전기 아끼기" 메시지를 감축률·환급액으로 다루고
있다 — 여기서 새 감축률을 다시 계산하면 같은 기업에 대해 서로 다른 숫자를
내는 두 계산기가 생겨 CLAUDE.md §5 원칙10과 충돌할 소지가 있다. 그래서 이
모듈은 소상공인의 감축률/환급액을 **다시 계산하지 않는다** — business_scale_hint
값만 반환해 호출부(라우터)가 이미 있는 evaluate_eligibility() 결과를 그대로
붙이게 한다(2026-08-25 사용자 확정: "탄소중립포인트와 연결").

── 층 구조는 그대로 ──
3층(baseline_load_by_fuel/reduction_target_for_fuel)은 이제 API 응답에
직접 나가지 않고, LLM 선별(_fuel_load_summary)의 입력 재료로만 쓰인다.
2층(facility_signals)이 todos의 동사형 문장 재료다. 1층(get_distribution)은
액션을 직접 필터링하는 데는 안 쓰지만, LLM 선별의 배경 컨텍스트로는 쓴다
(_industry_summary_for_prompt, 아래 "LLM 선별" 섹션 참고 — 다른 목적의
재사용이라 원칙과 충돌하지 않는다).

LLM은 문구를 짓는 데 관여하지 않는다. 모든 문구는 정적 딕셔너리로 조립한다.

── 2026-08-26: LLM 선별(순서 재배치) 추가 ──
사용자 요청 — "기업의 배출량(연료별), 기업 규모, 업종, 동종 업계 데이터를
LLM에게 주면 그에 맞춰 투두 설계"에 대해 범위를 좁혀 확정했다: **LLM은
새 문장을 짓지 않고, 이미 정적 카탈로그에서 매칭된 todos 후보 중 이 기업
맥락에서 어떤 걸 먼저 보여줄지 "순서"만 정한다.** 카탈로그 확장(새 항목
추가)도 하지 않는다 — 지금 있는 설비 신호 매칭분만 재정렬 대상이다.

이건 원칙1(LLM 산수 금지)과 같은 방어 구조다: `_llm_rerank_todos()`의 응답
스키마엔 `id` 문자열 배열만 있고 숫자·문장 필드가 아예 없다 — 값을 지어낼
경로가 구조적으로 없다(db/document_llm_router.py가 셀 id만 고르고 값은
정규식이 재파싱하는 것과 동일한 결). 반환된 id 중 후보 리스트에 없는 값,
중복, 누락은 전부 무시하고 코드가 기운 순서(원래 순서)로 보정한다 — LLM이
목록에 없는 id를 지어내도 그 값이 그대로 노출될 경로가 없다.

실패 시(키 없음·호출 실패·응답 파싱 실패) 조용히 원래 순서로 폴백한다.
이상치 판단(_judge_anomaly_with_llm)과 달리 "재검증 실패"를 트레이스에
남기지 않는다 — 이 판단은 "계산"이 아니라 "정렬 취향"이라 실패해도 사장님이
검토해야 할 이상 상태가 아니다(코드가 이미 정한 순서 자체가 유효한 결과).

── 2026-08-26: 순서 재배치 결과 캐싱 추가 ──
홈 화면 카드는 열릴 때마다 이 함수를 호출한다 — 캐시가 없으면 같은 기업이
화면을 열 때마다 Gemini를 매번 다시 호출하게 된다(사용자 지적: "홈화면
들어올때마다 재계산 되잖아"). db/models.py::ReductionTodoRerankCache에
저장한다. 기존 llm_cache(§4)를 재사용하지 않는 이유는 그 테이블 참고.

cache_key = SHA256(company_id + 정렬된 todos id 목록 + fuel_summary 직렬화) —
todos 후보 구성이나 배출량이 바뀌면 키가 달라져 자동으로 무효화된다.

── 2026-08-26: 동기 호출 → 캐시 히트/백그라운드 재배치로 전환 ──
캐시 도입 직후 실측(포항이엔지·대구정공)에서 Gemini 호출이 10초 타임아웃을
넘겨 매번 폴백되는 걸 확인했다(504 DEADLINE_EXCEEDED) — 그런데 이건 그
자리에서 사용자를 기다리게 하는 구조 자체의 문제이기도 했다: 재배치가
성공하든 실패하든 응답이 나갈 때까지 화면이 막혀 있었고, 폴백됐을 때도
"이게 최종 결과인지 아직 분석 전인지" 구분할 방법이 없었다(사용자 지적:
"AI분석 중이면 분석중이라고 떠야할거같음").

그래서 캐시 미스일 때 그 자리에서 LLM을 기다리지 않는다 — 즉시 원래 순서를
반환하면서 `reorder_status: "pending"`을 함께 보내고, 실제 재배치는
BackgroundTasks로 넘겨 응답이 나간 뒤 실행한다(api/document_ingestion.py::
process_upload_job과 같은 패턴 — 독립 세션은 api/db.py::new_session()).
완료되면 캐시에 쌓이므로 다음 방문(또는 폴링)부터 `reorder_status: "ready"`
로 재배치된 순서가 나온다. 캐시 히트는 그대로 즉시 반환.

FALLBACK_TIPS로 빠지는 경로(K택소노미 신호 자체가 없음)는 애초에 재배치
대상이 아니라 reorder_status 필드를 아예 보내지 않는다(2026-08-26 사용자
확정: "매칭 결과 없을시에는 기본 폴백").
"""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.carbon_neutral_point import business_scale_hint as _business_scale_hint
from db.models import ReductionTodoRerankCache
from db.pcaf_engine.reduction_actions import (
    FALLBACK_TIPS,
    baseline_load_by_fuel,
    facility_signals,
    reduction_target_for_fuel,
)

_HINT_COMMERCIAL = "소상공인/상업시설"

# ── 안전한 카탈로그 (2026-08-26) ──────────────────────────────────────────
#
# 이전 버전은 "지게차 충전 시간을 야간으로 옮겨보세요"처럼 방법을 코드가
# 짧게 지어냈다. 사용자 피드백으로 안전 기준 3단계를 확정했다:
#
#   1순위 — 외부 공인 도구/기관으로 위임. 감탄이 스스로 아무것도 계산·판단
#           하지 않고 "거기 가서 확인하라"고만 안내한다. 숫자 자체가 아예
#           없어 원칙1(LLM 산수 금지)과 가장 멀리 떨어져 있다(예: 한전
#           파워플래너로 피크 시간대 확인).
#   2순위 — 구체적 정비 스펙이 들어간 문구. 반드시 **사람이 사전에 공신력
#           있는 출처로 검증**하고 코드에 고정해야 한다. LLM이 그때그때
#           만들면 안 된다 — 실제로 확인해보니 "0.5~1bar 한 번에 낮추기"
#           같은 직관적인 수치가 공식 권고(0.1bar씩 점진적으로)와 5배
#           어긋나는 사례가 있었다(아래 공기압축기 항목 출처 참고). 사람이
#           검증하지 않았다면 이 위험을 아무도 걸러내지 못했을 것이다.
#   3순위 — 그래도 검증된 외부 근거가 없으면 문구 자체를 넣지 않는다(빈
#           문구보다 없는 게 안전 — §7 verify_metric 없는 액션은 카탈로그에
#           등록 불가 원칙과 같은 결).
#
# 모든 문구는 LLM이 생성하지 않는다 — 이 정적 딕셔너리에 사람이 미리
# 확정해둔 것을 그대로 노출할 뿐이다(재현성 100%, 매번 같은 문구).
#
# facility_type: (연료버킷, 할 일 문장, note — 2026-08-26 전부 None으로 정리:
# "회색 글씨로 아래에 뜨는거 다 삭제" 사용자 지시. label 한 줄만으로 todo가
# 완결되게 한다. 근거 자체(파워플래너가 실재하는 서비스인지, 0.1bar 권고가
# 공식 자료에서 왔는지)는 여전히 사람이 검증해뒀고 코드 주석·계획 문서
# (docs/reduction-todo-plan.md §15)에 남아있다 — 화면에 안 보일 뿐이다.
_FACILITY_TODO_HINTS: dict[str, tuple[str, str, str | None]] = {
    "전동지게차": (
        "전기",
        "한전 파워플래너로 충전 시간대를 확인하고 피크 시간을 피해 충전해보세요",
        None,
    ),
    "공조설비 등": (
        "전기",
        "퇴근 전 공조설비 전원과 냉난방 설정온도가 적정한지 확인해보세요",
        None,
    ),
    "열관리 설비": (
        "전기",
        "히트펌프 가동 스케줄이 실제 사용 시간과 맞는지 점검해보세요",
        None,
    ),
    "대기방지시설": (
        "전기",
        "집진기를 상시가동 대신 공정 가동 시간에 맞춰 연동할 수 있는지 점검해보세요",
        None,
    ),
    "수처리 설비": (
        "전기",
        "폐수처리설비 가동 시간이 실제 처리 물량과 맞는지 점검해보세요",
        None,
    ),
}

_AGING_EQUIPMENT_TODO = (
    "한국에너지공단 무상 에너지진단을 신청해 노후 설비 효율을 점검받아보세요"
)
_AGING_EQUIPMENT_TODO_NOTE = None

# 공기압축기(콤프레샤) — K택소노미 매핑엔 없는 설비지만 제조업에서 매우
# 흔해 별도로 둔다. 특정 facility_type 신호와 무관하게, 제조업 기업이면
# facility_todos에 공통으로 포함한다.
#
# "0.1bar씩 점진적으로"라는 수치 자체는 한국에너지공단 에너지진단 Q&A
# (tips.energy.or.kr) 권장 방식에서 왔다(안전 카탈로그 2순위 — 사람이
# 사전 검증한 정비 스펙만 label에 넣는다는 원칙은 그대로 유지). note로
# 그 출처·이유를 부연 설명하지는 않는다(2026-08-26 사용자 지시 — "이런
# 부연설명 없어도돼").
_COMPRESSOR_TODO = "공기압축기 토출압력을 0.1bar씩 낮춰보며 공정에 문제없는지 확인해보세요"
_COMPRESSOR_TODO_NOTE = None


def _has_k_taxonomy_signal(signals: dict) -> bool:
    """K택소노미 매칭 신호(설비 유형 또는 노후설비 의심)가 하나라도 있는지.

    공기압축기 팁은 이 신호에 포함하지 않는다 — 압축기는 특정 전표 매칭과
    무관하게 "제조업이면 항상 보여주는 공통 팁"이라, 압축기 유무로 폴백 전환을
    판단하면 설비 신호가 전혀 없는 기업도 압축기 팁 1개 때문에 폴백(§6, 빈
    화면 금지 취지의 최소 3개 채움)이 안 걸리는 버그가 생긴다(2026-08-26 실측
    — 테스트 2건에서 len(todos)==1로 확인)."""
    return bool(signals["facility_types"]) or signals["aging_equipment"]


def _facility_todos(signals: dict) -> list[dict]:
    """제조업 기업의 동사형 할 일 — 매칭된 설비 신호를 행동 문장으로 바꾼다.
    K택소노미 신호가 하나도 없으면 빈 리스트(호출부가 FALLBACK_TIPS로 채운다,
    _has_k_taxonomy_signal 참고). 공기압축기 팁은 그 판단과 무관하게 신호가
    있을 때만 이 리스트에 실제로 포함된다 — 신호가 없는 케이스는 이 함수가
    아예 호출되지 않고 _tip_todos()로 대체되기 때문이다."""
    if not _has_k_taxonomy_signal(signals):
        return []
    todos = [{"id": "compressor_pressure", "label": _COMPRESSOR_TODO, "note": _COMPRESSOR_TODO_NOTE}]
    for facility_type in signals["facility_types"]:
        hint = _FACILITY_TODO_HINTS.get(facility_type)
        if hint is not None:
            todos.append({"id": f"facility_{facility_type}", "label": hint[1], "note": hint[2]})
    if signals["aging_equipment"]:
        todos.append({
            "id": "aging_equipment", "label": _AGING_EQUIPMENT_TODO,
            "note": _AGING_EQUIPMENT_TODO_NOTE,
        })
    return todos


def _tip_todos() -> list[dict]:
    """FALLBACK_TIPS를 동사형 todos 형태로 변환 — label을 그대로 쓰고 note를
    부가 설명으로 옮긴다(카탈로그 정식 목표가 아니라는 성격은 그대로 유지,
    §6 verify_metric 없음)."""
    return [{"id": tip["id"], "label": tip["label"], "note": tip["note"]} for tip in FALLBACK_TIPS]


# ── LLM 선별: 이미 매칭된 todos의 순서만 재배치 ────────────────────────────
_RERANK_MODEL = "gemini-3.5-flash"  # api/agent/orchestrator.py의 이상치 판단과 동일 모델

_RERANK_PROMPT = """너는 중소기업 사장님에게 탄소 감축 할 일을 안내하는 회계 보조 AI다.
아래는 이미 이 기업의 설비·전표 데이터로 확정된 할 일 후보 목록이다 —
너는 문장을 만들거나 바꾸지 않는다. 이 기업 상황에서 어떤 할 일부터 먼저
보여줄지 **순서만** 정하면 된다.

[기업 정보]
업종: {industry_name}
규모: 직원 {employee_count}명

[연료별 배출량 현황 — 최근 대비 기준월(추정치)]
{fuel_summary}

[동종 업계 비교]
{industry_summary}

[할 일 후보 목록 — id: 문장]
{candidates}

이 기업이 지금 가장 먼저 신경 써야 할 순서대로 candidate id를 나열하라.
후보 목록에 있는 id만 사용하고, 모든 id를 정확히 한 번씩만 포함하라.
다른 설명 없이 id를 쉼표로만 구분해 한 줄로 답하라.
형식: id1,id2,id3"""


def _fuel_summary_for_prompt(fuel_summary: list[dict]) -> str:
    """_fuel_load_summary()가 만든 3층 요약을 LLM 프롬프트용 텍스트로 옮긴다
    — 새 계산 없음, 있는 숫자를 문장으로만 나열한다."""
    if not fuel_summary:
        return "특이 변동 없음"
    lines = [
        f"- {g['fuel']}: 기준월({g['baseline_month']}월) {g['baseline_tco2e']}tCO2e → "
        f"최근({g['current_month']}월) {g['current_tco2e']}tCO2e"
        for g in fuel_summary
    ]
    return "\n".join(lines)


def _industry_summary_for_prompt(session: Session, company) -> str:
    """1층(get_distribution)을 LLM 컨텍스트로만 재사용한다 — 액션을 이 값으로
    직접 필터링하지 않는다는 기존 원칙(§5)은 유지하되, LLM이 우선순위를 정할
    때 참고할 배경 정보로 주는 것은 다른 결이다(2026-08-26 사용자 요청)."""
    from api.queries import get_distribution

    lines = []
    for scope, label in ((1, "Scope 1(직접배출)"), (2, "Scope 2(전기)")):
        d = get_distribution(session, company.industry_code, scope, company.employee_count)
        if d is not None and d["median"] is not None:
            lines.append(f"- {label} 업종 중앙값: {d['median']}tCO2e (표본 {d['sample_size']}개)")
    return "\n".join(lines) if lines else "동종 업계 비교 데이터 없음"


def _rerank_cache_key(company_id: int, todos: list[dict], fuel_summary: list[dict]) -> str:
    """캐시 키 = company_id + todos id 목록(정렬) + fuel_summary를 해시한 값.
    todos 후보 구성이나 배출량이 바뀌면 자동으로 다른 키가 돼 무효화된다."""
    payload = {
        "company_id": company_id,
        "todo_ids": sorted(t["id"] for t in todos),
        "fuel_summary": fuel_summary,  # 이미 fuel/baseline_month/... 순으로 정렬된 리스트
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rerank_cache_get(session: Session, cache_key: str) -> list[str] | None:
    cached = session.execute(
        select(ReductionTodoRerankCache).where(ReductionTodoRerankCache.cache_key == cache_key)
    ).scalar_one_or_none()
    if cached is None:
        return None
    cached.hit_count = (cached.hit_count or 0) + 1
    from datetime import datetime, timezone

    cached.last_used_at = datetime.now(timezone.utc)
    session.commit()
    return cached.ordered_ids


def _rerank_cache_put(session: Session, company_id: int, cache_key: str, ordered_ids: list[str]) -> None:
    from sqlalchemy.exc import IntegrityError

    session.add(ReductionTodoRerankCache(
        company_id=company_id, cache_key=cache_key, ordered_ids=ordered_ids,
    ))
    try:
        session.commit()
    except IntegrityError:
        # 동시 요청 등으로 동일 cache_key가 이미 존재 — 기존 캐시를 신뢰하고 버림
        session.rollback()


def _apply_cached_order(todos: list[dict], cached_ids: list[str]) -> list[dict]:
    """캐시에 저장된 id 순서를 todos에 적용. 누락·오타 id는 뒤에 원순서로 보정."""
    by_id = {t["id"]: t for t in todos}
    ordered = [by_id[cid] for cid in cached_ids if cid in by_id]
    seen_ids = {t["id"] for t in ordered}
    ordered += [t for t in todos if t["id"] not in seen_ids]
    return ordered


def _rerank_lookup(
    session: Session, company_id: int, todos: list[dict], fuel_summary: list[dict],
) -> tuple[list[dict], str]:
    """캐시만 조회한다 — LLM을 절대 호출하지 않는다(그 자리에서 사용자를
    기다리게 하지 않기 위함, 2026-08-26 재설계). 항상 즉시 반환.

    반환: (todos_순서, reorder_status)
      - "ready": 캐시 적중, 재배치된 순서
      - "pending": 캐시 미스, 원래 순서를 우선 보여주고 호출부가 백그라운드
        재배치(run_rerank_and_cache)를 큐에 넣어야 한다
    todos가 1개 이하면 재배치할 게 없으므로 그냥 "ready"로 취급한다."""
    if len(todos) <= 1:
        return todos, "ready"

    cache_key = _rerank_cache_key(company_id, todos, fuel_summary)
    cached_ids = _rerank_cache_get(session, cache_key)
    if cached_ids is not None:
        return _apply_cached_order(todos, cached_ids), "ready"
    return todos, "pending"


def run_rerank_and_cache(
    company_id: int, todos: list[dict], fuel_summary: list[dict], session: Session | None = None,
) -> None:
    """실제 LLM 호출 + 캐시 저장 — BackgroundTasks 전용, 응답이 이미 나간 뒤
    실행된다(api/document_ingestion.py::process_upload_job과 같은 패턴).
    반환값을 아무도 안 쓴다 — 결과는 캐시를 통해서만 다음 요청에 전달된다.

    session을 생략하면(프로덕션 기본) 요청 스코프 세션이 응답과 함께 이미
    닫혀 있으므로 독립 세션을 직접 열고 여기서 닫는다. session을 직접
    넘기면(테스트 전용 — process_upload_job과 동일 이유: 호출부의 fixture
    세션을 그대로 써야 결과가 같은 트랜잭션에서 보인다) 그 세션을 그대로
    쓰고 여기서 닫지 않는다(호출자가 lifecycle을 소유).

    실패해도 조용히 끝낸다 — 캐시가 안 생길 뿐, 다음 요청도 여전히 원래
    순서로 정상 응답한다(정렬 취향이지 사장님이 볼 이상 상태가 아니라는
    원칙은 동기 시절과 동일)."""
    if len(todos) <= 1:
        return

    import os

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return

    from db.models import Company

    owns_session = session is None
    if session is None:
        from api.db import new_session

        session = new_session()
    try:
        company = session.get(Company, company_id)
        if company is None:
            return

        cache_key = _rerank_cache_key(company_id, todos, fuel_summary)
        # 다른 요청이 그 사이 먼저 채웠을 수 있다 — 중복 호출 방지.
        if _rerank_cache_get(session, cache_key) is not None:
            return

        candidates_text = "\n".join(f"{t['id']}: {t['label']}" for t in todos)

        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=10_000),
        )
        resp = client.models.generate_content(
            model=_RERANK_MODEL,
            contents=_RERANK_PROMPT.format(
                industry_name=company.industry_name or company.industry_code,
                employee_count=company.employee_count or "미상",
                fuel_summary=_fuel_summary_for_prompt(fuel_summary),
                industry_summary=_industry_summary_for_prompt(session, company),
                candidates=candidates_text,
            ),
        )
        raw_ids = [x.strip() for x in (resp.text or "").strip().split(",") if x.strip()]

        ordered = _apply_cached_order(todos, raw_ids)
        _rerank_cache_put(session, company_id, cache_key, [t["id"] for t in ordered])
    except Exception:  # noqa: BLE001 — 백그라운드 실패는 조용히 끝낸다(캐시만 안 생김)
        pass
    finally:
        if owns_session:
            session.close()


def _fuel_load_summary(session: Session, company_id: int, *, months: list[tuple[int, int]] | None) -> list[dict]:
    """3층(baseline_load_by_fuel)에서 절감 여지가 있는 연료만 추려 LLM 선별
    입력으로 쓸 요약을 만든다. 예전엔 이 결과가 API 응답 "goals" 필드로
    그대로 나갔으나, 화면 어디에도 렌더링되지 않는 죽은 필드로 확인돼
    2026-08-26 사용자 지시로 응답에서 뺐다 — 계산 자체는 _llm_rerank_todos의
    유일한 배출량 근거라 이 내부 헬퍼로 남긴다."""
    baseline = baseline_load_by_fuel(session, company_id, months=months)
    summary = []
    for fuel, load in baseline.items():
        target = reduction_target_for_fuel(load["baseline_tco2e"], load["current_tco2e"])
        if target is None:
            continue
        summary.append({
            "fuel": fuel,
            "baseline_tco2e": load["baseline_tco2e"],
            "baseline_month": load["baseline_month"],
            "current_tco2e": load["current_tco2e"],
            "current_month": load["current_month"],
        })
    summary.sort(key=lambda g: g["current_tco2e"] - g["baseline_tco2e"], reverse=True)
    return summary


def reduction_todo_for_company(session: Session, company_id: int, *, months: list[tuple[int, int]] | None = None) -> dict:
    """홈 화면 카드용 최종 응답. LLM을 직접 호출하지 않는다 — 캐시만 조회하고
    끝난다(2026-08-26 재설계, 위 모듈 docstring 참고). 그 자리에서 Gemini
    응답을 기다리지 않으므로 요청이 절대 오래 걸리지 않는다.

    반환:
      {
        "business_scale_hint": str,  # "제조업/산업체" | "소상공인/상업시설" | ...
        "todos": [{"id": str, "label": str, "note": str | None}, ...],  # 메인 콘텐츠, 동사형
        "reorder_status": "ready" | "pending",  # 설비 신호 경로에서만 존재.
            "ready"=캐시된 순서(또는 재배치 대상 아님), "pending"=캐시 미스,
            원래 순서를 우선 보여주는 중이고 백그라운드 재배치가 방금 큐에
            들어갔다(호출부가 _rerank_background_job으로 꺼내 실행해야 함).
        "_rerank_background_job": (company_id, todos, fuel_summary) | None,
            pending일 때만 채워지는 내부 신호 — 라우터가 이 튜플을
            run_rerank_and_cache(*job)으로 background_tasks에 등록한 뒤
            응답 본문에서는 이 키를 제거해야 한다(사용자에게 노출 금지).
      }

    todos는 항상 채워진다(빈 화면 금지, §6):
      - 제조업 + 설비 신호 있음: 그 신호를 동사형으로 바꾼 뒤, 캐시에 이미
        재배치된 순서가 있으면 그걸 쓰고(ready), 없으면 원래 순서를 우선
        보여주며 백그라운드 재배치를 큐에 남긴다(pending).
      - 제조업 + 설비 신호 없음, 소상공인: FALLBACK_TIPS로 채운다. 이 경로는
        애초에 재배치 대상이 아니라 reorder_status 자체가 없다(2026-08-26
        사용자 확정 — "매칭 결과 없을시에는 기본 폴백"). 소상공인의
        감축률·환급액은 이 함수가 계산하지 않는다 — business_scale_hint만
        반환하고, 라우터가 이미 있는 get_carbon_point_eligibility 결과를
        붙인다(중복 계산기 방지).
    """
    hint = _business_scale_hint(session, company_id)
    signals = facility_signals(session, company_id)

    if hint == _HINT_COMMERCIAL:
        return {"business_scale_hint": hint, "todos": _tip_todos()}

    todos = _facility_todos(signals)
    if not todos:
        return {"business_scale_hint": hint, "todos": _tip_todos()}

    fuel_summary = _fuel_load_summary(session, company_id, months=months)
    ordered, status = _rerank_lookup(session, company_id, todos, fuel_summary)

    result = {"business_scale_hint": hint, "todos": ordered, "reorder_status": status}
    if status == "pending":
        result["_rerank_background_job"] = (company_id, todos, fuel_summary)
    return result
