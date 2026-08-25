"use client";

import { useMemo, useRef, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import {
  saveCarbonPointApplicantInput,
  type CarbonPointApplicantField,
} from "@/lib/api";

/** 화면에서 좁게 두는 칸 — 우편번호·고객번호처럼 자릿수가 정해진 값은 전체 폭을 쓰면
 * 입력할 내용보다 칸이 훨씬 커서 뭘 넣는 칸인지 감이 안 온다. 그 외는 전부 한 줄 전체다
 * (모바일 1단 기준 — 참고한 데스크톱 2단 폼을 앱 폭에 맞춰 재구성한 결과).
 *
 * 전기 고객번호는 좁힐 후보였지만 안내 문구(help_text)가 붙어 있어 전체 폭으로 둔다. */
const NARROW_KEYS = new Set([
  "postal_code",
  "water_customer_number",
  "city_gas_customer_number",
  "district_heating_customer_number",
  "bank_name",
  "account_holder",
  "corporate_registration_no",
  "business_open_date",
]);

/** 3단계 "없는 데이터 입력하기" 폼.
 *
 * 칸 목록·라벨·필수여부·선택지는 전부 백엔드 명세(`applicant_fields`)를 그대로 렌더한다 —
 * 프론트에 필드 목록을 또 적으면 서식 개정 때 두 곳을 고쳐야 하고, 한쪽을 놓치면 "화면엔
 * 있는데 저장이 안 되는" 조용한 버그가 된다.
 *
 * 저장은 **칸을 벗어날 때(blur) 부분 저장**한다. 사장님이 폼을 다 채우기 전에 화면을
 * 벗어나도 지금까지 쓴 게 남아야 하기 때문이다(백엔드 PATCH가 보낸 key만 갱신한다).
 * 저장 실패는 조용히 넘기지 않고 배너로 드러낸다(CLAUDE.md §6 실패 가시성).
 *
 * `visible_when` 조건이 안 맞는 칸은 렌더하지 않는다 — 서식이 "금융계좌는 인센티브를
 * ②현금으로 선택하신 분에 한하여"라고 명시한 조건부 항목이라, 해당 없는 칸을 비활성으로
 * 띄워두면 사장님이 "내가 뭘 안 채웠나" 헷갈린다.
 */
export function ApplicantInputForm({
  companyId,
  applicationId,
  fields,
  onMissingRequiredChange,
}: {
  companyId: number;
  applicationId: number;
  fields: CarbonPointApplicantField[];
  /** 필수 미입력 목록이 바뀔 때 부모(위저드)에게 알린다 — "다음" 버튼 활성 조건. */
  onMissingRequiredChange: (missing: string[]) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.value ?? ""])),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 마지막으로 서버에 저장된 값 — 바뀌지 않은 칸을 blur할 때 요청을 또 보내지 않는다.
  const savedRef = useRef<Record<string, string>>(
    Object.fromEntries(fields.map((f) => [f.key, f.value ?? ""])),
  );

  // 조건부 칸을 걸러낸 "지금 화면에 보이는" 목록. 그룹 순서는 백엔드 배열 순서를 따른다.
  const visibleFields = useMemo(
    () =>
      fields.filter(
        (f) => f.visible_when === null || values[f.visible_when.key] === f.visible_when.equals,
      ),
    [fields, values],
  );

  const groups = useMemo(() => {
    const ordered: { group: string; items: CarbonPointApplicantField[] }[] = [];
    for (const field of visibleFields) {
      const last = ordered.at(-1);
      if (last !== undefined && last.group === field.group) last.items.push(field);
      else ordered.push({ group: field.group, items: [field] });
    }
    return ordered;
  }, [visibleFields]);

  async function persist(key: string, value: string) {
    if (savedRef.current[key] === value) return;
    setSaving(true);
    setError(null);
    try {
      const result = await saveCarbonPointApplicantInput(companyId, applicationId, {
        [key]: value,
      });
      savedRef.current = { ...savedRef.current, [key]: value };
      onMissingRequiredChange(result.missing_required);
    } catch (err) {
      // 저장에 실패했으면 실패한 채로 둔다 — 화면에만 값이 남아 "저장됐다"고 착각하게
      // 만들지 않는다. 사장님은 같은 칸을 다시 벗어나면 재시도된다.
      setError(err instanceof Error ? err.message : "입력을 저장하지 못했어요");
    } finally {
      setSaving(false);
    }
  }

  function update(key: string, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div>
      {groups.map(({ group, items }) => (
        <fieldset key={group} className="mt-4 first:mt-0">
          <legend className="mb-2 text-[12.5px] font-bold text-ink">{group}</legend>
          <div className="grid grid-cols-2 gap-x-3 gap-y-3.5">
            {items.map((field) => (
              <div
                key={field.key}
                className={NARROW_KEYS.has(field.key) ? "col-span-1" : "col-span-2"}
              >
                <FieldControl
                  field={field}
                  value={values[field.key] ?? ""}
                  onChange={(v) => update(field.key, v)}
                  onCommit={(v) => persist(field.key, v)}
                />
              </div>
            ))}
          </div>
        </fieldset>
      ))}

      <div className="mt-3 flex min-h-[18px] items-center gap-1.5">
        {saving && (
          <>
            <Loader2 size={12} className="animate-spin text-faint" />
            <span className="text-[11px] text-faint">저장 중…</span>
          </>
        )}
        {!saving && error !== null && (
          <>
            <AlertCircle size={12} className="shrink-0 text-hitl-ink" />
            <span className="text-[11px] font-semibold text-hitl-ink">{error}</span>
          </>
        )}
      </div>
    </div>
  );
}

/** 한 칸 — input_type에 따라 컨트롤 종류만 갈린다. 라벨·필수 표시·안내 문구는 공통.
 *
 * `onChange`는 타이핑마다, `onCommit`은 칸을 벗어날 때(select·radio는 선택 즉시) 호출된다 —
 * 글자마다 PATCH를 보내지 않으면서도 사장님이 화면을 벗어나기 전에 저장되게 하는 절충이다. */
function FieldControl({
  field,
  value,
  onChange,
  onCommit,
}: {
  field: CarbonPointApplicantField;
  value: string;
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
}) {
  const inputId = `cnp-${field.key}`;
  const helpId = field.help_text === null ? undefined : `${inputId}-help`;
  const inputClass =
    "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] text-ink " +
    "outline-none transition-colors placeholder:text-faint focus:border-brand";

  return (
    <div>
      <label
        htmlFor={field.input_type === "radio" ? undefined : inputId}
        className="block text-[11.5px] font-semibold text-muted"
      >
        {field.label}
        {field.required && (
          <span className="ml-0.5 text-brand-ink" aria-label="필수 항목">
            *
          </span>
        )}
      </label>

      <div className="mt-1.5">
        {field.input_type === "radio" ? (
          // 라디오는 label/htmlFor 짝이 항목마다 따로라 위 라벨을 그룹 제목으로만 쓴다.
          <div role="radiogroup" aria-label={field.label} className="flex gap-2">
            {field.options.map((option) => {
              const selected = value === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => {
                    onChange(option.value);
                    onCommit(option.value);
                  }}
                  className={`flex-1 rounded-xl border px-3 py-2.5 text-[13px] font-semibold transition-colors ${
                    selected
                      ? "border-brand bg-brand-soft text-brand-ink"
                      : "border-line bg-surface text-muted hover:text-ink"
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        ) : field.input_type === "select" ? (
          <select
            id={inputId}
            value={value}
            aria-describedby={helpId}
            onChange={(e) => {
              onChange(e.target.value);
              onCommit(e.target.value);
            }}
            className={inputClass}
          >
            <option value="">선택해 주세요</option>
            {field.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={inputId}
            type={field.input_type}
            value={value}
            placeholder={field.placeholder ?? undefined}
            aria-describedby={helpId}
            aria-required={field.required}
            onChange={(e) => onChange(e.target.value)}
            onBlur={(e) => onCommit(e.target.value)}
            className={inputClass}
          />
        )}
      </div>

      {field.help_text !== null && (
        <p id={helpId} className="mt-1.5 text-[10.5px] leading-relaxed text-faint">
          {field.help_text}
        </p>
      )}
    </div>
  );
}
