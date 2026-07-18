"use client";

// 목업: GET /admin/rate-candidates (예시 — 결선 확장)

import type { RateCandidateItem } from "@/lib/admin-types";

const GRADE_COLORS: Record<number, string> = {
  2: "#00c7a9",
  3: "#53e1e5",
  4: "#9ca3af",
  5: "#d1b5ff",
};

export function RateCandidates({ candidates }: { candidates: RateCandidateItem[] }) {
  return (
    <div className="flex h-full flex-col rounded-2xl border border-[#e8eaed] bg-white shadow-card">
      <div className="flex items-center justify-between border-b border-[#e8eaed] px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-[#222222]">우대금리 자격 후보</h2>
          <p className="mt-0.5 text-xs text-[#9ca3af]">등급 업그레이드 근접 기업</p>
        </div>
        <span className="rounded-full border border-[#00c7a9]/30 bg-[#e3faf5] px-2 py-1 text-[11px] font-semibold text-[#00967f]">
          예시 · 결선 확장
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-[#e8eaed] overflow-y-auto">
        {candidates.map((c) => (
          <div key={c.id} className="px-5 py-3.5">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-[#222222]">{c.company_name}</span>
              <div className="flex flex-shrink-0 items-center gap-1.5">
                <span
                  className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
                  style={{ backgroundColor: GRADE_COLORS[c.current_grade] ?? "#9ca3af" }}
                >
                  {c.current_grade}등급
                </span>
                <span className="text-xs text-[#9ca3af]">→</span>
                <span
                  className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
                  style={{ backgroundColor: GRADE_COLORS[c.target_grade] ?? "#00c7a9" }}
                >
                  {c.target_grade}등급
                </span>
              </div>
            </div>
            <p className="mb-1 text-xs leading-relaxed text-[#666666]">
              <span className="font-medium text-[#222222]">필요 데이터:</span> {c.missing}
            </p>
            <p className="text-xs font-medium text-[#00967f]">{c.benefit}</p>
          </div>
        ))}
      </div>

      <div className="border-t border-[#e8eaed] bg-[#e3faf5]/30 px-5 py-3">
        <p className="text-[11px] text-[#9ca3af]">
          예시 데이터입니다. 실제 엔드포인트{" "}
          <code className="rounded bg-slate-100 px-1 font-mono">GET /admin/rate-candidates</code> 연결 후 반영됩니다.
        </p>
      </div>
    </div>
  );
}
