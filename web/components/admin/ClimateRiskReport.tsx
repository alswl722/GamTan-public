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

function PendingBadge({ label }: { label: string }) {
  return (
    <span className="rounded bg-hitl/15 px-2 py-1 text-[10px] font-medium text-hitl-ink">
      {label} — 산정 예정
    </span>
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
                검증 오차율 (공시 섹션)
              </h3>
              <div className="flex flex-wrap gap-2">
                <PendingBadge label="분류 정확도" />
                <PendingBadge label="트랙A MAPE" />
                <PendingBadge label="트랙B 실물대조 오차" />
              </div>
            </section>

            <section>
              <div className="mb-3 flex items-center gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-faint">
                  시계열 금융배출량 (포트폴리오 전체 추이)
                </h3>
                <span className="rounded bg-hitl/15 px-1.5 py-0.5 text-[10px] font-semibold text-hitl-ink">
                  대출잔액 연동 전
                </span>
              </div>
              {report.financed_emissions_timeline.years.length === 0 ? (
                <p className="text-[11px] text-muted">시딩된 포트폴리오 대출 데이터가 없습니다.</p>
              ) : (
                <div className="flex items-end gap-8 rounded-md border border-line bg-bg/50 p-4">
                  {(() => {
                    const maxValue = Math.max(
                      ...report.financed_emissions_timeline.years.map((y) => y.financed_emission_tco2e),
                    );
                    return report.financed_emissions_timeline.years.map((y) => (
                      <div key={y.year} className="flex flex-col items-center gap-2">
                        <div className="flex h-20 w-14 items-end rounded bg-surface">
                          <div
                            className="w-full rounded-t bg-scope1"
                            style={{
                              height: `${maxValue > 0 ? Math.max(4, (y.financed_emission_tco2e / maxValue) * 100) : 0}%`,
                            }}
                          />
                        </div>
                        <div className="text-center leading-tight">
                          <p className="text-[12px] font-semibold text-ink">{y.year}</p>
                          <p className="text-[11px] text-muted">{y.financed_emission_tco2e.toFixed(2)} tCO2e</p>
                          <p className="text-[10px] text-muted">{y.company_count}개사</p>
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              )}
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
