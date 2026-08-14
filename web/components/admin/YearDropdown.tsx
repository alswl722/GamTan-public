"use client";

// 감사 대응 근거 패키지는 연 단위(월·일 없음)로 조회하므로 네이티브 <input type="number">
// 대신 드롭다운으로 연도만 고르게 한다.

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

const YEARS_BACK = 5;
const YEARS_FORWARD = 1;

export function YearDropdown({
  value,
  onChange,
}: {
  value: number;
  onChange: (year: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const thisYear = new Date().getFullYear();
  const years = Array.from(
    { length: YEARS_BACK + YEARS_FORWARD + 1 },
    (_, i) => thisYear + YEARS_FORWARD - i,
  );

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
    <div ref={rootRef} className="relative w-24">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-ink transition-colors focus:outline-none focus:ring-1 focus:ring-brand"
      >
        {value}년
        <ChevronDown className="h-3.5 w-3.5 text-faint" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-56 overflow-y-auto rounded-md border border-line bg-surface shadow-lg">
          {years.map((y) => (
            <button
              key={y}
              type="button"
              onClick={() => {
                onChange(y);
                setOpen(false);
              }}
              className={cn(
                "block w-full px-3 py-2 text-left text-xs transition-colors hover:bg-bg",
                y === value ? "bg-brand-soft font-semibold text-brand-ink" : "text-ink",
              )}
            >
              {y}년
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
