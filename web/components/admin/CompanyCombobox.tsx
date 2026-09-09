"use client";

// 기업이 많아지면(결선 목표 300여개사) 네이티브 <select> 스크롤 탐색이 비효율적이라
// 검색 가능한 콤보박스로 대체한다 — "기업" 탭의 기업 선택 전용.

import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import type { Company } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

export function CompanyCombobox({
  companies,
  value,
  onChange,
}: {
  companies: Company[];
  value: number | "";
  onChange: (companyId: number | "") => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = companies.find((c) => c.company_id === value);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter((c) => c.company_name.toLowerCase().includes(q));
  }, [companies, query]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div ref={rootRef} className="relative w-64">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
      <input
        type="text"
        value={open ? query : (selected?.company_name ?? "")}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onClick={() => {
          setQuery("");
          setOpen(true);
        }}
        placeholder="기업명 검색"
        className="w-full rounded-full border border-line bg-surface py-1.5 pl-8 pr-2.5 text-xs text-ink placeholder:text-faint transition-colors focus:outline-none focus:ring-1 focus:ring-brand"
      />

      {open && (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-72 overflow-y-auto rounded-md border border-line bg-surface shadow-lg">
          {filtered.length === 0 ? (
            <div className="px-3 py-2.5 text-xs text-faint">일치하는 기업 없음</div>
          ) : (
            filtered.map((c) => (
              <button
                key={c.company_id}
                type="button"
                onClick={() => {
                  onChange(c.company_id);
                  setQuery("");
                  setOpen(false);
                }}
                className={cn(
                  "block w-full truncate px-3 py-2 text-left text-xs transition-colors hover:bg-bg",
                  c.company_id === value ? "bg-brand-soft font-semibold text-brand-ink" : "text-ink",
                )}
              >
                {c.company_name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
