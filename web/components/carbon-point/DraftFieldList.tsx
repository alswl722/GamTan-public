"use client";

import type { CarbonPointDraftField } from "@/lib/api";

/** 신청서 초안 항목 목록 — 라벨·값·출처를 그대로 렌더한다(읽기 전용).
 *
 * 위저드 2단계("이미 있는 데이터 채우기")가 쓴다. 예전 `CarbonPointDraftSheet`의 목록
 * 부분을 떼어낸 것이다.
 *
 * `fields` 배열의 라벨 문구는 백엔드가 정한다 — 실물 서식이 개정되면 백엔드만 고쳐도 이
 * 화면이 따라온다.
 *
 * **어떤 항목을 넘길지는 호출부가 정한다.** 2단계는 값이 채워진 항목만 걸러 넘긴다(page.tsx
 * `filledFields` 주석) — 백엔드 `fields`에는 3단계에서 사장님이 채울 칸도 섞여 있다.
 * 그래도 null 표기를 남겨둔 건 최종 확인 화면처럼 전체 목록을 보여줄 자리가 생기면 빈칸을
 * 가리지 않고 "아직 없어요"로 드러내야 하기 때문이다(CLAUDE.md §6 실패 가시성).
 */
export function DraftFieldList({ fields }: { fields: CarbonPointDraftField[] }) {
  return (
    <dl className="divide-y divide-line overflow-hidden rounded-2xl bg-surface">
      {fields.map((field) => (
        <div
          key={field.label}
          className="flex items-baseline justify-between gap-3 px-3.5 py-2"
        >
          <dt className="min-w-0 text-[11.5px] font-semibold leading-snug text-muted">
            {field.label}
            {/* 출처를 값 옆이 아니라 라벨 아래에 둔다 — 한 항목이 한 줄 반으로 끝나 목록
                11개가 화면 하나에 들어온다(예전 카드형은 항목당 두 배 높이였다). */}
            <span className="mt-px block text-[10px] font-normal leading-snug text-faint">
              {field.source}
            </span>
          </dt>
          <dd
            className={`min-w-0 max-w-[54%] text-right text-[12.5px] font-bold leading-snug ${
              field.value === null ? "text-hitl-ink" : "text-ink"
            }`}
          >
            {field.value ?? "아직 없어요"}
          </dd>
        </div>
      ))}
    </dl>
  );
}
