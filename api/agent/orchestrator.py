"""오케스트레이터 — 도구 4종 위에 얹은 에이전트 루프 (킬러씬 A).

"이 기업의 탄소 리포트를 만들어라"는 목표를 받아 실행한다. 순서가 뻔한 단계
(수집→결손검사→알림→분류→계산→벤치마킹)는 결정론적 코드로 즉시 처리하고,
**진짜 판단이 필요한 지점 — 이상치가 정상인지 여부 — 에서만 Gemini를 부른다.**
LLM 산수 금지 원칙과 동일한 결로: "애매한 것만 모델에게, 나머지는 코드로."

전 단계를 [계획]/[관찰]/[행동]으로 trace_logs에 기록한다(장면② 데이터 소스).
GEMINI_API_KEY 가 없거나 이상치 판단 호출이 실패하면, 규칙 기반 판정
(품목 문구에 '증차'/'설비' 등 포함 여부)으로 대체해 항상 리포트가 끝까지 완료된다.
"""
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

_OPENER = "2024년 12개월 전표 분석 시작 → 결손 검사를 먼저 수행"

_ANOMALY_JUDGE_PROMPT = """너는 중소기업 전표를 검토하는 회계 보조 AI다.
아래 전표 품목명들을 보고, 이 달의 배출량이 업종 평균보다 훨씬 높은 것이
정당한 사유(예: 설비 증차·증설, 생산량 일시 증가 등)로 설명되는지 판단하라.

전표 품목: {items}

정당한 사유가 문구에 명시되어 있으면 "정상"과 그 사유 한 줄을,
사유가 불명확하면 "불명"만 답하라. 다른 말은 하지 마라.
형식: 정상|사유 또는 불명"""

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


# ── 도구 실행부 ────────────────────────────────────────────────────────────
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


# ── 공용 스텝 실행: 도구 호출 → 트레이스 기록 ─────────────────────────────
def _run_tool_and_log(session, company, sid, name, args) -> dict:
    result = _execute(name, args, session, company)
    step_type, tool_name = _TOOL_META[name]
    message, detail = _summarize(name, args, result)
    log_step(session, company.id, sid, step_type, message, tool_name=tool_name, detail=detail)
    return result


# ── 이상치 판단 — 여기서만 Gemini를 부른다 (진짜 애매한 지점) ────────────────
def _judge_anomaly_with_llm(items: str) -> tuple[bool, str] | None:
    """전표 문구를 보고 이상치가 정상 사유인지 LLM에게 짧게 묻는다.

    반환: (정상 여부, 사유) 또는 실패 시 None(호출부가 규칙 기반으로 대체).
    산수·집계는 절대 여기서 하지 않는다 — check_anomalies 가 이미 결정론적으로
    계산한 배수를 근거로, "이 문구가 그 배수를 설명하는가"만 판단시킨다.
    """
    import os

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=MODEL,
            contents=_ANOMALY_JUDGE_PROMPT.format(items=items),
        )
        text = (resp.text or "").strip()
        if text.startswith("정상"):
            reason = text.split("|", 1)[1].strip() if "|" in text else "정당한 사유 확인"
            return True, reason
        return False, ""
    except Exception:  # noqa: BLE001 — 실패 시 규칙 기반으로 조용히 대체
        return None


def _judge_anomaly_rule_based(items: str) -> tuple[bool, str]:
    """LLM 미가용 시 대체 — 문구 키워드 매칭(결정론적, 항상 완료 보장)."""
    if any(k in items for k in ("증차", "증설", "신규", "확장")):
        return True, "설비 증가 관련 문구 확인(규칙 기반 판정)"
    return False, ""


# ── 메인 실행 경로: 뻔한 단계는 코드, 이상치 판단만 LLM ──────────────────────
def _run_agent_core(session: Session, company: Company, sid: str, judge_mode: str) -> None:
    cid = company.id
    log_step(session, cid, sid, "계획", _OPENER)

    collect = _run_tool_and_log(session, company, sid, "collect_vouchers", {})
    gaps = collect.get("coverage", {}).get("gaps", [])
    gas_gap = next((g for g in gaps if g["fuel"] == "가스"), None)
    if gas_gap:
        months = "·".join(str(m) for m in gas_gap["missing_months"])
        _run_tool_and_log(session, company, sid, "notify_owner",
                          {"message": f"{months}월 가스 고지서 미연동 확인 필요 — 연동 시 등급 상향 가능"})

    _run_tool_and_log(session, company, sid, "classify_vouchers", {})
    _run_tool_and_log(session, company, sid, "get_industry_distribution", {"scope": 1})

    # 이상치 자가 검증 — 배수 계산은 코드(_check_anomalies), "정상인지" 판단만 모델
    anom = _run_tool_and_log(session, company, sid, "check_anomalies", {})
    for o in anom.get("outliers", [])[:1]:
        insp = _run_tool_and_log(session, company, sid, "inspect_vouchers",
                                 {"month": o["month"], "fuel": o["fuel"]})
        items = " / ".join(v["item"] for v in insp.get("vouchers", []))

        judged = _judge_anomaly_with_llm(items) if judge_mode == "llm" else None
        if judged is None:
            is_normal, reason = _judge_anomaly_rule_based(items)
            judge_note = "규칙 기반"
        else:
            is_normal, reason = judged
            judge_note = "AI 판단"

        if is_normal:
            log_step(session, cid, sid, "관찰",
                     f"'{items}' — {reason} → 오분류 아님, 정상 판정 + 주석 추가 ({judge_note})")
        else:
            _run_tool_and_log(session, company, sid, "notify_owner",
                              {"message": f"{o['month']}월 {o['fuel']} 이상치({o['ratio']}배) 사유 불명 — 사장 검토 요청"})

    _run_tool_and_log(session, company, sid, "calculate_pcaf", {})
    log_step(session, cid, sid, "계획", "리포트 생성 완료 → 부족 데이터는 사장 연동 요청 목록에 반영")


def run_agent(session: Session, company_id: int) -> dict:
    """오케스트레이터 실행.

    뻔한 단계(수집·알림·분류·계산·벤치마킹)는 항상 코드로 즉시 실행하고,
    이상치가 실제로 발견됐을 때만 그 지점에서 LLM 판단을 1회 시도한다.
    GEMINI_API_KEY 가 없거나 판단 호출이 실패해도 규칙 기반으로 대체되어
    리포트는 항상 끝까지 완료된다 — "폴백으로 전체를 다시 도는" 구조가 아니다.
    """
    import os

    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company_id={company_id} 없음")

    from db.models import TraceLog  # 지역 import — 순환 회피

    sid = new_session_id()
    judge_mode = "llm" if os.getenv("GEMINI_API_KEY") else "rule"
    _run_agent_core(session, company, sid, judge_mode)

    count = session.query(TraceLog).filter_by(session_id=sid).count()
    return {"session_id": sid, "mode": judge_mode, "step_count": count}
