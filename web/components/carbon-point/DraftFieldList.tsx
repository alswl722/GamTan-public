"use client";

import type { CarbonPointDraftField } from "@/lib/api";

/** 신청서 초안 항목 목록 — 라벨·값·출처를 그대로 렌더한다(읽기 전용).
 *
 * 위저드 2단계("이미 있는 데이터 채우기")와 4단계(최종 확인)가 같은 컴포넌트를 쓴다.
 * 예전 `CarbonPointDraftSheet`의 목록 부분을 떼어낸 것이다.
 *
 * `fields` 배열의 라벨 문구는 백엔드가 정한다 — 실물 서식이 개정되면 백엔드만 고쳐도 이
 * 화면이 따라온다. 값이 null인 항목은 빈칸으로 가리지 않고 "아직 없어요"로 드러낸다
 * (CLAUDE.md §6 실패 가시성).
 */
export function DraftFieldList({ fields }: { fields: CarbonPointDraftField[] }) {
  return (
    <dl className="space-y-2">
      {fields.map((field) => (
        <div key={field.label} className="rounded-2xl bg-bg px-3.5 py-3">
          <div className="flex items-start justify-between gap-3">
            <dt className="text-[11.5px] font-semibold text-muted">{field.label}</dt>
            <span className="shrink-0 text-[10.5px] text-faint">{field.source}</span>
          </div>
          <dd
            className={`mt-1 text-[13px] font-semibold leading-snug ${
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
