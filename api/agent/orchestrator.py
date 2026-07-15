"""오케스트레이터 — 도구 4종 위에 얹은 에이전트 루프 (킬러씬 A).

"이 기업의 탄소 리포트를 만들어라"는 목표를 받고, Gemini function calling으로
도구를 스스로 골라 호출한다. 코어 규칙은 "결손 검사를 먼저 수행하라" — 3~5월
도시가스 결손을 스스로 발견 → 사장 알림 → 분류·계산·등급 산정. 전 판단을
[계획]/[관찰]/[행동]으로 trace_logs에 기록한다(장면② 데이터 소스).

LLM 루프가 실패하거나 GEMINI_API_KEY가 없으면 **동일 트레이스 포맷의 결정론적
순차 러너**로 자동 폴백한다(CLAUDE.md D9 — 오프라인·무키 데모 방탄).
"""
import os
import time

from sqlalchemy.orm import Session

from api.agent.tools import (
    calculate_pcaf,
    classify_vouchers,
    collect_vouchers,
    get_industry_distribution,
)
from api.agent.trace_writer import log_step, new_session_id
from db.models import Classification, Company, Voucher

MODEL = "gemini-3.5-flash"   # 분류(llm_classify)와 동일 모델로 통일
MAX_ITERS = 6                # CLAUDE.md §6 최대 반복

_OPENER = "2024년 12개월 전표 분석 시작 → 결손 검사를 먼저 수행"

SYSTEM_PROMPT = """너는 대구·경북 소부장 중소기업의 탄소 배출량을 측정하는 AI 에이전트다.
목표: 주어진 기업의 탄소 리포트를 만들어라.

반드시 이 순서와 규칙을 따른다:
1. 먼저 collect_vouchers 로 전표를 수집하고 결과의 coverage.gaps 로 결손월을 검사한다 (결손 검사 우선).
2. 결손월이 있으면(예: 3~5월 도시가스 0건) notify_owner 로 사장에게 연동 요청 알림을 보낸다.
3. classify_vouchers 로 전표를 분류하고, calculate_pcaf 로 배출량·PCAF 등급을 산정한다.
4. 분류·계산 후 check_anomalies 로 이상치를 확인한다. 이상치(업종 평균 대비 과다)가 있으면
   inspect_vouchers(month, fuel) 로 해당 전표를 재파싱해 스스로 검증한다:
   - 전표 문구상 실제 고배출 사유(예: '증차', '설비 증설')가 보이면 오분류가 아닌 정상으로 판정하고 그 사유를 한 줄로 남긴다.
   - 사유가 불명확하면 notify_owner 로 사장 검토를 요청한다.
5. 필요하면 get_industry_distribution(scope) 로 동종 업종 분포를 벤치마킹 참조한다.
6. 리포트에 필요한 정보가 모이면 도구 호출을 멈추고 한 줄로 마무리한다.

계산(물량·탄소량)은 도구가 결정론적으로 수행한다. 너는 어떤 도구를 언제 부를지, 이상치가 정상인지 판단만 한다."""


# 함수명 → (trace step_type, 한국어 tool_name). notify_owner 는 행동, 데이터 조회는 관찰.
_TOOL_META = {
    "collect_vouchers": ("관찰", "마이데이터 수집기"),
    "classify_vouchers": ("행동", "전표 분류기"),
    "calculate_pcaf": ("행동", "계산·PCAF 엔진"),
    "get_industry_distribution": ("관찰", "업종 분포 조회"),
    "notify_owner": ("행동", "알림 생성기"),
    "check_anomalies": ("관찰", "이상치 검증기"),
    "inspect_vouchers": ("행동", "전표 재파싱기"),
}

_ANOMALY_THRESHOLD = 2.5  # 월별 배출량이 업종 월중앙값의 N배↑면 이상치로 의심


# ── 이상치 감지·재검증 (결정론 계산 — LLM 산수 금지 원칙 유지) ────────────────
def _check_anomalies(session: Session, company: Company) -> dict:
    """월별 Scope1 배출량 vs 업종 월중앙값. 임계 배수↑ 이상치 목록 반환."""
    from sqlalchemy import func, select

    dist = get_industry_distribution(session, company.industry_code, 1)
    median = (dist or {}).get("median")
    if not median:
        return {"outliers": []}
    monthly_median_kg = median * 1000.0 / 12.0   # 연 tCO2e → 월 kgCO2e
    rows = session.execute(
        select(Voucher.month, Classification.fuel_type, func.sum(Classification.emission_co2e))
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company.id, Classification.scope == 1, Classification.emission_co2e > 0)
        .group_by(Voucher.month, Classification.fuel_type)
    ).all()
    outliers = []
    for month, fuel, emission in rows:
        ratio = (emission or 0) / monthly_median_kg if monthly_median_kg else 0
        if ratio >= _ANOMALY_THRESHOLD:
            outliers.append({"month": int(month), "fuel": fuel, "ratio": round(ratio, 1)})
    outliers.sort(key=lambda o: -o["ratio"])
    return {"outliers": outliers}


def _inspect_vouchers(session: Session, company: Company, month: int, fuel: str) -> dict:
    """해당 월·연료 전표 품목명 반환 — 에이전트가 이상치를 재검증(재파싱)."""
    from sqlalchemy import select

    rows = session.execute(
        select(Voucher.item_description, Voucher.supply_amount_krw)
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company.id, Voucher.month == month, Classification.fuel_type == fuel)
    ).all()
    return {"vouchers": [{"item": r[0], "amount": int(r[1]) if r[1] is not None else None} for r in rows]}


# ── 도구 실행부: 모델의 함수 호출을 실제 함수로 (session, company_id 주입) ──────
def _execute(name: str, args: dict, session: Session, company: Company) -> dict:
    cid = company.id
    if name == "collect_vouchers":
        return collect_vouchers(session, cid)
    if name == "classify_vouchers":
        from api.agent import progress

        return classify_vouchers(
            session, cid, on_progress=lambda done, total: progress.tick(cid, done, total)
        )
    if name == "calculate_pcaf":
        return calculate_pcaf(session, cid)
    if name == "get_industry_distribution":
        scope = int(args.get("scope", 1))
        return get_industry_distribution(session, company.industry_code, scope) or {}
    if name == "notify_owner":
        return {"ack": True, "message": args.get("message", "")}
    if name == "check_anomalies":
        return _check_anomalies(session, company)
    if name == "inspect_vouchers":
        return _inspect_vouchers(session, company, int(args.get("month", 0)), args.get("fuel", ""))
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

    if name == "check_anomalies":
        outliers = result.get("outliers", [])
        if outliers:
            o = outliers[0]
            msg = f"{o['month']}월 {o['fuel']} 배출량이 업종 월중앙값의 {o['ratio']}배 — 이상치 의심"
        else:
            msg = "월별 배출량 모두 업종 정상 범위 — 이상치 없음"
        return msg, {"outliers": outliers}

    if name == "inspect_vouchers":
        vs = result.get("vouchers", [])
        items = " / ".join(v["item"] for v in vs) if vs else "(해당 전표 없음)"
        return f"{args.get('month')}월 {args.get('fuel')} 전표 재파싱: '{items}' 확인", {"vouchers": vs}

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
    if name in ("check_anomalies", "inspect_vouchers"):
        return result  # {outliers} / {vouchers} — 작음, 그대로 회신
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
        types.FunctionDeclaration(name="check_anomalies", description="월별 배출량을 업종 평균과 비교해 이상치(과다 배출) 월·연료를 반환한다. 분류·계산 후 호출."),
        types.FunctionDeclaration(
            name="inspect_vouchers",
            description="특정 월·연료의 전표 품목명을 반환한다(이상치 재검증용 재파싱).",
            parameters_json_schema={"type": "object", "properties": {"month": {"type": "integer"}, "fuel": {"type": "string", "description": "예: 경유"}}, "required": ["month", "fuel"]},
        ),
    ])
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    client = genai.Client(api_key=api_key)

    def _generate(contents):
        # Gemini 무료 티어는 간헐적 5xx/과부하가 있어 짧게 재시도 (마지막 실패는 폴백으로).
        last = None
        for attempt in range(3):
            try:
                return client.models.generate_content(model=MODEL, contents=contents, config=config)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise last

    log_step(session, company.id, sid, "계획", _OPENER)
    contents = [types.Content(role="user", parts=[types.Part(text=f"기업 '{company.name}'의 탄소 리포트를 만들어라.")])]

    for _ in range(MAX_ITERS):
        resp = _generate(contents)
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
    gas_gap = next((g for g in collect.get("gaps", []) if g["fuel"] == "가스"), None)
    if gas_gap:
        months = "·".join(str(m) for m in gas_gap["missing_months"])
        _run_tool_and_log(session, company, sid, "notify_owner",
                          {"message": f"{months}월 가스 고지서 미연동 확인 필요 — 연동 시 등급 상향 가능"})

    _run_tool_and_log(session, company, sid, "classify_vouchers", {})
    _run_tool_and_log(session, company, sid, "get_industry_distribution", {"scope": 1})

    # 이상치 자가 검증
    anom = _run_tool_and_log(session, company, sid, "check_anomalies", {})
    for o in anom.get("outliers", [])[:1]:
        insp = _run_tool_and_log(session, company, sid, "inspect_vouchers",
                                 {"month": o["month"], "fuel": o["fuel"]})
        items = " / ".join(v["item"] for v in insp.get("vouchers", []))
        if any(k in items for k in ("증차", "증설")):
            log_step(session, cid, sid, "관찰",
                     f"'{items}' — 일회성 설비 증가로 확인, 오분류 아님 → 정상 판정 + 주석 추가")
        else:
            _run_tool_and_log(session, company, sid, "notify_owner",
                              {"message": f"{o['month']}월 {o['fuel']} 이상치({o['ratio']}배) 사유 불명 — 사장 검토 요청"})

    _run_tool_and_log(session, company, sid, "calculate_pcaf", {})
    log_step(session, cid, sid, "계획", "리포트 생성 완료 → 부족 데이터는 사장 연동 요청 목록에 반영")


def run_agent(session: Session, company_id: int) -> dict:
    """오케스트레이터 실행. LLM 루프 → 실패 시 결정론적 폴백. 트레이스는 어느 쪽이든 기록."""
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company_id={company_id} 없음")

    from db.models import TraceLog  # 지역 import — 순환 회피

    sid = new_session_id()
    mode = "llm"
    try:
        _run_llm(session, company, sid)
    except Exception as exc:  # noqa: BLE001 — 무키·API오류·SDK드리프트 모두 폴백
        from sqlalchemy import delete, select
        session.rollback()
        # LLM이 중간까지 남긴 부분 트레이스·분류를 정리해 폴백을 깨끗한 단일 세션으로 재실행
        session.query(TraceLog).filter_by(session_id=sid).delete()
        vids = [r[0] for r in session.execute(select(Voucher.id).where(Voucher.company_id == company_id))]
        if vids:
            session.execute(delete(Classification).where(Classification.voucher_id.in_(vids)))
        session.commit()
        mode = "fallback"
        log_step(session, company_id, sid, "계획",
                 f"라이브 에이전트 사용 불가({type(exc).__name__}) — 동작 설계 시각화(폴백)로 진행")
        _run_sequential(session, company, sid)

    count = session.query(TraceLog).filter_by(session_id=sid).count()
    return {"session_id": sid, "mode": mode, "step_count": count}
