"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { getGovSupportCandidates, type GovSupportCandidate, type GovSupportCandidatesResponse } from "@/lib/api";

/** 개인화된 정부 지원사업 매칭 카드 — "금융 혜택" 페이지(/owner/benefits)의 세 번째
 * 섹션. RateProductCard·KTaxonomyCard와 같은 패턴: companyId만 받아 스스로 fetch하고,
 * 후보가 0건이면 스스로 숨는다. docs/gov-support-matching-plan.md §8 정본.
 *
 * evidence가 null이면 LLM 근거 생성 실패 — "설명 생성 실패"로 표기한다(대체 문구로
 * 안 가림, §7 실패 가시성). 사실 필드(사업명·마감일·소관기관·링크)는 항상 그대로
 * 보여준다. 우대금리 카드와 같은 결로 "신청 후보 안내"이지 "선정 보장"이 아니다. */

/** LLM이 근거 문장에서 "**단어**"처럼 마크다운 볼드로 강조 표시를 넣는 경우가 있는데,
 * 이 카드는 마크다운 렌더러를 안 쓰고 그냥 <p>로 찍어서 별표가 그대로 노출됐다
 * (2026-08-18 사용자 피드백). 마크다운 파서를 통째로 들이는 대신, 강조 의도만
 * 살려서 별표를 떼고 색깔·굵기로 표시한다 — "형광펜" 느낌을 기존 브랜드 색
 * 토큰(bg-brand-soft)으로 낸다(새 임의 색 안 씀). */
function HighlightedText({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className="rounded bg-brand-soft px-1 font-semibold text-brand-ink">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

function daysUntil(dateStr: string): number {
  const target = new Date(dateStr + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function DdayBadge({ applyEndDate }: { applyEndDate: string | null }) {
  if (!applyEndDate) {
    return (
      <span className="shrink-0 whitespace-nowrap rounded-full bg-line px-2 py-0.5 text-[10.5px] font-semibold text-muted">
        상시
      </span>
    );
  }
  const days = daysUntil(applyEndDate);
  const label = days <= 0 ? "마감임박" : `D-${days}`;
  return (
    <span className="shrink-0 whitespace-nowrap rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] font-semibold text-brand-ink">
      {label}
    </span>
  );
}

/** "이상 신호 알림" 카드·RateProductCard.tsx의 GuidanceBubble과 같은 아바타+말풍선
 * 패턴 — 근거 문장이 똑디가 직접 설명해주는 느낌이 나도록 통일한다(2026-08-18,
 * 사용자 요청). evidence가 null이면 "설명 생성 실패"를 그대로 말풍선에 보여준다
 * (대체 문구로 안 가림, §7 실패 가시성).
 *
 * 이 컴포넌트가 놓이는 부모(GovSupportItem)가 bg-surface(흰색)라서 말풍선은
 * 반대색인 bg-bg(회색)를 쓴다 — RateProductCard.tsx의 GuidanceBubble과 동일한
 * 조합(원래 겉 흰 박스 안에 회색 아이템이 있던 구조였는데, 겉 박스를 없애고
 * 아이템 자체를 흰 카드로 바꾸면서 다시 이 조합으로 돌아왔다, 2026-08-18). */
function EvidenceBubble({ text }: { text: string }) {
  return (
    <div className="mt-2.5 flex items-start gap-2">
      <span className="relative h-7 w-7 shrink-0 overflow-hidden rounded-full bg-brand-soft">
        <Image src="/ddockdi_glasses.jpeg" alt="" fill className="object-cover" />
      </span>
      <div className="relative min-w-0 flex-1 rounded-2xl rounded-tl-sm bg-bg px-3.5 py-2.5">
        <span className="absolute -left-1.5 top-3 h-3 w-3 rotate-45 rounded-sm bg-bg" />
        <p className="text-[12px] leading-relaxed text-muted">
          <HighlightedText text={text} />
        </p>
      </div>
    </div>
  );
}

function GovSupportItem({ candidate }: { candidate: GovSupportCandidate }) {
  return (
    <div className="rounded-3xl bg-surface p-4 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold leading-snug text-ink">
            {candidate.program_name}
          </div>
          {candidate.agency_name && (
            <span className="mt-1.5 inline-block rounded-full bg-line px-2 py-0.5 text-[10.5px] font-semibold text-muted">
              {candidate.agency_name}
            </span>
          )}
        </div>
        <DdayBadge applyEndDate={candidate.apply_end_date} />
      </div>

      <EvidenceBubble text={candidate.evidence ?? "설명 생성 실패"} />

      {candidate.detail_url && (
        <div className="mt-2">
          <a
            href={candidate.detail_url}
            target="_blank"
            rel="noreferrer"
            className="text-[11.5px] font-semibold text-brand-ink underline decoration-dotted underline-offset-2"
          >
            자세히 보기
          </a>
        </div>
      )}
    </div>
  );
}

type SortBy = "relevance" | "deadline";

const SORT_OPTIONS: { value: SortBy; label: string }[] = [
  { value: "relevance", label: "연관도순" },
  { value: "deadline", label: "마감일순" },
];

/** "연관도순"은 API가 이미 유사도 내림차순으로 준 순서를 그대로 쓴다(재정렬 안 함).
 * "마감임박순"은 apply_end_date 오름차순 — null(상시모집)은 마감이 임박한 게
 * 아니라 반대로 급할 게 없는 쪽이라 맨 뒤로 보낸다. */
function sortCandidates(candidates: GovSupportCandidate[], sortBy: SortBy): GovSupportCandidate[] {
  if (sortBy === "relevance") return candidates;
  return [...candidates].sort((a, b) => {
    if (a.apply_end_date === null && b.apply_end_date === null) return 0;
    if (a.apply_end_date === null) return 1;
    if (b.apply_end_date === null) return -1;
    return a.apply_end_date.localeCompare(b.apply_end_date);
  });
}

function SortToggle({ value, onChange }: { value: SortBy; onChange: (v: SortBy) => void }) {
  return (
    <div className="flex shrink-0 gap-0.5 rounded-full bg-surface p-0.5 shadow-card">
      {SORT_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-full px-2 py-1 text-[10.5px] font-semibold transition-colors ${
            value === opt.value ? "bg-brand-soft text-brand-ink" : "text-faint hover:text-muted"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export function GovSupportCard({ companyId }: { companyId: number | null }) {
  const [data, setData] = useState<GovSupportCandidatesResponse | null>(null);
  const [sortBy, setSortBy] = useState<SortBy>("relevance");

  useEffect(() => {
    if (companyId === null) return;
    let cancelled = false;
    getGovSupportCandidates(companyId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => console.error("정부 지원사업 매칭 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (companyId === null || !data || data.candidates.length === 0) return null;

  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-ink">받을 수 있는 지원사업</div>
        </div>
        <SortToggle value={sortBy} onChange={setSortBy} />
      </div>

      {sortCandidates(data.candidates, sortBy).map((candidate) => (
        <GovSupportItem key={candidate.program_id} candidate={candidate} />
      ))}
    </div>
  );
}
