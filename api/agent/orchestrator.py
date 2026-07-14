"""오케스트레이터 — 도구 4종 위에 얹은 에이전트 루프 (킬러씬 A).

"이 기업의 탄소 리포트를 만들어라"는 목표를 받고, Gemini function calling으로
도구를 스스로 골라 호출한다. 코어 규칙은 "결손 검사를 먼저 수행하라" — 3~5월
도시가스 결손을 스스로 발견 → 사장 알림 → 분류·계산·등급 산정. 전 판단을
[계획]/[관찰]/[행동]으로 trace_logs에 기록한다(장면② 데이터 소스).

LLM 루프가 실패하거나 GEMINI_API_KEY가 없으면 **동일 트레이스 포맷의 결정론적
순차 러너**로 자동 폴백한다(CLAUDE.md D9 — 오프라인·무키 데모 방탄).
"""
import os

from sqlalchemy.orm import Session

from api.agent.tools import (
    calculate_pcaf,
    classify_vouchers,
    collect_vouchers,
    get_industry_distribution,
)
from api.agent.trace_writer import log_step, new_session_id
from db.models import Company

MODEL = "gemini-3.5-flash"   # 분류(llm_classify)와 동일 모델로 통일
MAX_ITERS = 6                # CLAUDE.md §6 최대 반복

_OPENER = "2024년 12개월 전표 분석 시작 → 결손 검사를 먼저 수행"

SYSTEM_PROMPT = """너는 대구·경북 소부장 중소기업의 탄소 배출량을 측정하는 AI 에이전트다.
목표: 주어진 기업의 탄소 리포트를 만들어라.

반드시 이 순서와 규칙을 따른다:
1. 먼저 collect_vouchers 로 전표를 수집하고 결과의 coverage.gaps 로 결손월을 검사한다 (결손 검사 우선).
2. 결손월이 있으면(예: 3~5월 도시가스 0건) notify_owner 로 사장에게 연동 요청 알림을 보낸다.
3. classify_vouchers 로 전표를 분류하고, calculate_pcaf 로 배출량·PCAF 등급을 산정한다.
4. 필요하면 get_industry_distribution(scope) 로 동종 업종 분포를 참조해 이상치·벤치마킹을 확인한다.
5. 리포트에 필요한 정보가 모이면 도구 호출을 멈추고 한 줄로 마무리한다.

계산(물량·탄소량)은 도구가 결정론적으로 수행한다. 너는 어떤 도구를 언제 부를지 판단만 한다."""


# 함수명 → (trace step_type, 한국어 tool_name). notify_owner 는 행동, 데이터 조회는 관찰.
_TOOL_META = {
    "collect_vouchers": ("관찰", "마이데이터 수집기"),
    "classify_vouchers": ("행동", "전표 분류기"),
    "calculate_pcaf": ("행동", "계산·PCAF 엔진"),
    "get_industry_distribution": ("관찰", "업종 분포 조회"),
    "notify_owner": ("행동", "알림 생성기"),
}


# ── 도구 실행부: 모델의 함수 호출을 실제 함수로 (session, company_id 주입) ──────
def _execute(name: str, args: dict, session: Session, company: Company) -> dict:
    cid = company.id
    if name == "collect_vouchers":
        return collect_vouchers(session, cid)
    if name == "classify_vouchers":
        return classify_vouchers(session, cid)
    if name == "calculate_pcaf":
        return calculate_pcaf(session, cid)
    if name == "get_industry_distribution":
        scope = int(args.get("scope", 1))
        return get_industry_distribution(session, company.industry_code, scope) or {}
    if name == "notify_owner":
        return {"ack": True, "message": args.get("message", "")}
    raise ValueError(f"알 수 없는 도구: {name}")


# ── [관찰]/[행동] 메시지 포매터: 결과 dict → 데모급 한국어 한 줄 ─────────────
def _summarize(name: str, args: dict, result: dict) -> tuple[str, dict | None]:
    """(trace message, detail_json) 반환."""
    if name == "collect_vouchers":
        cov = result.get("coverage", {})
        gaps = cov.get("gaps", [])
        msg = f"전표 {result.get('count', 0)}건 수집 완료"
        gas = next((g for g in gaps if g["fuel"] == "가스"), None)
        if gas:
            months = "·".join(str(m) for m in gas["missing_months"])
            msg += f" — {months}월 도시가스 0건, 제조업 특성상 비정상(결손 발견)"
        return msg, cov

    if name == "classify_vouchers":
        bm = result.get("by_method", {})
        msg = (
            f"전표 {result.get('processed', 0)}건 분류 "
            f"(룰 {bm.get('rule', 0)}·LLM {bm.get('llm', 0)}), "
            f"저신뢰 {result.get('review_required', 0)}건 HITL 회부"
        )
        return msg, result

    if name == "calculate_pcaf":
        before, after, bench = result.get("before"), result.get("after"), result.get("benchmark") or {}
        if after:
            msg = (
                f"매출추정 {before['grade']}등급 → 전표기반 {after['grade']}등급 산정 "
                f"({after['total']} tCO2e). {bench.get('percentile_text') or ''}".strip()
            )
        else:
            msg = f"기준선 {before['grade']}등급 산정(분류 결과 없음 — 전표 기반 산정 불가)"
        return msg, {"before": before, "after": after, "benchmark": bench}

    if name == "get_industry_distribution":
        if result:
            msg = (
                f"동종 {result.get('industry_name', '업종')} Scope{result.get('scope', '')} "
                f"중앙값 {result.get('median')} tCO2e (min {result.get('min')}~max {result.get('max')}) 참조"
            )
        else:
            msg = "동종 업종 분포 데이터 없음"
        return msg, result or None

    if name == "notify_owner":
        return f"사장님 알림 발송: {args.get('message', '')}", None

    return f"{name} 완료", result


def _model_view(name: str, result: dict) -> dict:
    """모델에 회신할 요약(전표 33건 원본 등 컨텍스트 폭증 방지)."""
    if name == "collect_vouchers":
        return {"count": result.get("count"), "gaps": result.get("coverage", {}).get("gaps", [])}
    if name == "classify_vouchers":
        return {k: result.get(k) for k in ("processed", "review_required", "by_method")}
    if name == "calculate_pcaf":
        after = result.get("after")
        return {
            "before_grade": (result.get("before") or {}).get("grade"),
            "after_grade": (after or {}).get("grade"),
            "total_tco2e": (after or {}).get("total"),
        }
    if name == "get_industry_distribution":
        return {k: result.get(k) for k in ("median", "min", "max")} if result else {}
    return result


# ── 공용 스텝 실행: 도구 호출 → 트레이스 기록 → 모델 회신용 요약 반환 ─────────
def _run_tool_and_log(session, company, sid, name, args) -> dict:
    result = _execute(name, args, session, company)
    step_type, tool_name = _TOOL_META[name]
    message, detail = _summarize(name, args, result)
    log_step(session, company.id, sid, step_type, message, tool_name=tool_name, detail=detail)
    return _model_view(name, result)


# ── LLM 경로: Gemini function-calling 매뉴얼 루프 ─────────────────────────────
def _run_llm(session: Session, company: Company, sid: str) -> None:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 없음")

    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(name="collect_vouchers", description="회사의 12개월 전표를 수집하고 월별 결손(coverage.gaps)을 반환한다."),
        types.FunctionDeclaration(name="classify_vouchers", description="미분류 전표를 룰+LLM으로 Scope 분류하고 배출량을 계산해 저장한다."),
        types.FunctionDeclaration(name="calculate_pcaf", description="저장된 분류를 집계해 PCAF Before/After 등급과 벤치마킹을 반환한다."),
        types.FunctionDeclaration(
            name="get_industry_distribution",
            description="동종 업종의 배출량 분포(min/median/max)를 조회한다.",
            parameters_json_schema={"type": "object", "properties": {"scope": {"type": "integer", "description": "1(직접) 또는 2(간접)"}}, "required": ["scope"]},
        ),
        types.FunctionDeclaration(
            name="notify_owner",
            description="사장에게 알림을 보낸다(결손 데이터 연동 요청 등).",
            parameters_json_schema={"type": "object", "properties": {"message": {"type": "string", "description": "사장에게 보낼 한국어 알림 문구"}}, "required": ["message"]},
        ),
    ])
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    client = genai.Client(api_key=api_key)

    log_step(session, company.id, sid, "계획", _OPENER)
    contents = [types.Content(role="user", parts=[types.Part(text=f"기업 '{company.name}'의 탄소 리포트를 만들어라.")])]

    for _ in range(MAX_ITERS):
        resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
        parts = resp.candidates[0].content.parts or []
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        texts = [p.text for p in parts if getattr(p, "text", None)]

        for t in texts:
            log_step(session, company.id, sid, "계획", t.strip())

        if not calls:
            break

        contents.append(resp.candidates[0].content)   # 모델 턴(함수호출) 회신
        responses = []
        for fc in calls:
            args = dict(fc.args) if fc.args else {}
            view = _run_tool_and_log(session, company, sid, fc.name, args)
            responses.append(types.Part.from_function_response(name=fc.name, response={"result": view}))
        contents.append(types.Content(role="user", parts=responses))


# ── 폴백: 결정론적 순차 러너 (무LLM, 동일 트레이스 포맷) ─────────────────────
def _run_sequential(session: Session, company: Company, sid: str) -> None:
    cid = company.id
    log_step(session, cid, sid, "계획", _OPENER)

    collect = _run_tool_and_log(session, company, sid, "collect_vouchers", {})
    if any(g["fuel"] == "가스" for g in collect.get("gaps", [])):
        _run_tool_and_log(session, company, sid, "notify_owner",
                          {"message": "3~5월 가스 고지서 미연동 확인 필요 — 연동 시 등급 상향 가능"})

    _run_tool_and_log(session, company, sid, "classify_vouchers", {})
    _run_tool_and_log(session, company, sid, "get_industry_distribution", {"scope": 1})
    _run_tool_and_log(session, company, sid, "calculate_pcaf", {})

    log_step(session, cid, sid, "계획",
             "PCAF 상위 등급까지 부족 데이터 1건(가스 3~5월 실측치) → 사장 연동 요청 목록 생성")


def run_agent(session: Session, company_id: int) -> dict:
    """오케스트레이터 실행. LLM 루프 → 실패 시 결정론적 폴백. 트레이스는 어느 쪽이든 기록."""
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company_id={company_id} 없음")

    sid = new_session_id()
    mode = "llm"
    try:
        _run_llm(session, company, sid)
    except Exception as exc:  # noqa: BLE001 — 무키·API오류·SDK드리프트 모두 폴백
        session.rollback()
        mode = "fallback"
        log_step(session, company_id, sid, "계획",
                 f"라이브 에이전트 사용 불가({type(exc).__name__}) — 동작 설계 시각화(폴백)로 진행")
        _run_sequential(session, company, sid)

    from db.models import TraceLog  # 지역 import — 순환 회피
    count = session.query(TraceLog).filter_by(session_id=sid).count()
    return {"session_id": sid, "mode": mode, "step_count": count}
