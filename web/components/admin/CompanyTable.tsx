"use client";

// 기업을 아직 선택하지 않은 상태에서 검색 없이도 전체 기업을 정렬 가능한
// 테이블로 바로 볼 수 있게 한다 — "기업 상세"·"감사 대응" 탭 공용.

import { useState } from "react";
import type { Company } from "@/lib/admin-types";
import { gradeColor } from "@/lib/grade-colors";

type CompanySortKey =
  | "company_name"
  | "industry_name"
  | "grade"
  | "scope1"
  | "scope2"
  | "total"
  | "hitl_count";

const SORT_COLUMNS: { key: CompanySortKey; label: string }[] = [
  { key: "company_name", label: "기업명" },
  { key: "industry_name", label: "업종" },
  { key: "grade", label: "PCAF 등급" },
  { key: "scope1", label: "Scope1" },
  { key: "scope2", label: "Scope2" },
  { key: "total", label: "합계" },
  { key: "hitl_count", label: "검토 대기" },
];

export function CompanyTable({
  companies,
  onSelect,
}: {
  companies: Company[];
  onSelect: (companyId: number) => void;
}) {
  const [sortKey, setSortKey] = useState<CompanySortKey>("company_name");
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = [...companies].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    const cmp =
      typeof av === "string" && typeof bv === "string"
        ? av.localeCompare(bv, "ko")
        : (av as number) - (bv as number);
    return sortAsc ? cmp : -cmp;
  });

  const toggleSort = (key: CompanySortKey) => {
    if (key === sortKey) {
      setSortAsc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  return (
    <div className="overflow-hidden rounded-md border border-line bg-surface">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-line bg-bg">
            {SORT_COLUMNS.map((col) => (
              <th key={col.key} className="px-4 py-2.5 font-medium text-faint">
                <button
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className="flex items-center gap-1 hover:text-ink"
                >
                  {col.label}
                  {sortKey === col.key && <span>{sortAsc ? "▲" : "▼"}</span>}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((c) => (
            <tr
              key={c.company_id}
              onClick={() => onSelect(c.company_id)}
              className="cursor-pointer border-b border-line last:border-b-0 transition-colors hover:bg-bg"
            >
              <td className="px-4 py-2.5 font-semibold text-ink">{c.company_name}</td>
              <td className="px-4 py-2.5 text-ink">{c.industry_name ?? "업종 미상"}</td>
              <td className="px-4 py-2.5">
                <span
                  className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
                  style={{ backgroundColor: gradeColor(c.grade) }}
                >
                  {c.grade}등급
                </span>
                {!c.measured && <span className="ml-1.5 text-[10px] text-faint">매출 추정</span>}
              </td>
              <td className="px-4 py-2.5 text-ink">{c.scope1.toLocaleString()}</td>
              <td className="px-4 py-2.5 text-ink">{c.scope2.toLocaleString()}</td>
              <td className="px-4 py-2.5 font-medium text-ink">{c.total.toLocaleString()} tCO2e</td>
              <td className="px-4 py-2.5">
                {c.hitl_count > 0 ? (
                  <span className="text-hitl-ink">{c.hitl_count}건</span>
                ) : (
                  <span className="text-faint">없음</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
