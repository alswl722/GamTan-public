"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  getCompanyId,
  getKTaxonomyLeads,
  getRateCandidate,
  type KTaxonomyLeadsResponse,
  type RateCandidateResponse,
} from "@/lib/api";
import { RateProductCard } from "@/components/RateProductCard";
import { KTaxonomyCard } from "@/components/KTaxonomyCard";

/** 하단바 "혜택" 탭 — 우대금리(RateProductCard)와 K택소노미 설비금융(KTaxonomyCard)을
 * 한 페이지의 두 섹션으로 묶는다. 예전엔 각각 메인 화면(/owner)에 개별 카드로 떠
 * 있었으나, 두 안내 모두 rate_approval_requests의 request_type만 다를 뿐(rate_upgrade
 * vs equipment_finance) 같은 "금융 혜택 안내" 성격이라 페이지로 분리했다.
 *
 * 두 카드 컴포넌트는 각자 내부에서 fetch해 데이터가 없으면 스스로 숨는다 — 이 페이지는
 * 그와 별개로 "둘 다 없을 때"의 빈 상태 문구를 보여주려고 가볍게 한 번 더 조회한다. */
export default function OwnerBenefitsPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [rate, setRate] = useState<RateCandidateResponse | null>(null);
  const [taxonomy, setTaxonomy] = useState<KTaxonomyLeadsResponse | null>(null);

  useEffect(() => {
    getCompanyId()
      .then((id) => {
        setCompanyId(id);
        return Promise.all([getRateCandidate(id), getKTaxonomyLeads(id)]);
      })
      .then(([r, t]) => {
        setRate(r);
        setTaxonomy(t);
      })
      .catch((err) => console.error("금융 혜택 조회 실패:", err));
  }, []);

  const loaded = rate !== null && taxonomy !== null;
  const isEmpty = loaded && rate.candidates.length === 0 && taxonomy.leads.length === 0;

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

      <h1 className="mt-4 text-[17px] font-bold leading-snug text-ink">금융 혜택</h1>
      <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
        측정된 탄소 데이터를 바탕으로 받을 수 있는 우대금리·설비금융 안내예요.
      </p>

      {!loaded ? (
        <p className="mt-6 text-[13px] text-faint">불러오는 중…</p>
      ) : isEmpty ? (
        <div className="mt-6 rounded-3xl bg-surface p-5 text-center shadow-card">
          <p className="text-[13px] leading-relaxed text-muted">
            아직 안내할 혜택이 없어요.
            <br />
            데이터를 더 채우면 여기에 우대금리·설비금융 안내가 나타나요.
          </p>
        </div>
      ) : (
        <>
          <RateProductCard companyId={companyId} />
          <KTaxonomyCard companyId={companyId} />
        </>
      )}
    </div>
  );
}
