"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { getCompanies, getCompanyId, setCompanyId, type CompanyListItem } from "@/lib/api";

/** 사장님 앱 메인 화면 — 계정(로그인) 개념이 없어 기업을 직접 골라야 한다.
 * 고른 기업은 setCompanyId()로 저장되고, 이후 /owner/measure의 모든 단계가
 * getCompanyId()로 그 값을 그대로 읽는다(web/lib/api.ts). */

// /owner/measure의 STEPS와 라벨을 맞춘다(web/app/owner/measure/page.tsx) — 카드의
// 단계 미리보기가 실제 위저드 순서와 어긋나지 않게.
const MEASURE_STAGES = ["연동 동의", "데이터 수집", "결손 감지", "AI 분류", "리포트"] as const;

export default function OwnerHomePage() {
  const [companies, setCompanies] = useState<CompanyListItem[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getCompanies(), getCompanyId()])
      .then(([list, id]) => {
        setCompanies(list);
        setSelectedId(id);
      })
      .catch((err) => {
        console.error("기업 목록 조회 실패:", err);
        setError("기업 정보를 불러오지 못했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
      });
  }, []);

  function choose(id: number) {
    setCompanyId(id);
    setSelectedId(id);
    setPickerOpen(false);
  }

  const selected = companies?.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-6">
      {/* 기업 선택 — "로그인" 자리에 해당. 계정이 없어 기업명 자체를 눌러 고른다 */}
      <div className="relative pt-6">
        <button
          type="button"
          onClick={() => setPickerOpen((v) => !v)}
          disabled={!companies}
          className="flex items-center gap-1 text-[22px] font-extrabold text-ink disabled:opacity-60"
        >
          {selected ? `${selected.name}님` : companies ? "기업을 선택하세요" : "불러오는 중…"}
          <ChevronRight size={20} strokeWidth={2.6} className="shrink-0 text-muted" />
        </button>

        {pickerOpen && companies && (
          <div className="absolute inset-x-0 top-[calc(100%+8px)] z-10 max-h-72 overflow-y-auto rounded-2xl bg-surface p-1.5 shadow-card">
            {companies.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => choose(c.id)}
                className={`flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-left text-[13.5px] font-semibold transition-colors ${
                  c.id === selectedId ? "bg-brand-soft text-brand-ink" : "text-ink hover:bg-bg"
                }`}
              >
                <span className="truncate">{c.name}</span>
                <span className="shrink-0 text-[11px] font-medium text-faint">
                  {c.industry_name ?? c.region ?? ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-hitl/25 px-3.5 py-2.5 text-[12.5px] text-hitl-ink">
          {error}
        </div>
      )}

      {/* 프로모 카드 — 종합소득세 환급 카드 참고: 라벨+화살표 → 굵은 CTA 문장 → 진행 단계 미리보기 */}
      <Link
        href="/owner/measure"
        className="btn-cta group mt-5 block rounded-3xl bg-surface px-5 py-5 shadow-card transition-transform"
      >
        <span className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[13px] font-bold text-muted">
            탄소 측정
            <span className="h-1.5 w-1.5 rounded-full bg-brand" />
          </span>
          <ChevronRight size={16} className="shrink-0 text-faint" />
        </span>

        <span className="mt-2.5 flex items-center gap-2">
          <span className="text-[16.5px] font-extrabold leading-snug text-ink">
            우리 기업 탄소 배출량을
            <br />
            확인해보세요
          </span>
          <Search size={22} strokeWidth={2.2} className="shrink-0 text-brand-ink" />
        </span>

        <span className="mt-4 block h-1 overflow-hidden rounded-full bg-line">
          <span
            className="block h-full rounded-full bg-brand"
            style={{ width: `${100 / MEASURE_STAGES.length}%` }}
          />
        </span>
        <span className="mt-2 flex items-center justify-between">
          {MEASURE_STAGES.map((stage, i) => (
            <span
              key={stage}
              className={`text-[10.5px] font-semibold ${i === 0 ? "text-ink" : "text-faint"}`}
            >
              {stage}
            </span>
          ))}
        </span>
      </Link>
    </div>
  );
}
