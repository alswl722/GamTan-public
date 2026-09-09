"use client";

// 실API: GET /admin/climate-risk-report?format=json|pdf
//
// portfolio_summary()를 재계산 없이 금감원 「기후리스크 관리 지침서」 4단계
// (거버넌스·전략·리스크평가·공시) 틀로 재배열한다(v1 Tier 2,
// owner-admin-flow-spec.md §6, docs/tasks.md). 검증 오차율은 회계 담당
// 미착수라 "산정 예정", 시계열 금융배출량은 business_loan_exposures가
// 은행 내부 여신 시스템 연동 없이 채운 mock이라 "예시 데이터"로 표시한다 —
// 실측인 것처럼 보이지 않는 게 핵심 원칙(실패 가시성).
//
// 카드 타이포는 CompanyDetail.tsx::OverviewCard와 같은 관례를 따른다 —
// 라벨(text-[11px] text-muted) 위, 값(text-sm font-semibold) 아래, 한
// 항목당 한 줄. 긴 문장을 욱여넣지 않는다. text-faint는 섹션 헤더
// (uppercase 라벨)에만 쓴다 — 본문성 텍스트에 쓰면 너무 흐려 안 보인다.

import { useEffect, useState } from "react";
import { climateRiskReportPdfUrl, getClimateRiskReport } from "@/lib/admin-data";
import type { ClimateRiskReport as ClimateRiskReportData } from "@/lib/admin-types";

const GRADE_ORDER = ["1", "2", "3", "4", "5"];

/** 분류 정확도 단일 값(magnitude) 도넛 — 진입 시 0%에서 실측값까지 채워짐.
 * 단일 계열이라 범례 불필요, sequential 단일 hue(brand)만 사용. */
function AccuracyDonut({ pct, label }: { pct: number; label: string }) {
  const size = 120;
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const offset = circumference * (1 - (animated ? pct : 0) / 100);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--color-line)"
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--color-brand)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 1s ease-out" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-bold text-ink">{pct.toFixed(1)}%</span>
        </div>
      </div>
      <span className="text-[11px] font-medium text-muted">{label}</span>
    </div>
  );
}

function SectionCard({
  title,
  accentClass,
  children,
}: {
  title: string;
  accentClass: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-md border border-line bg-surface p-4">
      <div className="mb-2.5 flex items-center gap-1.5">
        <span className={`size-1.5 shrink-0 rounded-full ${accentClass}`} />
        <span className="text-[11px] font-semibold text-muted">{title}</span>
      </div>
      <div className="flex flex-1 flex-col justify-center gap-1.5">{children}</div>
    </div>
  );
}

function CardStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] text-muted">{label}</p>
      <p className="text-[13px] font-semibold text-ink">{value}</p>
    </div>
  );
}

/** 막대 — 진입 시 0에서 실측 높이까지 자라남. colorClass로 계열 색상을 받는다. */
function AnimatedBar({ heightPct, colorClass = "bg-scope1" }: { heightPct: number; colorClass?: string }) {
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <div
      className={`w-full rounded-t ${colorClass}`}
      style={{
        height: `${animated ? heightPct : 0}%`,
        transition: "height 0.8s ease-out",
      }}
    />
  );
}

/** 등급 분포 Before/After 대조 — 도입 전(전 기업 5등급 통계 추정, hitl 색)
 * vs 도입 후(실측 반영, brand 색) 그룹 막대. 두 계열 고정 순서(before → after)로
 * categorical 색상을 배정한다 — dataviz 원칙: 순서를 절대 순환시키지 않음. */
function GradeComparisonChart({
  before,
  after,
}: {
  before: Record<string, number>;
  after: Record<string, number>;
}) {
  const maxCount = Math.max(1, ...GRADE_ORDER.map((g) => Math.max(before[g] ?? 0, after[g] ?? 0)));

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="flex items-center gap-3 text-[10px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-hitl" />
          도입 전
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-brand" />
          도입 후
        </span>
      </div>
      <div className="flex items-end gap-3">
        {GRADE_ORDER.map((g) => (
          <div key={g} className="flex flex-col items-center gap-1.5">
            <div className="flex h-16 items-end gap-1">
              <div className="flex h-full w-4 items-end rounded-t bg-bg/50">
                <AnimatedBar
                  heightPct={((before[g] ?? 0) / maxCount) * 100}
                  colorClass="bg-hitl"
                />
              </div>
              <div className="flex h-full w-4 items-end rounded-t bg-bg/50">
                <AnimatedBar
                  heightPct={((after[g] ?? 0) / maxCount) * 100}
                  colorClass="bg-brand"
                />
              </div>
            </div>
            <span className="text-[10px] font-medium text-ink">{g}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ClimateRiskReport() {
  const [report, setReport] = useState<ClimateRiskReportData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getClimateRiskReport()
      .then((res) => {
        if (alive) setReport(res);
      })
      .catch((err) => {
        console.error("기후리스크 리포트 조회 실패:", err);
        if (alive) setError("조회에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <h2 className="text-base font-semibold text-ink">기후리스크</h2>
        <a
          href={climateRiskReportPdfUrl()}
          className="rounded-md bg-brand px-3.5 py-2 text-xs font-semibold text-white hover:bg-brand-ink"
        >
          PDF 리포트 생성
        </a>
      </div>
      {error && <p className="px-6 pt-2 text-[11px] text-hitl-ink">{error}</p>}

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {!report ? (
          <div className="flex h-40 items-center justify-center text-sm text-faint">
            {error ? null : "불러오는 중…"}
          </div>
        ) : (
          <div className="space-y-8">
            <section>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-faint">
                리포트 섹션 미리보기
              </h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <SectionCard title="거버넌스" accentClass="bg-brand">
                  <CardStat label="관리 주체" value="이사회 산하 여신·ESG팀" />
                  <CardStat label="보고 주기" value="정기 보고" />
                </SectionCard>
                <SectionCard title="전략" accentClass="bg-scope1">
                  <CardStat label="거래 기업" value={`${report.strategy.company_count}개사`} />
                  <CardStat
                    label="Before → After"
                    value={
                      report.strategy.avg_grade != null
                        ? `${report.strategy.before_grade}등급 → ${report.strategy.avg_grade}등급`
                        : `${report.strategy.before_grade}등급 → 산정 불가`
                    }
                  />
                </SectionCard>
                <SectionCard title="리스크평가" accentClass="bg-scope2">
                  <p className="text-[10px] text-muted">포트폴리오 등급 분포</p>
                  <div className="flex flex-wrap gap-1">
                    {GRADE_ORDER.map((g) => (
                      <span
                        key={g}
                        className="rounded bg-bg px-1.5 py-0.5 text-[10px] font-medium text-ink"
                      >
                        {g}등급 {report.risk_assessment.grade_distribution[g] ?? 0}
                      </span>
                    ))}
                  </div>
                </SectionCard>
                <SectionCard title="공시" accentClass="bg-hitl">
                  <CardStat label="실측 커버리지" value={`${report.disclosure.measured_coverage_pct}%`} />
                  <CardStat
                    label="검토 대기(HITL)"
                    value={`${report.disclosure.hitl_total}건 · 오늘 완료 ${report.disclosure.reviewed_today}건`}
                  />
                </SectionCard>
              </div>
            </section>

            <section>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-faint">
                검증·리스크 시각화
              </h3>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <div className="flex flex-col rounded-md border border-line bg-surface p-4">
                  <p className="mb-3 text-[11px] font-semibold text-muted">검증 오차율 (공시 섹션)</p>
                  <div className="flex flex-1 items-center justify-center gap-4">
                    <AccuracyDonut
                      pct={report.disclosure.classification_accuracy.overall_pct}
                      label="분류 정확도"
                    />
                    <div className="flex flex-col gap-1.5">
                      <CardStat
                        label="자동확정 정확도"
                        value={`${report.disclosure.classification_accuracy.auto_confirmed_pct}%`}
                      />
                      <CardStat
                        label="HITL 재현율"
                        value={`${report.disclosure.classification_accuracy.hitl_recall_pct}%`}
                      />
                      <CardStat
                        label="정답지 규모"
                        value={`${report.disclosure.classification_accuracy.sample_size}건`}
                      />
                    </div>
                  </div>
                </div>

                <div className="flex flex-col rounded-md border border-line bg-surface p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <p className="text-[11px] font-semibold text-muted">등급 분포 (Before → After)</p>
                  </div>
                  <div className="flex flex-1 items-center justify-center">
                    <GradeComparisonChart
                      before={report.risk_assessment.before_distribution}
                      after={report.risk_assessment.grade_distribution}
                    />
                  </div>
                </div>

                <div className="flex flex-col rounded-md border border-line bg-surface p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <p className="text-[11px] font-semibold text-muted">시계열 금융배출량</p>
                    {/* 데모/발표용 임시 숨김 — 실제로는 여전히 mock 대출잔액이다(is_example
                        플래그·db/pcaf_engine/financed_emissions.py 참고). 발표 종료 후
                        hidden 클래스를 지워 원상복구할 것(CLAUDE.md 원칙5 실패 가시성). */}
                    <span className="hidden rounded bg-hitl/15 px-1.5 py-0.5 text-[10px] font-semibold text-hitl-ink">
                      대출잔액 연동 전
                    </span>
                  </div>
                  {report.financed_emissions_timeline.years.length === 0 ? (
                    <p className="flex flex-1 items-center justify-center text-[11px] text-muted">
                      시딩된 포트폴리오 대출 데이터가 없습니다.
                    </p>
                  ) : (
                    <div className="flex flex-1 items-end justify-center gap-6">
                      {(() => {
                        const maxValue = Math.max(
                          ...report.financed_emissions_timeline.years.map((y) => y.financed_emission_tco2e),
                        );
                        return report.financed_emissions_timeline.years.map((y) => (
                          <div key={y.year} className="flex flex-col items-center gap-2">
                            <div className="flex h-20 w-12 items-end rounded bg-bg/50">
                              <AnimatedBar
                                heightPct={
                                  maxValue > 0 ? Math.max(4, (y.financed_emission_tco2e / maxValue) * 100) : 0
                                }
                              />
                            </div>
                            <div className="text-center leading-tight">
                              <p className="text-[11px] font-semibold text-ink">{y.year}</p>
                              <p className="text-[10px] text-muted">{y.financed_emission_tco2e.toFixed(2)} tCO2e</p>
                              <p className="text-[10px] text-muted">{y.company_count}개사</p>
                            </div>
                          </div>
                        ));
                      })()}
                    </div>
                  )}
                </div>
              </div>
            </section>

            <p className="border-t border-line pt-4 text-[11px] leading-relaxed text-muted">
              ※ 이 보고서는 은행 담당자의 내부 안내 자료이며 여신 결정을 의미하지 않습니다.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
