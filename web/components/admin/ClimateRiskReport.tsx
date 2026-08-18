"use client";

// 실API: GET /admin/climate-risk-report?format=json|pdf
//
// portfolio_summary()를 재계산 없이 금감원 「기후리스크 관리 지침서」 4단계
// (거버넌스·전략·리스크평가·공시) 틀로 재배열한다(v1 Tier 2,
// owner-admin-flow-spec.md §6, docs/tasks.md). 검증 오차율은 회계 담당
// 미착수라 "산정 예정", 시계열 금융배출량은 business_loan_exposures가
// 0건(은행 내부 여신 시스템 연동 필요)이라 "예시 데이터"로 표시한다 —
// 실측인 것처럼 보이지 않는 게 핵심 원칙(실패 가시성).

import { useEffect, useState } from "react";
import {
  climateRiskReportPdfUrl,
  getClimateRiskReport,
} from "@/lib/admin-data";
import type { ClimateRiskReport as ClimateRiskReportData } from "@/lib/admin-types";

const GRADE_ORDER = ["1", "2", "3", "4", "5"];

function SectionCard({
  index,
  title,
  accentClass,
  children,
}: {
  index: string;
  title: string;
  accentClass: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex-1 rounded-lg border border-line bg-bg p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className={`size-2 rounded-full ${accentClass}`} />
        <span className="text-[13px] font-bold text-ink">
          {index} {title}
        </span>
      </div>
      <div className="space-y-1 text-[11px] leading-relaxed text-muted">
        {children}
      </div>
    </div>
  );
}

function PendingBadge({ label }: { label: string }) {
  return (
    <span className="rounded bg-hitl/20 px-2 py-1 text-[10px] font-medium text-hitl-ink">
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

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {!report ? (
          <div className="flex h-40 items-center justify-center text-sm text-faint">
            {error ? null : "불러오는 중…"}
          </div>
        ) : (
          <div className="space-y-6">
            <div>
              <p className="mb-2 text-[11px] font-medium text-faint">
                리포트 섹션 미리보기
              </p>
              <div className="flex flex-wrap gap-3">
                <SectionCard index="①" title="거버넌스" accentClass="bg-brand">
                  <p>{report.governance.description}</p>
                </SectionCard>
                <SectionCard index="②" title="전략" accentClass="bg-scope1">
                  <p>거래 기업 {report.strategy.company_count}개사</p>
                  <p>
                    도입 전 기준선: {report.strategy.before_grade}등급
                    (매출·업종 통계 대입)
                  </p>
                  <p>
                    도입 후:{" "}
                    {report.strategy.avg_grade != null
                      ? `배출가중 평균 ${report.strategy.avg_grade}등급`
                      : "산정 불가"}
                  </p>
                </SectionCard>
                <SectionCard
                  index="③"
                  title="리스크평가"
                  accentClass="bg-scope2"
                >
                  <p>포트폴리오 등급 분포</p>
                  <div className="mt-1 flex gap-2">
                    {GRADE_ORDER.map((g) => (
                      <span
                        key={g}
                        className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-ink"
                      >
                        {g}등급{" "}
                        {report.risk_assessment.grade_distribution[g] ?? 0}개사
                      </span>
                    ))}
                  </div>
                </SectionCard>
                <SectionCard index="④" title="공시" accentClass="bg-hitl">
                  <p>
                    실측 데이터 커버리지{" "}
                    {report.disclosure.measured_coverage_pct}%
                  </p>
                  <p>검토 대기(HITL) {report.disclosure.hitl_total}건</p>
                  <p>오늘 검토 완료 {report.disclosure.reviewed_today}건</p>
                </SectionCard>
              </div>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-medium text-faint">
                검증 오차율 (공시 섹션)
              </p>
              <div className="flex flex-wrap gap-2">
                <PendingBadge label="분류 정확도" />
                <PendingBadge label="트랙A MAPE" />
                <PendingBadge label="트랙B 실물대조 오차" />
              </div>
            </div>

            <div className="border-t border-line pt-4">
              <div className="mb-3 flex items-center gap-2">
                <p className="text-[13px] font-bold text-ink">
                  금융배출량 전체추이
                </p>
                <span className="rounded bg-hitl/20 px-2 py-1 text-[10px] font-semibold text-hitl-ink">
                  대출잔액 연동 전
                </span>
              </div>
              <div className="mb-3 flex items-end gap-6">
                {report.financed_emissions_timeline.years.map((y) => (
                  <div
                    key={y.year}
                    className="flex flex-col items-center gap-1.5"
                  >
                    <div className="flex h-[90px] w-16 items-end rounded bg-bg">
                      <div
                        className="w-full rounded-t bg-scope1"
                        style={{
                          height: `${Math.min(100, (y.year - 2023) * 25)}%`,
                        }}
                      />
                    </div>
                    <span className="text-[11px] font-semibold text-ink">
                      {y.year}
                    </span>
                    <span className="text-[10px] text-muted">
                      {y.grade_label}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <p className="border-t border-line pt-3 text-[10px] text-faint">
              ※ 이 보고서는 은행 담당자의 내부 안내 자료이며 여신 결정을
              의미하지 않습니다.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
