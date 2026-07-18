"use client";

// 실API: GET /admin/portfolio (등급 분포 Before/After)

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { PortfolioResponse } from "@/lib/admin-types";

const GRADE_COLORS: Record<string, string> = {
  "1": "#e2f15e", // lime — 최우수 (rare)
  "2": "#00c7a9", // brand mint — 양호
  "3": "#53e1e5", // scope2 teal — 양호
  "4": "#9ca3af", // faint/neutral — 중립
  "5": "#d1b5ff", // hitl purple — 경고
};

const GRADE_LABELS: Record<string, string> = {
  "1": "1등급 (최우수)",
  "2": "2등급 (양호)",
  "3": "3등급 (양호)",
  "4": "4등급 (중립)",
  "5": "5등급 (경고)",
};

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
        <h3 className="text-sm font-semibold text-[#222222]">{title}</h3>
        <p className="mt-0.5 text-xs text-[#9ca3af]">{subtitle}</p>
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
                border: "1px solid #e8eaed",
                fontSize: "12px",
                fontFamily: "inherit",
              }}
            />
          </PieChart>
        </ResponsiveContainer>

        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[11px] leading-none text-[#9ca3af]">{centerLabel}</span>
          <span className="mt-1 text-xl font-bold leading-none text-[#222222]">{centerValue}</span>
          <span className="mt-0.5 text-[10px] text-[#9ca3af]">{total}개사</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1.5">
        {data.map((entry) => (
          <div key={entry.grade} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm"
              style={{ backgroundColor: GRADE_COLORS[entry.grade] ?? "#e8eaed" }}
            />
            <span className="text-xs text-[#666666]">
              {GRADE_LABELS[entry.grade] ?? `${entry.grade}등급`}
            </span>
            <span className="text-xs font-semibold text-[#222222]">{entry.value}개사</span>
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
    <div className="flex h-full flex-col rounded-2xl border border-[#e8eaed] bg-white p-6 shadow-card">
      <div className="mb-2 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-[#222222]">PCAF 등급 분포 비교</h2>
          <p className="mt-0.5 text-xs text-[#9ca3af]">도입 전 vs 도입 후</p>
        </div>
        <div className="flex-shrink-0 rounded-lg border border-[#00c7a9]/30 bg-[#e3faf5] px-3 py-1.5 text-center">
          <span className="block text-[11px] leading-tight text-[#666666]">AI 도입 전 5등급 100%</span>
          <span className="mt-0.5 block text-[11px] font-bold leading-tight text-[#00967f]">
            → 도입 후 3등급 이상 {afterGoodPct}%
          </span>
        </div>
      </div>

      <div className="mb-6 h-px bg-[#e8eaed]" />

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
          <div className="w-px flex-1 bg-[#e8eaed]" />
          <span className="my-2 text-xl text-[#9ca3af]">→</span>
          <div className="w-px flex-1 bg-[#e8eaed]" />
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

      <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 border-t border-[#e8eaed] pt-4">
        {[
          { grade: "2·3", label: "양호", color: "#00c7a9", desc: "전표 실측 → 신뢰도 높음" },
          { grade: "4", label: "중립", color: "#9ca3af", desc: "부분 측정" },
          { grade: "5", label: "경고", color: "#d1b5ff", desc: "매출·업종 평균 추정" },
        ].map((item) => (
          <div key={item.grade} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 flex-shrink-0 rounded-sm" style={{ backgroundColor: item.color }} />
            <span className="text-xs text-[#666666]">
              <span className="font-semibold">{item.grade}등급</span> — {item.label}
            </span>
            <span className="text-[11px] text-[#9ca3af]">({item.desc})</span>
          </div>
        ))}
      </div>
    </div>
  );
}
