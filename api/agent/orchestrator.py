"""오케스트레이터 — 도구 4종 위에 얹은 에이전트 루프 (킬러씬 A).

"이 기업의 탄소 리포트를 만들어라"는 목표를 받아 실행한다. 순서가 뻔한 단계
(수집→결손검사→알림→분류→계산→벤치마킹)는 결정론적 코드로 즉시 처리하고,
**진짜 판단이 필요한 지점 — 이상치가 정상인지 여부 — 에서만 Gemini를 부른다.**
LLM 산수 금지 원칙과 동일한 결로: "애매한 것만 모델에게, 나머지는 코드로."

전 단계를 [계획]/[관찰]/[행동]으로 trace_logs에 기록한다(장면② 데이터 소스).

실패 가시성 원칙: GEMINI_API_KEY 가 없거나 이상치 판단 호출이 실패하면
대체 판정 없이 **실패 자체를 트레이스에 기록**하고 해당 건을 사장 검토로
넘긴다 — 제대로 안 돌아가면 안 돌아가는 것이 화면에 그대로 보여야 한다.
"""
from statistics import median

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

_OPENER = "최근 1년 치 자료를 확인하고 있어요. 빠진 달이 있는지 먼저 살펴볼게요."

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

_ANOMALY_THRESHOLD = 2.5    # 월별 배출량이 같은 연료의 평월 중앙값의 N배↑면 이상치로 의심
_ANOMALY_PEER_FACTOR = 2.0  # + 다른 어떤 월보다도 N배↑ — 계절성(동절기 가스)은 비슷한 형제 월이 있어 걸러짐
_ANOMALY_MIN_MONTHS = 3     # 연료별 데이터가 이보다 적으면 평월 기준을 세울 수 없어 판단 보류


# ── 이상치 감지·재검증 (결정론 계산 — LLM 산수 금지 원칙 유지) ────────────────
def _check_anomalies(session: Session, company: Company) -> dict:
    """월×연료별 Scope1 배출량을 **같은 연료의 나머지 월(평월) 중앙값**과 비교.

    업종 연중앙값÷12 비교는 계절성(동절기 가스↑)을 이상치로 오검출한다.
    자기 평월 대비 배수는 단가·계수 스케일이 약분되어 데이터 갱신에도 안정적.
    """
    from sqlalchemy import func, select

    rows = session.execute(
        select(Voucher.month, Classification.fuel_type, func.sum(Classification.emission_co2e))
        .join(Classification, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company.id, Classification.scope == 1, Classification.emission_co2e > 0)
        .group_by(Voucher.month, Classification.fuel_type)
    ).all()
    by_fuel: dict[str, dict[int, float]] = {}
    for month, fuel, emission in rows:
        by_fuel.setdefault(fuel, {})[int(month)] = float(emission or 0)

    outliers = []
    for fuel, months in by_fuel.items():
        if len(months) < _ANOMALY_MIN_MONTHS:
            continue
        for month, emission in months.items():
            others = [v for m, v in months.items() if m != month]
            baseline = median(others)
            if not baseline:
                continue
            ratio = emission / baseline
            # 계절성 방어: 진짜 이상치는 다른 '모든' 월보다 확연히 크다.
            # 동절기 가스는 이웃 겨울 월(12↔1월)이 비슷해 peer 조건에서 걸러진다.
            if ratio >= _ANOMALY_THRESHOLD and emission >= _ANOMALY_PEER_FACTOR * max(others):
                outliers.append({"month": month, "fuel": fuel, "ratio": round(ratio, 1)})
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
        return get_industry_distribution(session, company.industry_code, scope, company.employee_count) or {}
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
        msg = f"자료 {result.get('count', 0)}건을 확인했어요."
        # get_coverage()가 실제로 계산한 gaps를 연료 무관하게 그대로 읽는다 — 특정
        # 연료(과거엔 "가스"만)를 하드코딩하면 다른 연료 결손은 트레이스에 조용히
        # 묻힌다. 여러 연료가 동시에 비면 첫 번째를 대표로 문장에 넣고 개수만 덧붙인다.
        if gaps:
            g = gaps[0]
            months = "·".join(str(m) for m in g["missing_months"])
            msg += f" 그런데 {months}월 {g['fuel']} 자료가 비어있네요. 이런 업종에서는 흔치 않은 경우예요."
            if len(gaps) > 1:
                msg += f" 이 외에 {len(gaps) - 1}개 연료도 더 비어있어요."
        return msg, cov

    if name == "classify_vouchers":
        processed = result.get("processed", 0)
        review = result.get("review_required", 0)
        msg = f"자료 {processed}건을 종류별로 정리했어요."
        if review:
            msg += f" 이 중 {review}건은 AI가 확신하지 못해서 제가 직접 확인해볼게요."
        return msg, result

    if name == "calculate_pcaf":
        before, after, bench = result.get("before"), result.get("after"), result.get("benchmark") or {}
        if after:
            msg = (
                f"매출액만 봤을 때는 {before['grade']}등급이었는데, 실제 자료로 다시 계산해보니 "
                f"{after['grade']}등급이 나왔어요(총 {after['total']}톤 CO2)."
            )
            if bench.get("percentile_text"):
                msg += f" {bench['percentile_text']}예요."
        else:
            msg = f"아직 분류된 자료가 없어서 매출액 기준으로만 {before['grade']}등급을 매겼어요."
        return msg, {"before": before, "after": after, "benchmark": bench}

    if name == "get_industry_distribution":
        if result:
            msg = (
                f"같은 업종 다른 회사들과 비교해봤어요. 보통 {result.get('median')}톤 정도 "
                f"배출하시더라고요(적게는 {result.get('min')}톤, 많게는 {result.get('max')}톤)."
            )
        else:
            msg = "비교할 동종 업종 자료가 아직 없어요."
        return msg, result or None

    if name == "notify_owner":
        return args.get("message", ""), None

    if name == "check_anomalies":
        outliers = result.get("outliers", [])
        if outliers:
            o = outliers[0]
            msg = f"{o['month']}월 {o['fuel']} 사용량이 평소보다 {o['ratio']}배나 많아요. 왜 그런지 다시 확인해볼게요."
        else:
            msg = "달마다 사용량을 비교해봤는데 특별히 이상한 달은 없었어요."
        return msg, {"outliers": outliers}

    if name == "inspect_vouchers":
        vs = result.get("vouchers", [])
        items = " / ".join(v["item"] for v in vs) if vs else "해당 자료 없음"
        return f"{args.get('month')}월 자료를 다시 열어봤어요. '{items}'라고 적혀있네요.", {"vouchers": vs}

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

    반환: (정상 여부, 사유) 또는 실패 시 None.
    실패 시 대체 판정은 없다 — 호출부가 실패를 트레이스에 기록하고 사장 검토로
    넘긴다(실패 가시성 원칙). 산수·집계는 절대 여기서 하지 않는다 —
    check_anomalies 가 이미 결정론적으로 계산한 배수를 근거로,
    "이 문구가 그 배수를 설명하는가"만 판단시킨다.
    """
    import os

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=10_000),  # ms — 행 걸림은 빠르게 실패로
        )
        resp = client.models.generate_content(
            model=MODEL,
            contents=_ANOMALY_JUDGE_PROMPT.format(items=items),
        )
        text = (resp.text or "").strip()
        if text.startswith("정상"):
            reason = text.split("|", 1)[1].strip() if "|" in text else "정당한 사유 확인"
            return True, reason
        return False, ""
    except Exception:  # noqa: BLE001 — 실패는 None으로 반환, 호출부가 트레이스에 노출
        return None


def _annotate_classifications(session: Session, company_id: int, month: int, fuel: str, note: str) -> None:
    """이상치 재검증 결과를 해당 월·연료 분류 행의 evidence에 주석으로 남긴다.

    트레이스의 "정상 판정 + 주석 추가"가 말뿐이 아니라 실제 데이터(장면③의
    evidence 펼침)에 반영되도록 — 전 판단 evidence 저장 원칙(CLAUDE.md §5-5).
    """
    from sqlalchemy import select

    rows = session.execute(
        select(Classification)
        .join(Voucher, Voucher.id == Classification.voucher_id)
        .where(Voucher.company_id == company_id, Voucher.month == month,
               Classification.fuel_type == fuel)
    ).scalars().all()
    for c in rows:
        c.evidence = f"{c.evidence or ''} | 이상치 재검증: {note}".strip(" |")
    session.commit()


def _mark_anomaly_pending(session: Session, company_id: int, month: int, fuel: str, ratio: float) -> None:
    """이상치 되묻기(docs/tasks.md) — 해당 월·연료 분류 행 전부를
    anomaly_check_status='pending'으로 표시해 사장님 확인 대기열에 올린다.

    LLM이 "정상"으로 자동 판단한 케이스도 사람 확인 없이 바로 confirmed로
    넘기지 않는다 — 에이전트의 1차 판단이지 최종 확인이 아니기 때문에,
    사장님이 한 번은 "네/아니오/모르겠어요"로 답해야 anomaly_check_status가
    pending 밖으로 나간다(api/routers/owner.py::supplement_anomaly_check).
    """
    from sqlalchemy import select

    rows = session.execute(
        select(Classification)
        .join(Voucher, Voucher.id == Classification.voucher_id)
        .where(Voucher.company_id == company_id, Voucher.month == month,
               Classification.fuel_type == fuel)
    ).scalars().all()
    for c in rows:
        c.anomaly_check_status = "pending"
        c.anomaly_ratio = ratio
    session.commit()


# ── 메인 실행 경로: 뻔한 단계는 코드, 이상치 판단만 LLM ──────────────────────
def _run_agent_core(session: Session, company: Company, sid: str) -> int:
    """전 단계 실행. 반환: LLM 판단 실패 건수(실패 가시성 — mode 산정용)."""
    cid = company.id
    judge_failures = 0
    log_step(session, cid, sid, "계획", _OPENER)

    collect = _run_tool_and_log(session, company, sid, "collect_vouchers", {})
    gaps = collect.get("coverage", {}).get("gaps", [])
    # 특정 연료로 좁히지 않고 get_coverage()가 찾은 결손 전부를 사장에게 알린다 —
    # 시나리오(가스만 비는 데모)가 아니라 실제 업로드 데이터가 말해주는 대로.
    for gap in gaps:
        months = "·".join(str(m) for m in gap["missing_months"])
        _run_tool_and_log(session, company, sid, "notify_owner",
                          {"message": f"{months}월 {gap['fuel']} 고지서가 아직 연동 안 됐어요. 연동하시면 등급이 올라갈 수도 있어요."})

    _run_tool_and_log(session, company, sid, "classify_vouchers", {})
    _run_tool_and_log(session, company, sid, "get_industry_distribution", {"scope": 1})

    # 이상치 자가 검증 — 배수 계산은 코드(_check_anomalies), "정상인지" 판단만 모델.
    # 이상치 되묻기(docs/tasks.md): 세 경우(판단 실패/정상/비정상) 모두 최종 확인은
    # 사장님 몫이라 anomaly_check_status='pending'으로 남긴다 — LLM이 "정상"으로
    # 판단해도 evidence 주석은 참고용일 뿐, 사장님이 "네/아니오/모르겠어요"로
    # 답하기 전까지는 pending 상태를 유지한다.
    anom = _run_tool_and_log(session, company, sid, "check_anomalies", {})
    for o in anom.get("outliers", [])[:1]:
        insp = _run_tool_and_log(session, company, sid, "inspect_vouchers",
                                 {"month": o["month"], "fuel": o["fuel"]})
        items = " / ".join(v["item"] for v in insp.get("vouchers", []))

        judged = _judge_anomaly_with_llm(items)
        _mark_anomaly_pending(session, cid, o["month"], o["fuel"], o["ratio"])
        if judged is None:
            # 실패를 숨기지 않는다 — 대체 판정 없이 실패 자체를 기록하고 사람에게
            judge_failures += 1
            log_step(session, cid, sid, "관찰",
                     "다시 확인하다가 막혔어요. 제가 판단하지 않고 사장님이 직접 봐주셨으면 해요.")
            _run_tool_and_log(session, company, sid, "notify_owner",
                              {"message": f"{o['month']}월 {o['fuel']} 사용량이 평소보다 {o['ratio']}배 많은데, 제가 이유를 못 찾았어요. 한 번 확인해주시겠어요?"})
        elif judged[0]:
            reason = judged[1]
            log_step(session, cid, sid, "관찰",
                     f"'{items}' 자료를 보니 {reason}. 정상적인 사용 같아 보이는데, 사장님께도 확인 부탁드릴게요.")
            _annotate_classifications(session, cid, o["month"], o["fuel"],
                                      f"평월 대비 {o['ratio']}배지만 {reason}. AI 1차 판정: 정상(사장님 확인 대기).")
            _run_tool_and_log(session, company, sid, "notify_owner",
                              {"message": f"{o['month']}월 {o['fuel']} 사용량이 평소보다 {o['ratio']}배 많은데, {reason} 때문인 것 같아요. 맞는지 확인해주시겠어요?"})
        else:
            _run_tool_and_log(session, company, sid, "notify_owner",
                              {"message": f"{o['month']}월 {o['fuel']} 사용량이 평소보다 {o['ratio']}배 많은데, 이유를 특별히 찾지 못했어요. 확인 한번 부탁드려요."})

    _run_tool_and_log(session, company, sid, "calculate_pcaf", {})
    log_step(session, cid, sid, "계획", "확인이 끝났어요. 결과는 리포트로 정리했고, 빠진 자료는 요청 목록에 담아뒀어요.")
    return judge_failures


def run_agent(session: Session, company_id: int) -> dict:
    """오케스트레이터 실행.

    뻔한 단계(수집·알림·분류·계산·벤치마킹)는 항상 코드로 즉시 실행하고,
    이상치가 실제로 발견됐을 때만 그 지점에서 LLM 판단을 1회 시도한다.
    판단 실패 시 대체 판정 없이 실패가 트레이스에 기록된다(실패 가시성 원칙).
    반환 mode: "llm"(판단 전부 정상) | "judge_failed"(판단 실패 발생).
    실행 자체가 죽으면 "실행 중단" 스텝을 남기고 예외를 그대로 올린다.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"company_id={company_id} 없음")

    from db.models import TraceLog  # 지역 import — 순환 회피

    sid = new_session_id()
    try:
        judge_failures = _run_agent_core(session, company, sid)
    except Exception as e:
        # 반쪽 트레이스를 '진행 중'처럼 남기지 않는다 — 중단 사실을 기록 후 재전파
        session.rollback()
        try:
            log_step(session, company_id, sid, "관찰",
                     "지금 문제가 생겨서 확인을 끝내지 못했어요. 잠시 후 다시 시도해주세요.",
                     detail={"error_type": type(e).__name__})
        except Exception:  # noqa: BLE001 — 기록 실패(DB 장애 등)가 원인 예외를 가리면 안 됨
            pass
        raise

    count = session.query(TraceLog).filter_by(session_id=sid).count()
    mode = "judge_failed" if judge_failures else "llm"
    return {"session_id": sid, "mode": mode, "step_count": count}
