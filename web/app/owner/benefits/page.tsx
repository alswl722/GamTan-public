"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  getCompanyId,
  getGovSupportCandidates,
  getKTaxonomyLeads,
  getRateCandidate,
  type GovSupportCandidatesResponse,
  type KTaxonomyLeadsResponse,
  type RateCandidateResponse,
} from "@/lib/api";
import { RateProductCard } from "@/components/RateProductCard";
import { KTaxonomyCard } from "@/components/KTaxonomyCard";
import { GovSupportCard } from "@/components/GovSupportCard";

/** 하단바 "맞춤 혜택" 탭 — 우대금리(RateProductCard)·K택소노미 설비금융(KTaxonomyCard)·
 * 정부 지원사업 매칭(GovSupportCard)을 한 페이지의 세 섹션으로 묶는다. 예전엔 각각
 * 메인 화면(/owner)에 개별 카드로 떠 있었으나, 셋 다 "신청 후보 안내이지 선정
 * 보장이 아니다"라는 같은 성격의 "금융 혜택 안내"라 페이지로 묶었다
 * (docs/gov-support-matching-plan.md §8).
 *
 * 세 카드 컴포넌트는 각자 내부에서 fetch해 데이터가 없으면 스스로 숨는다 — 이
 * 페이지는 그와 별개로 "셋 다 없을 때"의 빈 상태 문구를 보여주려고 가볍게 한 번
 * 더 조회한다. */
export default function OwnerBenefitsPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [rate, setRate] = useState<RateCandidateResponse | null>(null);
  const [taxonomy, setTaxonomy] = useState<KTaxonomyLeadsResponse | null>(null);
  const [govSupport, setGovSupport] = useState<GovSupportCandidatesResponse | null>(null);

  useEffect(() => {
    getCompanyId()
      .then((id) => {
        setCompanyId(id);
        return Promise.all([getRateCandidate(id), getKTaxonomyLeads(id), getGovSupportCandidates(id)]);
      })
      .then(([r, t, g]) => {
        setRate(r);
        setTaxonomy(t);
        setGovSupport(g);
      })
      .catch((err) => console.error("금융 혜택 조회 실패:", err));
  }, []);

  const loaded = rate !== null && taxonomy !== null && govSupport !== null;
  const isEmpty =
    loaded &&
    rate.candidates.length === 0 &&
    taxonomy.leads.length === 0 &&
    govSupport.candidates.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-16">
      <div className="pt-5">
        <Link
          href="/owner"
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-faint transition-colors hover:text-ink"
        >
          ← 홈으로
        </Link>
      </div>

      <h1 className="mt-4 text-[19px] font-bold leading-snug text-ink">
        <span className="text-brand-ink">감탄</span>이 찾은 딱 맞는{" "}
        <span className="text-brand-ink">혜택</span>,
        <br />
        지금 확인해 보세요.
      </h1>

      <div className="mt-5 border-t border-line" />

      {!loaded ? (
        <p className="mt-6 text-[13px] text-faint">불러오는 중…</p>
      ) : isEmpty ? (
        <div className="mt-6 rounded-3xl bg-surface p-5 text-center shadow-card">
          <p className="text-[13px] leading-relaxed text-muted">
            아직 안내할 혜택이 없어요.
            <br />
            데이터를 더 채우면 여기에 우대금리·설비금융·정부 지원사업 안내가 나타나요.
          </p>
        </div>
      ) : (
        <>
          {rate && rate.candidates.length > 0 && (
            <h2 className="mt-5 text-[13px] font-semibold text-ink">우대금리</h2>
          )}
          <RateProductCard companyId={companyId} />
          <KTaxonomyCard companyId={companyId} />
          <GovSupportCard companyId={companyId} />
        </>
      )}
    </div>
  );
}
