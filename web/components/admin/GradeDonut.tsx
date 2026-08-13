"use client";

// 실API: GET /admin/portfolio (등급 분포 Before/After)

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { PortfolioResponse } from "@/lib/admin-types";
import { GRADE_COLORS, GRADE_LABELS } from "@/lib/grade-colors";

// 등급은 순서형 → 브랜드 민트 단일 색조의 순차 램프 (진함=실측 상위, 흐림=추정 하위).
// 인접 슬라이스 구분은 도넛 흰 간격(paddingAngle) + 범례 직접 라벨이 담당.
// 색상표는 lib/grade-colors — 다른 등급 표시와 공유.

function DonutChart({
  title,
  subtitle,
  distribution,
  total,
  centerLabel,
  centerValue,
}: {
  title: string;
  subtitle: string;
  distribution: Record<string, number>;
  total: number;
  centerLabel: string;
  centerValue: string;
}) {
  const data = Object.entries(distribution)
    .filter(([, v]) => v > 0)
    .map(([grade, count]) => ({
      name: GRADE_LABELS[grade] ?? `${grade}등급`,
      value: count,
      grade,
    }));

  return (
    <div className="flex flex-1 flex-col gap-3 min-w-0">
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <p className="mt-0.5 text-xs text-faint">{subtitle}</p>
      </div>

      <div className="relative h-52">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={88}
              paddingAngle={2}
              dataKey="value"
              strokeWidth={0}
            >
              {data.map((entry) => (
                <Cell key={entry.grade} fill={GRADE_COLORS[entry.grade] ?? "#e8eaed"} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value) => [`${value}개사`, "기업 수"]}
              contentStyle={{
                borderRadius: "10px",
                border: "1px solid var(--color-line)",
                fontSize: "12px",
                fontFamily: "inherit",
              }}
            />
          </PieChart>
        </ResponsiveContainer>

        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[11px] leading-none text-faint">{centerLabel}</span>
          <span className="mt-1 text-xl font-bold leading-none text-ink">{centerValue}</span>
          <span className="mt-0.5 text-[10px] text-faint">{total}개사</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1.5">
        {data.map((entry) => (
          <div key={entry.grade} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm"
              style={{ backgroundColor: GRADE_COLORS[entry.grade] ?? "#e8eaed" }}
            />
            <span className="text-xs text-muted">
              {GRADE_LABELS[entry.grade] ?? `${entry.grade}등급`}
            </span>
            <span className="text-xs font-semibold text-ink">{entry.value}개사</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function GradeDonut({ data }: { data: PortfolioResponse }) {
  const totalCompanies = data.company_count;
  const afterGoodCount =
    (data.grade_distribution["1"] ?? 0) +
    (data.grade_distribution["2"] ?? 0) +
    (data.grade_distribution["3"] ?? 0);
  const afterGoodPct =
    totalCompanies > 0 ? Math.round((afterGoodCount / totalCompanies) * 100) : 0;

  return (
    <div className="flex h-full flex-col rounded-md border border-line bg-surface p-6 shadow-card">
      <div className="mb-2 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-ink">PCAF 등급 분포 비교</h2>
          <p className="mt-0.5 text-xs text-faint">도입 전 vs 도입 후</p>
        </div>
        <div className="flex-shrink-0 rounded-md border border-brand/30 bg-brand-soft px-3 py-1.5 text-center">
          <span className="block text-[11px] leading-tight text-muted">AI 도입 전 5등급 100%</span>
          <span className="mt-0.5 block text-[11px] font-bold leading-tight text-brand-ink">
            → 도입 후 3등급 이상 {afterGoodPct}%
          </span>
        </div>
      </div>

      <div className="mb-6 h-px bg-line" />

      <div className="flex flex-1 flex-col gap-8 sm:flex-row">
        <DonutChart
          title="도입 전 (매출·업종 평균 추정)"
          subtitle="전 기업 5등급 — 매출액에 업종 평균 배출강도를 적용 (실측 데이터 없음)"
          distribution={data.before_distribution}
          total={totalCompanies}
          centerLabel="5등급 100%"
          centerValue="매출 추정"
        />

        <div className="hidden flex-col items-center justify-center px-2 sm:flex">
          <div className="w-px flex-1 bg-line" />
          <span className="my-2 text-xl text-faint">→</span>
          <div className="w-px flex-1 bg-line" />
        </div>

        <DonutChart
          title="도입 후 (실측 측정)"
          subtitle="전표·전기요금 기반 실물 배출량 산정"
          distribution={data.grade_distribution}
          total={totalCompanies}
          centerLabel="3등급↑"
          centerValue={`${afterGoodPct}%`}
        />
      </div>

      <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 border-t border-line pt-4">
        {[
          { grade: "2·3", color: GRADE_COLORS["2"], desc: "전표 실측 → 신뢰도 높음" },
          { grade: "4", color: GRADE_COLORS["4"], desc: "부분 측정" },
          { grade: "5", color: GRADE_COLORS["5"], desc: "매출·업종 평균 추정" },
        ].map((item) => (
          <div key={item.grade} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 flex-shrink-0 rounded-sm" style={{ backgroundColor: item.color }} />
            <span className="text-xs text-muted">
              <span className="font-semibold">{item.grade}등급</span> — {item.desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
