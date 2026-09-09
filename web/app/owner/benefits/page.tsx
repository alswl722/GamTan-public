"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  getCarbonPointEligibility,
  getCompanyId,
  getGovSupportCandidates,
  getKTaxonomyLeads,
  getRateCandidate,
  type BusinessScaleHint,
  type GovSupportCandidatesResponse,
  type KTaxonomyLeadsResponse,
  type RateCandidateResponse,
} from "@/lib/api";
import { RateProductCard } from "@/components/RateProductCard";
import { KTaxonomyCard } from "@/components/KTaxonomyCard";
import { GovSupportCard } from "@/components/GovSupportCard";
import { CarbonPointCard } from "@/components/CarbonPointCard";

/** 하단바 "맞춤 혜택" 탭 — 우대금리(RateProductCard)·K택소노미 설비금융(KTaxonomyCard)·
 * 정부 지원사업 매칭(GovSupportCard)을 한 페이지의 세 섹션으로 묶는다. 예전엔 각각
 * 메인 화면(/owner)에 개별 카드로 떠 있었으나, 셋 다 "신청 후보 안내이지 선정
 * 보장이 아니다"라는 같은 성격의 "금융 혜택 안내"라 페이지로 묶었다
 * (docs/gov-support-matching-plan.md §8).
 *
 * 카드 컴포넌트는 각자 내부에서 fetch해 데이터가 없으면 스스로 숨는다 — 이
 * 페이지는 그와 별개로 "셋 다 없을 때"의 빈 상태 문구를 보여주려고 가볍게 한 번
 * 더 조회한다.
 *
 * ── 소상공인 분기(2026-08-21, small-business-green-supply-develop-plan.md §3.2) ──
 * 사업 규모는 저장된 컬럼이 아니라 조회 시점에 계산되는 `business_scale_hint`로 가른다
 * (data-plan.md §5·§6.1 — 계약종별이 바뀌면 마이그레이션 없이 자동으로 따라오게 하려고
 * 저장하지 않는다):
 *
 *   "소상공인/상업시설" → 제조업 카드 3종을 렌더하지 않고 그 3종 API 조회도 건너뜀,
 *                        CarbonPointCard만 노출
 *   "제조업/산업체"     → 현행 그대로(CarbonPointCard가 스스로 숨는다). 산업용 전기는
 *                        탄소중립포인트 에너지분야 원천 제외라서다(data-plan §6.2)
 *   "미확인"           → 현행 3종 유지 + 계약종별 확인 안내(HITL, data-plan §6.1).
 *                        판별 실패 상태에서 이미 받던 안내를 없애는 쪽이 손해가 크다
 *
 * 2026-08-25에 fixture를 걷고 §9.1 API로 붙이면서 실제 2단 로딩이 됐다 — hint를 먼저
 * 받고(`scaleHint`), 소상공인이 아닐 때만 제조업 카드 3종을 조회한다. 소상공인 사업장에
 * 쓸데없는 조회 3건을 보내지 않는 게 원래 의도였고, 이제 그게 실제로 지켜진다. */
export default function OwnerBenefitsPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [scaleHint, setScaleHint] = useState<BusinessScaleHint | null>(null);
  const [rate, setRate] = useState<RateCandidateResponse | null>(null);
  const [taxonomy, setTaxonomy] = useState<KTaxonomyLeadsResponse | null>(null);
  const [govSupport, setGovSupport] = useState<GovSupportCandidatesResponse | null>(null);

  const isSmallBusiness = scaleHint === "소상공인/상업시설";
  const hintReady = scaleHint !== null;

  useEffect(() => {
    let cancelled = false;
    getCompanyId()
      .then(async (id) => {
        if (cancelled) return;
        setCompanyId(id);

        // 사업 규모부터 확인한다 — 소상공인 분기에서는 제조업 카드 3종을 아예 안 그리니
        // 조회도 하지 않는다(느린 gov-support 조회 25초 타임아웃을 헛돌리지 않는다).
        const { business_scale_hint } = await getCarbonPointEligibility(id);
        if (cancelled) return;
        setScaleHint(business_scale_hint);
        if (business_scale_hint === "소상공인/상업시설") return;

        const [r, t, g] = await Promise.all([
          getRateCandidate(id),
          getKTaxonomyLeads(id),
          getGovSupportCandidates(id),
        ]);
        if (cancelled) return;
        setRate(r);
        setTaxonomy(t);
        setGovSupport(g);
      })
      .catch((err) => console.error("금융 혜택 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, []);

  // 소상공인 분기는 3종을 조회하지 않으므로 companyId만 확정되면 그릴 준비가 끝난다.
  const loaded = hintReady && (isSmallBusiness
    ? companyId !== null
    : rate !== null && taxonomy !== null && govSupport !== null);

  // 소상공인 화면에서는 CarbonPointCard가 항상 렌더되므로(자격 미달도 "기준 미달"로
  // 보여준다) 빈 상태가 존재하지 않는다.
  const isEmpty =
    loaded &&
    !isSmallBusiness &&
    rate !== null &&
    taxonomy !== null &&
    govSupport !== null &&
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

      {/* 계약종별을 못 읽었을 때 — 기존 안내는 그대로 두고, 무엇을 올리면 판별이
          되는지만 덧붙인다(data-plan §6.1 HITL). 딥링크 규약은 결손월 안내 칩과 동일. */}
      {scaleHint === "미확인" && (
        <div className="mt-5 rounded-2xl bg-hitl/25 px-4 py-3">
          <div className="text-[12.5px] font-bold text-hitl-ink">
            전기요금고지서의 계약종별을 확인할 수 없어요
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-hitl-ink">
            계약종별(산업용·일반용)을 확인하면 사업장에 맞는 혜택을 더 정확히 안내할 수 있어요.
          </p>
          <Link
            href="/owner/uploads?type=electric_bill"
            className="mt-2 inline-block text-[11.5px] font-semibold text-hitl-ink underline decoration-dotted underline-offset-2"
          >
            전기요금고지서 올리러 가기
          </Link>
        </div>
      )}

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
      ) : isSmallBusiness ? (
        <CarbonPointCard companyId={companyId} />
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
