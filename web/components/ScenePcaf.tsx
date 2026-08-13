"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, getCompanyId } from "@/lib/api";
import type { AlertItem } from "@/lib/admin-types";

/** 장면 ⑤ — PCAF 정식 엔진(db/pcaf_quality.py) 리포트. GET /owner/{id}/quality-report
 *  실데이터만 사용. API 실패 시 목업으로 위장하지 않고 에러 배너 + 재시도를 표시한다
 *  (실패 가시성). 월별 배출 추이만 예외로 구 엔진(/pcaf/{id})의 monthly를 그대로
 *  재사용한다 — Classification 원자료를 월별로 집계하는 독립 로직이라 엔진 교체와
 *  무관하다. */

type ScopeQuality = {
  scope_group: "scope_1" | "scope_2";
  emission_tco2e: number | null;
  candidate_score: number | null;
  option_code: string | null;
  activity_data_basis: string | null;
  completeness_pct: number | null;
  basis: string[];
  limitations: string[];
  status: string;
  version: number;
  bank_review_required: boolean;
};
type Benchmark = {
  industry_code: string;
  industry_name: string | null;
  percentile_text: string | null;
  hint: string | null;
  value: number | null;
  min: number | null;
  median: number | null;
  max: number | null;
  percentile_pct: number | null;
};
type QualityReportResponse = {
  reporting_year: number;
  scope_1: ScopeQuality;
  scope_2: ScopeQuality;
  benchmark: Benchmark;
};

// 월별 배출 추이 전용 — 구 엔진(/pcaf/{id})의 after.monthly만 재사용(위 주석 참고).
type MonthlyRow = { month: number; total_tco2e: number; by_fuel: Record<string, number> };
type LegacyPcafResponse = { after: { monthly: MonthlyRow[] } | null };

// GET /owner/{company_id}/rate-candidate — db/pcaf.py::upgrade_candidate_for_company와
// 은행 쪽 GET /admin/rate-candidates가 같은 판정 로직을 공유한다(중복 없음).
type RateCandidate = {
  company_id: number;
  company_name: string;
  current_grade: number;
  target_grade: number;
  missing: string;
  benefit: string;
};
type RateCandidateResponse = { candidate: RateCandidate | null; disclaimer_text: string };

// POST /owner/{company_id}/rate-requests 응답 — 여신 결정이 아니다(CLAUDE.md §9).
// 관리자 승인요청 큐(GET /admin/rate-requests)로 넘어가 담당자가 "안내 대상 확인"만 한다.
type RateRequestResponse = {
  id: number;
  status: "pending" | "approved" | "rejected";
  disclaimer_text: string;
};

const fmt = (n: number) => n.toFixed(1);

// PCAF 품질점수는 1(최정확)~5(최부정확)의 순서형 데이터라, 배출량 수치 크기가 아니라
// "5칸 중 어디에 있는지"를 직접 그린다. 정식 엔진은 Scope별 단일 값만 주므로(구
// 엔진의 "매출추정 → 실측" before/after 개념 없음) 애니메이션은 마운트 시 0에서
// 실제 위치로 슬라이드하는 것만 남긴다.
const GRADE_TICKS = [5, 4, 3, 2, 1] as const;
const posOfGrade = (g: number) => ((5 - g) / 4) * 100;

function ScoreMarker({ score }: { score: number }) {
  const pct = posOfGrade(score);
  const [animPct, setAnimPct] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimPct(pct));
    return () => cancelAnimationFrame(id);
  }, [pct]);

  return (
    <div>
      <div className="relative mt-3 h-2 rounded-full bg-bg">
        <div className="absolute inset-0 flex items-center justify-between">
          {GRADE_TICKS.map((g) => (
            <span key={g} className="h-2.5 w-2.5 rounded-full bg-line" />
          ))}
        </div>
        <div
          className="absolute -top-1 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-white bg-brand shadow transition-[left] duration-700 ease-out"
          style={{ left: `${animPct}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] font-semibold text-faint">
        {GRADE_TICKS.map((g) => (
          <span key={g}>{g}등급</span>
        ))}
      </div>
    </div>
  );
}

const SCOPE_LABEL: Record<string, string> = { scope_1: "Scope 1", scope_2: "Scope 2" };

// Scope별 카드 — 품질점수 사다리 + 배출량 + 데이터 완전성을 담는다. 판정 근거
// 원문(basis/limitations, PCAF 옵션코드·Table 10.1-2 인용문)은 은행 담당자용
// 감사 근거 문장이라 사장님 화면엔 아예 안 보여준다 — API 응답엔 그대로 남아있어
// 나중에 관리자 화면에서 쓸 수 있다.
function ScopeQualitySection({ data }: { data: ScopeQuality }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-semibold text-ink">{SCOPE_LABEL[data.scope_group]}</span>
        {data.candidate_score != null && (
          <span className="rounded-full bg-brand px-2.5 py-1 text-[13px] font-extrabold text-white">
            {data.candidate_score}등급
          </span>
        )}
      </div>

      {data.candidate_score != null ? (
        <>
          <ScoreMarker score={data.candidate_score} />

          <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-[11.5px] text-muted">
            <span>배출량</span>
            <span className="font-semibold text-ink">
              {data.emission_tco2e != null ? `${fmt(data.emission_tco2e)}tCO₂e` : "미산정"}
            </span>
          </div>
        </>
      ) : (
        <div className="mt-3 rounded-xl border-2 border-dashed border-line p-4 text-center text-[12.5px] text-muted">
          {data.limitations[0] ?? "아직 산정할 수 없어요"}
        </div>
      )}
    </div>
  );
}

// 연료 대분류(db/pcaf.py::_fuel_bucket과 동일 어휘) → 막대 색. scope1/scope2는
// 이미 "직접배출(연소)/간접배출(전기)" 의미로 쓰이는 색을 그대로 재사용하고,
// 경유/유류만 3번째 색(lime)을 새로 씀 — 하나의 색을 두 버킷이 나눠 쓰면
// 스택 막대에서 구분이 안 된다.
const FUEL_BAR_COLOR: Record<string, string> = {
  전기: "bg-scope2",
  가스: "bg-scope1",
  "경유/유류": "bg-lime",
  기타: "bg-faint",
};
const FUEL_ORDER = ["전기", "가스", "경유/유류", "기타"];
const CHART_HEIGHT_PX = 96;

// 점들을 부드러운 곡선으로 잇는 SVG path — 각 구간을 다음 점과의 중점까지
// 2차 베지어(Q)로 그리고, 마지막만 실제 마지막 점까지 부드럽게 이어지도록(T)
// 마무리한다. 외부 차트 라이브러리 없이 표준적인 "점 중점 스무딩" 기법.
function smoothLinePath(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0].x},${pts[0].y} L ${pts[0].x},${pts[0].y}`;
  let d = `M ${pts[0].x},${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const curr = pts[i];
    const next = pts[i + 1];
    const midX = (curr.x + next.x) / 2;
    const midY = (curr.y + next.y) / 2;
    d += ` Q ${curr.x},${curr.y} ${midX},${midY}`;
  }
  const last = pts[pts.length - 1];
  d += ` T ${last.x},${last.y}`;
  return d;
}

function MonthlyTrendChart({ monthly }: { monthly: MonthlyRow[] }) {
  const maxTotal = Math.max(...monthly.map((m) => m.total_tco2e), 0.001);
  const fuelsPresent = new Set(monthly.flatMap((m) => Object.keys(m.by_fuel)));
  const fuels = FUEL_ORDER.filter((f) => fuelsPresent.has(f));

  // 막대 맨 위 중앙 좌표 — 꺾은선 오버레이용. x는 컨테이너 폭 대비 %(반응형 폭에
  // 맞춰 자동으로 따라감), y는 CHART_HEIGHT_PX 기준 고정 px(컨테이너 높이가
  // 고정값이라 DOM 측정 없이 계산 가능).
  const points = monthly.map((m, i) => {
    const barHeight = Math.max(2, Math.round((m.total_tco2e / maxTotal) * CHART_HEIGHT_PX));
    return { x: ((i + 0.5) / monthly.length) * 100, y: CHART_HEIGHT_PX - barHeight, barHeight };
  });

  const linePath = smoothLinePath(points);

  return (
    <div className="mt-3 rounded-2xl bg-surface p-5">
      <div className="text-[13px] font-semibold text-ink">월별 배출 추이</div>

      <div
        className="relative mt-4 flex items-end justify-between gap-1"
        style={{ height: CHART_HEIGHT_PX }}
      >
        {monthly.map((m, i) => (
          <div key={m.month} className="flex flex-1 flex-col items-center justify-end">
            <div
              className="flex w-full flex-col-reverse overflow-hidden rounded-[3px] bg-line"
              style={{ height: points[i].barHeight }}
            >
              {fuels.map((f) => {
                const v = m.by_fuel[f] || 0;
                if (v <= 0) return null;
                return <div key={f} className={FUEL_BAR_COLOR[f]} style={{ flexGrow: v }} />;
              })}
            </div>
          </div>
        ))}

        {/* 꺾은선 오버레이 — 부드러운 곡선으로 막대 맨 위를 이어 총량 추이를
            한눈에 보여준다. */}
        <svg
          className="pointer-events-none absolute left-0 top-0 block"
          style={{ width: "100%", height: "100%" }}
          preserveAspectRatio="none"
          viewBox={`0 0 100 ${CHART_HEIGHT_PX}`}
        >
          <path
            d={linePath}
            fill="none"
            stroke="var(--color-brand)"
            strokeWidth={1.75}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div className="mt-1 flex justify-between text-[9px] text-faint">
        {monthly.map((m) => (
          <span key={m.month} className="flex-1 text-center">
            {m.month}
          </span>
        ))}
      </div>

      {fuels.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-line pt-3 text-[10.5px] text-muted">
          {fuels.map((f) => (
            <span key={f} className="flex items-center gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${FUEL_BAR_COLOR[f]}`} /> {f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function DistributionTrack({
  min,
  max,
  value,
}: {
  min: number;
  max: number;
  value: number;
}) {
  const span = Math.max(max - min, 0.001);
  // 배출량이 적을수록 "상위" → 트랙은 진한(상위) → 연한(하위) 순으로 좌에서 우로 흐름
  const valuePct = Math.min(100, Math.max(0, ((value - min) / span) * 100));

  const [animatedPct, setAnimatedPct] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimatedPct(valuePct));
    return () => cancelAnimationFrame(id);
  }, [valuePct]);

  return (
    <div className="mt-3">
      <div
        className="relative h-2 rounded-full"
        style={{
          background:
            "linear-gradient(90deg, var(--color-brand) 0%, var(--color-brand-soft) 100%)",
        }}
      >
        <div
          className="absolute -top-[7px] -translate-x-1/2 transition-[left] duration-700 ease-out"
          style={{ left: `${animatedPct}%` }}
        >
          <svg width="12" height="8" viewBox="0 0 12 8" fill="none">
            <path d="M6 8L0.5 0H11.5L6 8Z" fill="var(--color-ink)" />
          </svg>
        </div>
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[11px] font-semibold text-faint">
        <span>상위</span>
        <span>하위</span>
      </div>
    </div>
  );
}

function BenchmarkCard({
  benchmark,
  hasDistribution,
}: {
  benchmark: Benchmark;
  hasDistribution: boolean;
}) {
  return (
    <div className="flex-1 rounded-2xl bg-surface p-4">
      {hasDistribution ? (
        <>
          <p className="truncate text-[13px] font-semibold text-ink">
            동종 {benchmark.industry_name ?? benchmark.industry_code} 대비
          </p>
          <p className="mt-0.5 text-[14px] font-bold text-ink">
            상위 <span className="text-brand-ink">{benchmark.percentile_pct}%</span>
          </p>
          <DistributionTrack min={benchmark.min!} max={benchmark.max!} value={benchmark.value!} />
        </>
      ) : (
        <>
          <div className="text-[13px] font-semibold text-ink">동종 업종 벤치마킹</div>
          <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">
            분류 실행 후 산출돼요.
          </p>
        </>
      )}
    </div>
  );
}

// 데이터 완전성을 막대 대신 원형 게이지로 — 채워진 비율이 링 형태로 한눈에
// "확" 들어오게 한다. 마운트 시 0%에서 실제 값까지 슬라이드.
const RING_SIZE = 64;
const RING_STROKE = 6;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function CompletenessRing({ label, pct }: { label: string; pct: number }) {
  const [animPct, setAnimPct] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimPct(pct));
    return () => cancelAnimationFrame(id);
  }, [pct]);
  const offset = RING_CIRCUMFERENCE * (1 - animPct / 100);

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: RING_SIZE, height: RING_SIZE }}>
        <svg width={RING_SIZE} height={RING_SIZE} className="-rotate-90">
          <circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RING_RADIUS}
            fill="none"
            stroke="var(--color-line)"
            strokeWidth={RING_STROKE}
          />
          <circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RING_RADIUS}
            fill="none"
            stroke="var(--color-brand)"
            strokeWidth={RING_STROKE}
            strokeLinecap="round"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={offset}
            className="transition-[stroke-dashoffset] duration-700 ease-out"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center text-[12.5px] font-extrabold text-ink">
          {Math.round(pct)}%
        </div>
      </div>
      <span className="text-[10.5px] font-semibold text-muted">{label}</span>
    </div>
  );
}

function CompletenessCard({ scope1, scope2 }: { scope1: ScopeQuality; scope2: ScopeQuality }) {
  return (
    <div className="flex-1 rounded-2xl bg-surface p-4">
      <div className="text-[13px] font-semibold text-ink">데이터 완전성</div>
      <div className="mt-3 flex items-center justify-around">
        {scope1.completeness_pct != null && (
          <CompletenessRing label="Scope1" pct={scope1.completeness_pct} />
        )}
        {scope2.completeness_pct != null && (
          <CompletenessRing label="Scope2" pct={scope2.completeness_pct} />
        )}
      </div>
    </div>
  );
}

export function ScenePcaf() {
  const [data, setData] = useState<QualityReportResponse | null>(null);
  const [monthly, setMonthly] = useState<MonthlyRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [rateCandidate, setRateCandidate] = useState<RateCandidateResponse | null>(null);
  const [rateRequest, setRateRequest] = useState<RateRequestResponse | null>(null);
  const [requestBusy, setRequestBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  async function submitRateRequest() {
    setRequestBusy(true);
    setRequestError(null);
    try {
      const cid = await getCompanyId();
      const res = await apiPost<RateRequestResponse>(`/owner/${cid}/rate-requests`, {
        request_type: "rate_upgrade",
      });
      setRateRequest(res);
    } catch (err) {
      console.error("우대금리 안내 요청 실패:", err);
      setRequestError("요청에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setRequestBusy(false);
    }
  }

  async function load() {
    setError(null);
    try {
      const cid = await getCompanyId();
      const res = await apiGet<QualityReportResponse>(`/owner/${cid}/quality-report`);
      setData(res);
      // 이상 신호는 은행 담당자와 동일한 판정 로직(GET /admin/alerts와 같은
      // db/alerts.py::detect_alerts)을 자기 기업분만 조회 — 은행이 먼저 알고
      // 사장은 모르는 구도를 만들지 않는다(CLAUDE.md §9).
      apiGet<{ alerts: AlertItem[] }>(`/owner/alerts/${cid}`)
        .then((r) => setAlerts(r.alerts))
        .catch((err) => console.error("이상 신호 조회 실패(부가 정보라 화면은 계속 진행):", err));
      // 등급 상승 후보 여부도 부가 정보 — 실패해도 리포트 본문은 그대로 보여준다.
      apiGet<RateCandidateResponse>(`/owner/${cid}/rate-candidate`)
        .then((r) => setRateCandidate(r))
        .catch((err) => console.error("우대금리 후보 조회 실패(부가 정보라 화면은 계속 진행):", err));
      // 월별 배출 추이만 구 엔진에서 재사용(파일 상단 주석 참고) — 부가 정보라
      // 실패해도 리포트 본문(Scope 품질 후보)은 그대로 보여준다.
      apiGet<LegacyPcafResponse>(`/pcaf/${cid}`)
        .then((r) => setMonthly(r.after?.monthly ?? null))
        .catch((err) => console.error("월별 추이 조회 실패(부가 정보라 화면은 계속 진행):", err));
    } catch (err) {
      // 목업으로 위장하지 않는다 — 실패는 실패로 표시
      console.error("PCAF 품질 조회 실패:", err);
      setData(null);
      setError("산정 결과를 불러오지 못했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (!data) {
    return (
      <section>
        <h2 className="text-[17px] font-bold leading-snug text-ink">
          측정 결과를 불러오는 중이에요
        </h2>
        {error ? (
          <>
            <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
              {error}
            </div>
            <button
              type="button"
              onClick={() => void load()}
              className="btn-cta mt-4 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
            >
              다시 시도
            </button>
          </>
        ) : (
          <p className="mt-1 flex items-center gap-2 text-[13px] leading-relaxed text-muted">
            잠시만 기다려 주세요…
            <span className="flex gap-1">
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand [animation-delay:-0.3s]" />
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand [animation-delay:-0.15s]" />
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand" />
            </span>
          </p>
        )}
      </section>
    );
  }

  const { scope_1, scope_2, benchmark } = data;
  const hasDistribution =
    benchmark.value !== null &&
    benchmark.min !== null &&
    benchmark.median !== null &&
    benchmark.max !== null;
  const bankReviewRequired = scope_1.bank_review_required || scope_2.bank_review_required;

  return (
    <section>
      <h2 className="text-[17px] font-bold leading-snug text-ink">
        측정이 끝났어요
      </h2>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {bankReviewRequired && (
          <span className="rounded-full bg-hitl/25 px-2 py-0.5 text-[10.5px] font-semibold text-hitl-ink">
            은행 검토 대기
          </span>
        )}
      </div>

      <div className="mt-3 flex gap-3">
        <div className="flex-1 rounded-2xl bg-surface p-4">
          <ScopeQualitySection data={scope_1} />
        </div>
        <div className="flex-1 rounded-2xl bg-surface p-4">
          <ScopeQualitySection data={scope_2} />
        </div>
      </div>

      <div className="mt-3 flex gap-3">
        <BenchmarkCard benchmark={benchmark} hasDistribution={hasDistribution} />
        <CompletenessCard scope1={scope_1} scope2={scope_2} />
      </div>

      {monthly && <MonthlyTrendChart monthly={monthly} />}

      {alerts.length > 0 && (
        <div className="mt-3 space-y-2 rounded-2xl bg-surface p-5">
          <div className="text-[13px] font-semibold text-ink">이상 신호 알림</div>
          <p className="text-[11.5px] leading-relaxed text-faint">
            은행 담당자에게도 같은 시점에 안내되는 신호예요. 여신 결정과는 무관하며,
            참고용 안내입니다.
          </p>
          {alerts.map((a) => (
            <div
              key={`${a.type}-${a.month}`}
              className="rounded-xl bg-bg px-3.5 py-2.5 text-[12.5px] leading-relaxed text-muted"
            >
              {a.message}
            </div>
          ))}
        </div>
      )}

      {rateCandidate?.candidate ? (
        <div className="mt-3 rounded-2xl bg-surface p-5">
          <div className="text-[13px] font-semibold text-ink">우대금리 대상 안내</div>
          <div className="mt-2 flex items-center gap-1.5 text-[12.5px] text-muted">
            <span className="rounded-full bg-line px-2 py-0.5 text-[11px] font-bold text-muted">
              {rateCandidate.candidate.current_grade}등급
            </span>
            <span className="text-faint">→</span>
            <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-bold text-white">
              {rateCandidate.candidate.target_grade}등급
            </span>
          </div>
          <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
            <span className="font-semibold text-ink">필요 데이터:</span>{" "}
            {rateCandidate.candidate.missing}
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-brand-ink">
            {rateCandidate.candidate.benefit}
          </p>
          <p className="mt-3 text-[11px] leading-relaxed text-faint">
            {rateCandidate.disclaimer_text}
          </p>

          {rateRequest ? (
            <div className="mt-3 rounded-xl bg-brand-soft px-3.5 py-2.5 text-center text-[12.5px] font-semibold text-brand-ink">
              요청됐어요. 담당 은행원이 확인 후 안내드려요
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={() => void submitRateRequest()}
                disabled={requestBusy}
                className="btn-cta mt-3 w-full rounded-2xl bg-brand py-3.5 text-[14px] font-bold text-white disabled:opacity-60"
              >
                {requestBusy ? "요청하는 중…" : "우대금리 안내 요청"}
              </button>
              {requestError && (
                <p className="mt-2 text-[11.5px] text-red-600">{requestError}</p>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="mt-3 rounded-2xl bg-surface p-5 text-center">
          <div className="text-[13px] font-semibold text-ink">
            우대금리 대상 안내
          </div>
          <p className="mt-1 text-[12.5px] text-muted">
            담당 은행원과의 상담을 통해 우대금리 자격을 확인할 수 있어요.
          </p>
        </div>
      )}
    </section>
  );
}
