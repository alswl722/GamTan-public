"use client";

import type { CarbonPointDraftField } from "@/lib/api";

/** ApplicantInputForm(3단계)의 NARROW_KEYS와 같은 역할 — 이 목록엔 key가 없어(백엔드가
 * label 문자열만 준다) 라벨 텍스트로 판단한다. 자릿수가 정해진 짧은 값만 좁은 칸. */
const NARROW_LABELS = new Set(["고지서 고객번호(전기)", "고지서 고객번호(수도)"]);

/** 신청서 초안 항목 목록 — 라벨·값·출처를 그대로 렌더한다(읽기 전용).
 *
 * 위저드 2단계("이미 채운 데이터 확인하기")가 쓴다. 예전 `CarbonPointDraftSheet`의 목록
 * 부분을 떼어낸 것이다.
 *
 * `fields` 배열의 라벨 문구는 백엔드가 정한다 — 실물 서식이 개정되면 백엔드만 고쳐도 이
 * 화면이 따라온다.
 *
 * **어떤 항목을 넘길지는 호출부가 정한다.** 2단계는 값이 채워진 항목만 걸러 넘긴다(page.tsx
 * `filledFields` 주석) — 백엔드 `fields`에는 3단계에서 사장님이 채울 칸도 섞여 있다.
 * 그래도 null 표기를 남겨둔 건 최종 확인 화면처럼 전체 목록을 보여줄 자리가 생기면 빈칸을
 * 가리지 않고 "아직 없어요"로 드러내야 하기 때문이다(CLAUDE.md §6 실패 가시성).
 *
 * **필드 형태·그리드·색을 3단계(`ApplicantInputForm`)와 그대로 맞춘다** — 같은
 * `<fieldset><legend>` + `grid-cols-2`(NARROW는 col-span-1, 나머지 col-span-2) +
 * `border-line bg-surface` input 스타일. 다른 점은 `disabled` 하나뿐이다 — "이미
 * 채워졌다"는 값 자체로 보여주고, 폼의 생김새는 3단계와 완전히 같아야 사장님이 "다음
 * 단계에서도 이렇게 입력하는구나"를 자연스럽게 예상한다(2026-08-25 사용자 피드백:
 * "디자인이 3단계랑 다른데"). 그룹은 3단계의 `group`(백엔드 명세)과 달리 이 필드엔
 * 그룹 메타데이터가 없어, 백엔드가 채워 보내는 `source` 문구를 그대로 재사용한다.
 */
export function DraftFieldList({ fields }: { fields: CarbonPointDraftField[] }) {
  const groups: { source: string; fields: CarbonPointDraftField[] }[] = [];
  for (const field of fields) {
    const last = groups.at(-1);
    if (last !== undefined && last.source === field.source) last.fields.push(field);
    else groups.push({ source: field.source, fields: [field] });
  }

  const inputClass =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] text-ink " +
    "outline-none disabled:text-ink disabled:opacity-100";

  return (
    <div>
      {groups.map(({ source, fields: groupFields }) => (
        <fieldset key={source} className="mt-4 first:mt-0">
          <legend className="mb-2 text-[12.5px] font-bold text-ink">{source}</legend>
          <div className="grid grid-cols-2 gap-x-3 gap-y-3.5">
            {groupFields.map((field) => (
              <div
                key={field.label}
                className={NARROW_LABELS.has(field.label) ? "col-span-1" : "col-span-2"}
              >
                <label className="block text-[11.5px] font-semibold text-muted">
                  {field.label}
                </label>
                <div className="mt-1.5">
                  <input
                    type="text"
                    value={field.value ?? ""}
                    placeholder={field.value === null ? "아직 없어요" : undefined}
                    disabled
                    readOnly
                    className={inputClass}
                  />
                </div>
              </div>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
