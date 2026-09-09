"use client";

// 목업: GET /admin/rate-candidates (예시 — 결선 확장)

import type { RateCandidateItem } from "@/lib/admin-types";
import { gradeColor } from "@/lib/grade-colors";

export function RateCandidates({ candidates }: { candidates: RateCandidateItem[] }) {
  return (
    <div className="flex h-full flex-col rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">우대금리 자격 후보</h2>
          <p className="mt-0.5 text-xs text-faint">등급 업그레이드 근접 기업</p>
        </div>
        <span className="rounded-full border border-brand/30 bg-brand-soft px-2 py-1 text-[11px] font-semibold text-brand-ink">
          예시 · 결선 확장
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {candidates.map((c) => (
          <div key={c.id} className="px-5 py-3.5">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-ink">{c.company_name}</span>
              <div className="flex flex-shrink-0 items-center gap-1.5">
                <span
                  className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
                  style={{ backgroundColor: gradeColor(c.current_grade) }}
                >
                  {c.current_grade}등급
                </span>
                <span className="text-xs text-faint">→</span>
                <span
                  className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
                  style={{ backgroundColor: gradeColor(c.target_grade) }}
                >
                  {c.target_grade}등급
                </span>
              </div>
            </div>
            <p className="mb-1 text-xs leading-relaxed text-muted">
              <span className="font-medium text-ink">필요 데이터:</span> {c.missing}
            </p>
            <p className="text-xs font-medium text-brand-ink">{c.benefit}</p>
          </div>
        ))}
      </div>

      <div className="border-t border-line bg-brand-soft/30 px-5 py-3">
        <p className="text-[11px] text-faint">
          예시 데이터입니다. 실제 엔드포인트{" "}
          <code className="rounded bg-line px-1 font-mono">GET /admin/rate-candidates</code> 연결 후 반영됩니다.
        </p>
      </div>
    </div>
  );
}
