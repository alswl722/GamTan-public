"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertCircle, ArrowRight, Download, Leaf } from "lucide-react";
import {
  createCarbonPointApplication,
  getCarbonPointEligibility,
  getCompanyId,
  getOwnerProgress,
  type CarbonPointDraft,
  type CarbonPointEligibility,
} from "@/lib/api";
import { CARBON_POINT_THRESHOLD_PCT, estimateRefund } from "@/lib/carbon-point";
import { ApplicationStepper, type StepperStep } from "@/components/carbon-point/ApplicationStepper";
import { ApplicantInputForm } from "@/components/carbon-point/ApplicantInputForm";
import { DraftFieldList } from "@/components/carbon-point/DraftFieldList";

/** 탄소중립포인트(에너지 분야) 사업자 참여신청서 초안 작성 — 4단계 위저드.
 *
 * ① 탄소 측정 완료 ② 이미 있는 데이터 채우기 ③ 없는 데이터 입력하기 ④ 신청서 다운로드
 *
 * 예전에는 "맞춤 혜택" 페이지의 `CarbonPointCard`에서 바텀시트(`CarbonPointDraftSheet`)로
 * 초안을 미리보기만 했다. 3단계에서 실제 입력을 받게 되면서 시트로는 좁아 라우트로
 * 승격했다(2026-08-25). 하단바 4탭에는 넣지 않는다 — 신청서는 상시 탭이 아니라 혜택
 * 카드에서 들어오는 절차형 화면이고, `/owner/measure`가 같은 위치를 잡고 있는 선례가 있다.
 *
 * ── 감탄이 하지 않는 것 ──
 * 접수는 사장님이 탄소중립포인트 포털에서 직접 한다(data-plan §3.2 — 감탄이 대구시·
 * 한국환경공단에 제출하는 인터페이스 자체가 없다). 감축률은 어디서도 확정치처럼 쓰지
 * 않는다("예상 감축률"로 통일, CLAUDE.md 원칙10). 포털 비밀번호는 받지 않는다.
 */
export default function CarbonPointApplicationPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [measured, setMeasured] = useState<boolean | null>(null);
  const [eligibility, setEligibility] = useState<CarbonPointEligibility | null>(null);
  const [draft, setDraft] = useState<CarbonPointDraft | null>(null);
  const [missingRequired, setMissingRequired] = useState<string[]>([]);
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCompanyId()
      .then(async (id) => {
        const [progress, elig] = await Promise.all([
          getOwnerProgress(id),
          getCarbonPointEligibility(id),
        ]);
        if (cancelled) return;
        setCompanyId(id);
        setMeasured(progress.steps.report);
        setEligibility(elig);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "불러오지 못했어요");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** 2단계 진입 시 초안을 만든다(같은 감축년도의 미제출 초안이 있으면 그 행을 재사용). */
  async function startDraft() {
    if (companyId === null) return;
    setError(null);
    try {
      const created = await createCarbonPointApplication(companyId);
      setDraft(created);
      setActive(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "초안을 만들지 못했어요");
    }
  }

  if (error !== null) {
    return (
      <Shell>
        <ErrorBanner message={error} />
      </Shell>
    );
  }

  if (companyId === null || measured === null || eligibility === null) {
    return (
      <Shell>
        <p className="mt-6 text-[13px] text-faint">불러오는 중…</p>
      </Shell>
    );
  }

  const refund = estimateRefund(eligibility.reduction_rate_pct);

  // 2단계는 감탄이 실제로 채운 항목만 보여준다.
  //
  // 백엔드 `draft.fields`는 서식 전체 미리보기라(build_application_draft) 감탄이 채운 칸과
  // 사장님이 채울 칸이 섞여 있다 — 휴대전화번호·전자메일은 마이데이터 5종에 없는 항목이고,
  // 수도 고객번호는 파싱 범위 밖이라 항상 null로 온다. 그걸 2단계에 "아직 없어요"로 띄우면
  // "이미 있는 데이터 채우기 / 확인만 해주세요"라는 단계 문구와 정면으로 어긋난다.
  // 값을 감추는 게 아니다 — 같은 항목을 3단계 입력 폼(`applicant_fields`)이 필수 표시까지
  // 달아 그대로 물어본다. 없는 걸 없다고 말하는 자리를 3단계 하나로 모으는 것이다.
  const filledFields = draft === null ? [] : draft.fields.filter((f) => f.value !== null);

  const steps: StepperStep[] = [
    {
      label: "탄소 측정 완료",
      content: measured ? (
        <div>
          <div className="rounded-2xl bg-brand-soft px-4 py-3.5">
            <div className="flex items-center gap-2">
              <Leaf size={15} strokeWidth={2.2} className="shrink-0 text-brand-ink" />
              <span className="text-[13px] font-bold text-brand-ink">
                측정이 끝나 신청서를 채울 수 있어요
              </span>
            </div>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-brand-ink">
              {eligibility.baseline_year}년 대비 {eligibility.target_year}년 예상 감축률{" "}
              {eligibility.reduction_rate_pct === null
                ? "계산 전"
                : `${eligibility.reduction_rate_pct}%`}
              {refund !== null && ` · 예상 환급액 ${refund.krw.toLocaleString()}원`}
            </p>
          </div>

          {eligibility.eligible ? (
            <button
              type="button"
              onClick={startDraft}
              className="btn-cta mt-4 flex w-full items-center justify-center gap-1.5 rounded-2xl bg-gradient-to-r from-brand-ink to-brand py-3.5 text-[14px] font-bold text-white"
            >
              신청서 채우기 시작
              <ArrowRight size={14} strokeWidth={2.4} />
            </button>
          ) : (
            // 자격 미달이면 초안을 만들지 않는다 — 신청 대상이 아닌 기업의 신청서를 DB에
            // 쌓지 않는다는 백엔드 규약과 화면을 맞춘다.
            <p className="mt-4 text-[12px] leading-relaxed text-muted">
              예상 감축률이 {CARBON_POINT_THRESHOLD_PCT}%를 넘으면 신청서를 만들어 드려요.
              에너지를 더 아끼면 다시 안내해 드릴게요.
            </p>
          )}
        </div>
      ) : (
        // 측정이 안 끝났으면 여기서 막는다 — 사용량 데이터 없이는 기준년도·감축년도
        // 사용량과 감축률을 채울 수 없고, 그게 신청서의 본문이다.
        <div>
          <div className="rounded-2xl bg-hitl/25 px-4 py-3.5">
            <div className="text-[13px] font-bold text-hitl-ink">
              먼저 탄소 측정을 끝내야 해요
            </div>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-hitl-ink">
              신청서에는 기준년도·감축년도 사용량과 감축률이 들어가요. 측정이 끝나야 그 값을
              채울 수 있어요.
            </p>
          </div>
          <Link
            href="/owner/measure"
            className="btn-cta mt-4 flex w-full items-center justify-center gap-1.5 rounded-2xl bg-gradient-to-r from-brand-ink to-brand py-3.5 text-[14px] font-bold text-white"
          >
            탄소 측정하러 가기
            <ArrowRight size={14} strokeWidth={2.4} />
          </Link>
        </div>
      ),
    },
    {
      label: "이미 있는 데이터 채우기",
      content:
        draft === null ? null : (
          <div>
            <p className="text-[12px] leading-relaxed text-muted">
              마이데이터와 고지서에서 읽어 감탄이 대신 채운 {filledFields.length}개 항목이에요.
            </p>
            {/* 채운 항목이 하나도 없으면 빈 카드를 띄우지 않는다 — 측정을 끝낸 뒤에만
                여기까지 오므로 실제로는 상호·사업자번호·사용량이 항상 있다. */}
            {filledFields.length > 0 && (
              <div className="mt-2.5">
                <DraftFieldList fields={filledFields} />
              </div>
            )}
            <button
              type="button"
              onClick={() => setActive(2)}
              className="btn-cta mt-3.5 flex w-full items-center justify-center gap-1.5 rounded-2xl bg-gradient-to-r from-brand-ink to-brand py-3 text-[14px] font-bold text-white"
            >
              다음
              <ArrowRight size={14} strokeWidth={2.4} />
            </button>
          </div>
        ),
    },
    {
      label: "없는 데이터 입력하기",
      content:
        draft === null || draft.application_id === null ? null : (
          <div>
            <ApplicantInputForm
              companyId={companyId}
              applicationId={draft.application_id}
              fields={draft.applicant_fields}
              onMissingRequiredChange={setMissingRequired}
            />

            {draft.remaining_fields.length > 0 && (
              <div className="mt-4 rounded-2xl bg-bg px-3.5 py-3">
                <div className="text-[11.5px] font-bold text-ink">직접 챙기셔야 하는 것</div>
                <ul className="mt-1.5 space-y-1">
                  {draft.remaining_fields.map((item) => (
                    <li key={item} className="flex gap-1.5 text-[11px] leading-relaxed text-muted">
                      <span className="mt-[6px] size-1 shrink-0 rounded-full bg-faint" />
                      <span className="min-w-0">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <button
              type="button"
              onClick={() => setActive(3)}
              disabled={missingRequired.length > 0}
              className="btn-cta mt-4 flex w-full items-center justify-center gap-1.5 rounded-2xl bg-gradient-to-r from-brand-ink to-brand py-3.5 text-[14px] font-bold text-white"
            >
              다음
              <ArrowRight size={14} strokeWidth={2.4} />
            </button>
            {missingRequired.length > 0 && (
              <p className="mt-2 text-center text-[11px] text-faint">
                별표(*) 항목 {missingRequired.length}개를 채우면 다음으로 넘어갈 수 있어요.
              </p>
            )}
          </div>
        ),
    },
    {
      label: "신청서 다운로드",
      content:
        draft === null ? null : (
          // 설명 문구를 전부 걷어낸 화면이다(2026-08-25). 접수 안내·비활성 이유·비보장
          // 문구가 버튼 하나 위아래로 세 덩이 붙어 있어 마지막 단계가 읽히지 않았다.
          // 비보장 문구의 지정 렌더 위치는 `CarbonPointCard`이고(develop-plan §3.3 —
          // data-plan §6.2가 API 플래그가 아니라 프론트 정적 문구로 강제한 그 자리) 거기엔
          // 그대로 남아 있다. 비활성 버튼은 `draft_document_url`이 null인 동안 눌리지
          // 않는다 — 없는 파일을 있는 척 내려주지 않는다(CLAUDE.md §6 실패 가시성).
          <div>
            <button
              type="button"
              disabled={draft.draft_document_url === null}
              className="btn-cta flex w-full items-center justify-center gap-1.5 rounded-2xl bg-brand py-3.5 text-[14.5px] font-extrabold text-white disabled:opacity-50"
            >
              <Download size={15} strokeWidth={2.4} />
              신청서 내려받기
            </button>
          </div>
        ),
    },
  ];

  return (
    <Shell>
      <h1 className="mt-4 text-[19px] font-bold leading-snug text-ink">
        <span className="text-brand-ink">탄소중립포인트</span> 신청서,
        <br />
        네 단계로 끝내요.
      </h1>
      <div className="mt-5 border-t border-line" />

      <ApplicationStepper
        steps={steps}
        activeIndex={active}
        onStepClick={(i) => setActive(i)}
      />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-16">
      <div className="pt-5">
        <Link
          href="/owner/benefits"
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-faint transition-colors hover:text-ink"
        >
          ← 맞춤 혜택으로
        </Link>
      </div>
      {children}
    </div>
  );
}

/** API 장애를 목업으로 가리지 않고 배너로 드러낸다(CLAUDE.md §6 실패 가시성). */
function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mt-6 rounded-2xl bg-hitl/25 px-4 py-3.5">
      <div className="flex items-center gap-2">
        <AlertCircle size={15} className="shrink-0 text-hitl-ink" />
        <span className="text-[13px] font-bold text-hitl-ink">불러오지 못했어요</span>
      </div>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-hitl-ink">{message}</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-2.5 rounded-full bg-surface px-3.5 py-1.5 text-[11.5px] font-semibold text-hitl-ink"
      >
        다시 시도
      </button>
    </div>
  );
}
