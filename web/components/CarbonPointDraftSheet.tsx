"use client";

import { X } from "lucide-react";
import { FIXTURE_BADGE_LABEL, type CarbonPointDraft } from "@/lib/carbon-point-fixture";

/** 탄소중립포인트 사업자 참여신청서 **초안 미리보기** 바텀시트
 * (docs/small-business-green-supply-develop-plan.md §3.3).
 *
 * 셸(오버레이·라운드·닫기·배경 클릭)은 GoalSheet.tsx 패턴을 그대로 따른다 — 하단바
 * 4탭에 안 들어가는 고아 라우트를 새로 만들지 않기 위해 페이지가 아니라 시트다.
 *
 * 이 화면이 하는 일은 "감탄이 가진 값으로 어디까지 채울 수 있는지" 보여주는 것까지다.
 * 접수는 사장님이 직접 한다(data-plan §3.2 — 감탄이 대구시·환경공단에 제출하는
 * 인터페이스 자체가 없다). 그래서:
 *   - 감축률은 어디서도 확정치처럼 쓰지 않는다("예상 감축률"로 통일, §2.3)
 *   - 다운로드 버튼은 비활성이다 — 초안 생성 함수(§2.3)가 아직 없고, 없는데 있는 척
 *     가짜 파일을 내려주지 않는다(CLAUDE.md §6 실패 가시성)
 *   - 필드 목록은 fixture 배열을 그대로 렌더한다 — 실물 hwp 서식이 확인되면
 *     (data-plan §14-1) fixture만 고쳐도 이 화면이 따라온다
 */
export function CarbonPointDraftSheet({
  draft,
  onClose,
}: {
  draft: CarbonPointDraft;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40" onClick={onClose}>
      <div
        className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-t-3xl bg-surface px-5 pb-8 pt-4 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <span className="text-[16px] font-extrabold text-ink">신청서 초안</span>
          <button type="button" onClick={onClose} className="p-1 text-faint" aria-label="닫기">
            <X size={20} />
          </button>
        </div>
        <p className="mt-1 text-[12px] text-muted">탄소중립포인트(에너지) 사업자 참여신청서</p>

        <div className="mt-4 space-y-2">
          {draft.fields.map((field) => (
            <div key={field.label} className="rounded-2xl bg-bg px-3.5 py-3">
              <div className="flex items-start justify-between gap-3">
                <span className="text-[11.5px] font-semibold text-muted">{field.label}</span>
                <span className="shrink-0 text-[10.5px] text-faint">{field.source}</span>
              </div>
              {field.value === null ? (
                <p className="mt-1 text-[13px] font-semibold text-hitl-ink">확인 필요</p>
              ) : (
                <p className="mt-1 text-[13px] font-semibold leading-snug text-ink">{field.value}</p>
              )}
            </div>
          ))}
        </div>

        {draft.remaining_fields.length > 0 && (
          <div className="mt-4">
            <div className="text-[12.5px] font-bold text-ink">사장님이 직접 입력해야 하는 항목</div>
            <ul className="mt-1.5 space-y-1">
              {draft.remaining_fields.map((item) => (
                <li key={item} className="flex gap-1.5 text-[12px] leading-relaxed text-muted">
                  <span className="mt-[7px] size-1 shrink-0 rounded-full bg-faint" />
                  <span className="min-w-0">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* draft_document_url이 null인 동안은 비활성 — 가짜 파일을 내려주지 않는다. */}
        <button
          type="button"
          disabled={draft.draft_document_url === null}
          className="btn-cta mt-5 w-full rounded-2xl bg-brand py-3.5 text-[14.5px] font-extrabold text-white disabled:opacity-50"
        >
          초안 내려받기
        </button>
        {draft.draft_document_url === null && (
          <p className="mt-2 text-center text-[11px] text-faint">초안 생성 기능 준비 중이에요.</p>
        )}

        <p className="mt-3 text-[11px] leading-relaxed text-faint">
          예상 감축률 기준으로 채운 초안이며, 실제 심사·지급은 한국환경공단이 진행합니다. 접수는
          사장님이 직접 하셔야 해요.
        </p>

        <div className="mt-2">
          <span className="inline-block rounded-full bg-line px-2 py-0.5 text-[10px] font-semibold text-faint">
            {FIXTURE_BADGE_LABEL}
          </span>
        </div>
      </div>
    </div>
  );
}
