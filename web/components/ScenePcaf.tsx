"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, getCompanyId } from "@/lib/api";
import type { AlertItem } from "@/lib/admin-types";

/** 장면 ④ — PCAF Before/After + 벤치마킹. /pcaf/{id} 실데이터만 사용.
 *  API 실패 시 목업으로 위장하지 않고 에러 배너 + 재시도를 표시한다(실패 가시성). */

type Before = {
  grade: number;
  scope1: number;
  scope2: number;
  emission_tco2e: number;
};
type After = {
  grade: number;
  scope1: number;
  scope2: number;
  total: number;
  measured_tco2e: number;
  estimated_gap_tco2e: number;
  hitl_count: number;
  gap_months: { fuel: string; missing_months: number[] }[];
  by_fuel: { fuel: string; measured_tco2e: number; estimated_tco2e: number; total_tco2e: number }[];
  monthly: { month: number; total_tco2e: number; by_fuel: Record<string, number> }[];
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
type PcafResponse = { before: Before; after: After | null; benchmark: Benchmark };

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

// PCAF 등급은 1(최정확)~5(최부정확)의 순서형 데이터라, 배출량 수치 크기가 아니라
// "5칸 중 어디에 있는지"를 직접 그려야 등급 개선이 왜곡 없이 보인다(과거엔 tCO2e
// 막대 길이로 표현했는데, 실측치가 추정치보다 큰 경우엔 등급이 좋아져도 막대가
// 짧아 보이는 모순이 있었다). 왼쪽(5등급, 최하)에서 오른쪽(1등급, 최상)으로 이동한
// 칸 수를 마커 이동 애니메이션으로 직접 보여준다.
const GRADE_TICKS = [5, 4, 3, 2, 1] as const;
const posOfGrade = (g: number) => ((5 - g) / 4) * 100;

// 매출액 추정 vs 전표 기반 실측 — 카드형 Before/After 비교(값을 화살표 문장 대신
// 두 박스로 나란히 놓고, 오른쪽 박스 위에 변화율 배지를 단다).
const EMISSION_BOX_MAX_H = 56;
const EMISSION_BOX_MIN_H = 22;

function EmissionBoxCompare({ beforeValue, afterValue }: { beforeValue: number; afterValue: number }) {
  const pct = beforeValue > 0 ? Math.round(((afterValue - beforeValue) / beforeValue) * 100) : 0;
  const pctLabel = `${pct > 0 ? "+" : ""}${pct}%`;

  // 박스 높이 자체를 값에 비례시켜 "줄었다/늘었다"가 숫자를 안 읽어도 바로
  // 보이게 한다 — 둘 다 고정 높이면 변화가 안 느껴진다. 최소 높이는 변화율
  // 배지 텍스트가 박스 안에 들어갈 만큼은 확보한다.
  const maxValue = Math.max(beforeValue, afterValue, 0.001);
  const beforeH = Math.max(EMISSION_BOX_MIN_H, Math.round((beforeValue / maxValue) * EMISSION_BOX_MAX_H));
  const afterH = Math.max(EMISSION_BOX_MIN_H, Math.round((afterValue / maxValue) * EMISSION_BOX_MAX_H));

  // 값 배지(pill)·라벨은 항상 같은 위치에 고정하고, 막대만 고정 높이 트랙
  // 안에서 아래를 기준으로 자라게 한다 — 그래야 막대 높이가 바뀌어도 글씨가
  // 같이 밀려 올라가지/내려가지 않는다.
  return (
    <div className="flex flex-1 flex-col justify-center gap-2">
      <div className="flex gap-2">
        <div className="flex-1 text-center">
          <span className="inline-block rounded-full bg-line px-2 py-0.5 text-[10px] font-bold text-muted">
            {fmt(beforeValue)}t
          </span>
          <div
            className="mt-1.5 flex items-end justify-center"
            style={{ height: EMISSION_BOX_MAX_H }}
          >
            <div className="w-full rounded-xl bg-line" style={{ height: beforeH }} />
          </div>
          <div className="mt-1.5 text-[10px] font-semibold text-faint">측정 전</div>
        </div>
        <div className="flex-1 text-center">
          <span className="inline-block rounded-full bg-line px-2 py-0.5 text-[10px] font-bold text-muted">
            {fmt(afterValue)}t
          </span>
          <div
            className="mt-1.5 flex items-end justify-center"
            style={{ height: EMISSION_BOX_MAX_H }}
          >
            <div
              className="flex w-full items-center justify-center rounded-xl bg-brand"
              style={{ height: afterH }}
            >
              <span className="text-[10px] font-bold text-white">{pctLabel}</span>
            </div>
          </div>
          <div className="mt-1.5 text-[10px] font-semibold text-muted">측정 후</div>
        </div>
      </div>
    </div>
  );
}

// Scope1/2 + 검토 예정 건수를 세로로 쌓아 EmissionBoxCompare 옆에 컴팩트하게 배치.
function ScopeCompact({
  scope1,
  scope2,
  hitlCount,
}: {
  scope1: number;
  scope2: number;
  hitlCount: number;
}) {
  return (
    <div className="flex flex-1 flex-col justify-center rounded-xl bg-bg p-3">
      <div className="space-y-2 text-[11.5px]">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-muted">
            <span className="h-2 w-2 rounded-full bg-scope1" /> Scope1
          </span>
          <span className="font-semibold text-ink">{fmt(scope1)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-muted">
            <span className="h-2 w-2 rounded-full bg-scope2" /> Scope2
          </span>
          <span className="font-semibold text-ink">{fmt(scope2)}</span>
        </div>
      </div>
      {hitlCount > 0 && (
        <div className="mt-2 rounded-md bg-hitl/25 px-2 py-1 text-center text-[10px] font-semibold text-hitl-ink">
          검토 예정 {hitlCount}건
        </div>
      )}
    </div>
  );
}

function GradeLadder({
  before,
  after,
  improvedBy,
}: {
  before: number;
  after: number;
  improvedBy: number;
}) {
  const beforePct = posOfGrade(before);
  const afterPct = posOfGrade(after);

  const [animPct, setAnimPct] = useState(beforePct);
  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimPct(afterPct));
    return () => cancelAnimationFrame(id);
  }, [afterPct]);

  const fillLeft = Math.min(beforePct, animPct);
  const fillWidth = Math.abs(animPct - beforePct);

  return (
    <div>
      <div className="flex items-center justify-center gap-2">
        <span className="rounded-full bg-line px-2.5 py-1 text-[13px] font-bold text-muted">
          {before}등급
        </span>
        <span className="text-faint">→</span>
        <span className="rounded-full bg-brand px-2.5 py-1 text-[15px] font-extrabold text-white">
          {after}등급
        </span>
        {improvedBy > 0 && (
          <span className="rounded-full bg-brand-soft px-2 py-1 text-[11px] font-bold text-brand-ink">
            {improvedBy}단계 개선
          </span>
        )}
      </div>

      <div className="relative mt-6 h-2 rounded-full bg-bg">
        {fillWidth > 0 && (
          <div
            className="absolute inset-y-0 rounded-full bg-brand-soft transition-all duration-700 ease-out"
            style={{ left: `${fillLeft}%`, width: `${fillWidth}%` }}
          />
        )}
        <div className="absolute inset-0 flex items-center justify-between">
          {GRADE_TICKS.map((g) => (
            <span key={g} className="h-2.5 w-2.5 rounded-full bg-line" />
          ))}
        </div>
        <div
          className="absolute -top-1 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-white bg-faint shadow"
          style={{ left: `${beforePct}%` }}
        />
        {afterPct !== beforePct && (
          <div
            className="absolute -top-1 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-white bg-brand shadow transition-[left] duration-700 ease-out"
            style={{ left: `${animPct}%` }}
          />
        )}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] font-semibold text-faint">
        {GRADE_TICKS.map((g) => (
          <span key={g}>{g}등급</span>
        ))}
      </div>
    </div>
  );
}

// 리포트가 "이 숫자 어떻게 나온 거야?"에 답하는 부분 — 총량 중 실측 대 추정
// 보정 비율, 연료별 내역까지 보여준다. db/pcaf.py::_after_measured가 이미
// 계산해 둔 measured_tco2e/estimated_gap_tco2e/by_fuel을 그대로 쓴다.
function FuelBreakdown({ after }: { after: After }) {
  const measuredPct = after.total > 0 ? Math.round((after.measured_tco2e / after.total) * 100) : 0;
  const estimatedPct = Math.max(0, 100 - measuredPct);

  return (
    <div className="flex-1 rounded-2xl bg-surface p-4">
      <div className="text-[13px] font-semibold text-ink">항목별 상세</div>

      <div className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-bg">
        <div className="h-full bg-brand" style={{ width: `${measuredPct}%` }} />
        {estimatedPct > 0 && <div className="h-full bg-line" style={{ width: `${estimatedPct}%` }} />}
      </div>
      <div className="mt-1 text-[10px] leading-relaxed text-faint">
        실측 {fmt(after.measured_tco2e)}
        {after.estimated_gap_tco2e > 0 && <> · 추정 {fmt(after.estimated_gap_tco2e)}</>}
      </div>

      <div className="mt-3 space-y-1.5 border-t border-line pt-2.5">
        {after.by_fuel.map((row) => (
          <div key={row.fuel} className="flex items-center justify-between text-[11.5px]">
            <span className="text-muted">{row.fuel}</span>
            <span className="font-semibold text-ink">
              {fmt(row.total_tco2e)}
              {row.estimated_tco2e > 0 && <span className="text-faint">*</span>}
            </span>
          </div>
        ))}
      </div>
      {after.by_fuel.some((row) => row.estimated_tco2e > 0) && (
        <div className="mt-2 text-[9.5px] text-faint">* 추정 보정 포함</div>
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

function MonthlyTrendChart({ monthly }: { monthly: After["monthly"] }) {
  const maxTotal = Math.max(...monthly.map((m) => m.total_tco2e), 0.001);
  const fuelsPresent = new Set(monthly.flatMap((m) => Object.keys(m.by_fuel)));
  const fuels = FUEL_ORDER.filter((f) => fuelsPresent.has(f));

  return (
    <div className="mt-3 rounded-2xl bg-surface p-5">
      <div className="text-[13px] font-semibold text-ink">월별 배출 추이</div>

      <div
        className="mt-4 flex items-end justify-between gap-1"
        style={{ height: CHART_HEIGHT_PX }}
      >
        {monthly.map((m) => {
          const barHeight = Math.max(2, Math.round((m.total_tco2e / maxTotal) * CHART_HEIGHT_PX));
          return (
            <div key={m.month} className="flex flex-1 flex-col items-center justify-end">
              <div
                className="flex w-full flex-col-reverse overflow-hidden rounded-[3px] bg-line"
                style={{ height: barHeight }}
              >
                {fuels.map((f) => {
                  const v = m.by_fuel[f] || 0;
                  if (v <= 0) return null;
                  return <div key={f} className={FUEL_BAR_COLOR[f]} style={{ flexGrow: v }} />;
                })}
              </div>
            </div>
          );
        })}
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

  // 마운트 시 0%에서 시작해 실제 위치로 스윽 슬라이드 — transition은 값이
  // "변할 때"만 트리거되므로, 첫 페인트는 0%로 그린 뒤 다음 프레임에 목표
  // 위치로 옮겨 애니메이션을 강제로 발생시킨다.
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

// 항목별 상세와 좌우로 짝지어지는 컴팩트 벤치마크 카드.
function BenchmarkCard({
  benchmark,
  hasDistribution,
}: {
  benchmark: Benchmark;
  hasDistribution: boolean;
}) {
  return (
    <div className="flex flex-1 flex-col rounded-2xl bg-surface p-4">
      {hasDistribution ? (
        <>
          <p className="truncate text-[13px] font-semibold text-ink">
            동종 {benchmark.industry_name ?? benchmark.industry_code} 대비
          </p>
          {/* 제목은 항목별 상세와 같은 높이(맨 위)에 고정하고, 나머지(퍼센트+막대)는
              남는 세로 공간 안에서 가운데로 — 그래야 옆 카드가 더 길어도 막대가
              카드 위쪽에 붕 떠 있지 않는다. */}
          <div className="flex flex-1 flex-col justify-center">
            <p className="text-[14px] font-bold text-ink">
              상위 <span className="text-brand-ink">{benchmark.percentile_pct}%</span>
            </p>
            <DistributionTrack min={benchmark.min!} max={benchmark.max!} value={benchmark.value!} />
          </div>
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

export function ScenePcaf() {
  const [data, setData] = useState<PcafResponse | null>(null);
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
      const res = await apiGet<PcafResponse>(`/pcaf/${cid}`);
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
    } catch (err) {
      // 목업으로 위장하지 않는다 — 실패는 실패로 표시
      console.error("PCAF 조회 실패:", err);
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

  const { before, after, benchmark } = data;
  const gradeUp = after ? before.grade - after.grade : 0;
  const hasDistribution =
    benchmark.value !== null &&
    benchmark.min !== null &&
    benchmark.median !== null &&
    benchmark.max !== null;

  return (
    <section>
      <h2 className="text-[17px] font-bold leading-snug text-ink">
        측정이 끝났어요
      </h2>

      {/* 등급 사다리 — 결과의 핵심이라 원래 크기(전체 폭)를 유지한다. */}
      <div className="mt-5 space-y-4 rounded-2xl bg-surface p-5">
        {after ? (
          <GradeLadder before={before.grade} after={after.grade} improvedBy={gradeUp} />
        ) : (
          <>
            <div className="flex items-center justify-center">
              <span className="rounded-full bg-line px-2.5 py-1 text-[13px] font-bold text-muted">
                {before.grade}등급 · 매출액 통계 추정
              </span>
            </div>
            <div className="rounded-xl border-2 border-dashed border-line p-4 text-center text-[12.5px] text-muted">
              ③ AI 분류를 먼저 실행하면 실측 배출량이 표시됩니다
            </div>
          </>
        )}
        {after && (
          <div className="flex gap-3 border-t border-line pt-3">
            <EmissionBoxCompare beforeValue={before.emission_tco2e} afterValue={after.total} />
            <ScopeCompact scope1={after.scope1} scope2={after.scope2} hitlCount={after.hitl_count} />
          </div>
        )}
      </div>

      {/* 벤치마크 + 항목별 상세를 좌우로 배치해 한 화면에 같이 들어오게 한다.
          항목별 상세는 분류 실행 전엔 보여줄 게 없어 그때는 벤치마크 카드
          (아직 산출 전 안내) 혼자 폭을 채운다. */}
      <div className="mt-3 flex gap-3">
        <BenchmarkCard benchmark={benchmark} hasDistribution={hasDistribution} />
        {after && <FuelBreakdown after={after} />}
      </div>

      {after && <MonthlyTrendChart monthly={after.monthly} />}

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
            PCAF {after ? after.grade : before.grade}등급 기준, 담당 은행원과의
            상담을 통해 우대금리 자격을 확인할 수 있어요.
          </p>
        </div>
      )}
    </section>
  );
}
