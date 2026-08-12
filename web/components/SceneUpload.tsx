"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPatch, apiUpload, getCompanyId } from "@/lib/api";

/** 장면 ② — 연료 유형 체크 + 자료 업로드(세금계산서·전기요금고지서·도시가스고지서) 통합 화면.
 *
 * 연료 pill을 누르는 즉시 저장되고(PATCH), 필요한 문서 상태는 previewRequiredDocuments()로
 * 그 자리에서 바로 계산해 아래 업로드 카드에 반영한다 — 서버 왕복을 기다리지 않는다.
 * (판정 로직 자체의 정본은 db/document_requirements.py — 여기 계산은 그 규칙을 그대로 미러링)
 */

export type LpgStatus = "yes" | "no" | "unsure";

export type FuelTypesState = {
  diesel: boolean;
  gasoline: boolean;
  cityGas: boolean;
  lpg: LpgStatus;
};

export type RequiredDocuments = {
  tax_invoice: "required" | "optional" | "not_applicable";
  electric_bill: "required" | "optional" | "not_applicable";
  gas_bill: "required" | "optional" | "not_applicable";
};

const DEFAULT_FUEL_STATE: FuelTypesState = {
  diesel: false,
  gasoline: false,
  cityGas: false,
  lpg: "no",
};

function previewRequiredDocuments(fuel: FuelTypesState): RequiredDocuments {
  const scope1Selected = fuel.diesel || fuel.gasoline || fuel.lpg !== "no";
  return {
    tax_invoice: scope1Selected ? "required" : "optional",
    electric_bill: "required",
    gas_bill: fuel.cityGas ? "required" : "not_applicable",
  };
}

type DocType = "tax_invoice" | "electric_bill" | "gas_bill";
type DocStatus = "required" | "optional" | "not_applicable";
type UploadStatus = "idle" | "uploading" | "done" | "error";
type MonthEntry = { month: number; status: UploadStatus; error?: string };

const DOC_LABELS: Record<DocType, { title: string; hint: string }> = {
  tax_invoice: { title: "세금계산서", hint: "경유·휘발유·LPG 등 연료 구매 전표" },
  electric_bill: { title: "전기요금고지서", hint: "한전 마이데이터엔 사용량(kWh)이 없어 직접 업로드가 필요해요" },
  gas_bill: { title: "도시가스고지서", hint: "도시가스는 자동 연동 경로가 없어 직접 업로드가 필요해요" },
};

const STATUS_BADGE: Record<DocStatus, { label: string; className: string }> = {
  required: { label: "필수", className: "bg-hitl/30 text-hitl-ink" },
  optional: { label: "선택", className: "bg-brand-soft text-brand-ink" },
  not_applicable: { label: "해당없음", className: "bg-line text-faint" },
};

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

type Coverage = {
  matrix: Record<string, Record<string, number>>;
  gaps: { fuel: string; missing_months: number[] }[];
};

const FUEL_PILLS: { key: "diesel" | "gasoline" | "cityGas"; label: string }[] = [
  { key: "diesel", label: "경유" },
  { key: "gasoline", label: "휘발유" },
  { key: "cityGas", label: "도시가스" },
];

function Pill({
  label,
  selected,
  tone = "brand",
  disabled,
  onClick,
}: {
  label: string;
  selected: boolean;
  tone?: "brand" | "hitl";
  disabled?: boolean;
  onClick?: () => void;
}) {
  const selectedClass =
    tone === "hitl" ? "border-hitl bg-hitl/25 text-hitl-ink" : "border-brand bg-brand text-white";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      className={`rounded-full border-2 px-4 py-2.5 text-[13.5px] font-bold transition-colors ${
        selected ? selectedClass : "border-transparent bg-surface text-muted"
      } ${disabled ? "opacity-70" : ""}`}
    >
      {label}
    </button>
  );
}

export function SceneUpload({
  initialFuel,
  onFuelChange,
  onNext,
}: {
  initialFuel?: FuelTypesState;
  onFuelChange?: (fuel: FuelTypesState) => void;
  onNext: () => void;
}) {
  const [fuel, setFuel] = useState<FuelTypesState>(initialFuel ?? DEFAULT_FUEL_STATE);
  const [fuelError, setFuelError] = useState<string | null>(null);

  const required = useMemo(() => previewRequiredDocuments(fuel), [fuel]);

  const [taxMode, setTaxMode] = useState<"ocr" | "excel">("ocr");
  const [entries, setEntries] = useState<Record<DocType, MonthEntry[]>>({
    tax_invoice: [],
    electric_bill: [],
    gas_bill: [],
  });
  const [excelResult, setExcelResult] = useState<{ status: UploadStatus; count?: number; error?: string }>({
    status: "idle",
  });
  const [coverage, setCoverage] = useState<Coverage | null>(null);

  async function refreshCoverage() {
    try {
      const cid = await getCompanyId();
      const cov = await apiGet<Coverage>(`/owner/${cid}/coverage`);
      setCoverage(cov);
    } catch (err) {
      console.error("결손 조회 실패:", err);
    }
  }

  useEffect(() => {
    refreshCoverage();
  }, []);

  async function saveFuel(next: FuelTypesState) {
    setFuel(next);
    onFuelChange?.(next);
    setFuelError(null);
    try {
      const cid = await getCompanyId();
      await apiPatch(`/owner/${cid}/fuel-types`, {
        diesel: next.diesel,
        gasoline: next.gasoline,
        city_gas: next.cityGas,
        lpg: next.lpg,
        electricity: true,
      });
      refreshCoverage();
    } catch (err) {
      console.error("연료 유형 저장 실패:", err);
      setFuelError("연료 선택 저장에 실패했습니다. 다시 눌러 주세요.");
    }
  }

  function toggleFuel(key: "diesel" | "gasoline" | "cityGas") {
    saveFuel({ ...fuel, [key]: !fuel[key] });
  }

  function cycleLpg() {
    const nextStatus: LpgStatus = fuel.lpg === "no" ? "yes" : fuel.lpg === "yes" ? "unsure" : "no";
    saveFuel({ ...fuel, lpg: nextStatus });
  }

  async function uploadOcr(docType: DocType, month: number, file: File) {
    setEntries((e) => ({
      ...e,
      [docType]: [...e[docType].filter((m) => m.month !== month), { month, status: "uploading" }],
    }));
    try {
      const cid = await getCompanyId();
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", docType);
      form.append("mode", "ocr");
      form.append("year", "2025");
      form.append("month", String(month));
      await apiUpload(`/owner/${cid}/documents/upload`, form);
      setEntries((e) => ({
        ...e,
        [docType]: [...e[docType].filter((m) => m.month !== month), { month, status: "done" }],
      }));
      refreshCoverage();
    } catch (err) {
      console.error(`${docType} 업로드 실패:`, err);
      setEntries((e) => ({
        ...e,
        [docType]: [
          ...e[docType].filter((m) => m.month !== month),
          { month, status: "error", error: err instanceof Error ? err.message : "업로드 실패" },
        ],
      }));
    }
  }

  async function uploadExcel(file: File) {
    setExcelResult({ status: "uploading" });
    try {
      const cid = await getCompanyId();
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", "tax_invoice");
      form.append("mode", "excel");
      const res = await apiUpload<{ vouchers_created: number }>(`/owner/${cid}/documents/upload`, form);
      setExcelResult({ status: "done", count: res.vouchers_created });
      refreshCoverage();
    } catch (err) {
      console.error("엑셀 업로드 실패:", err);
      setExcelResult({
        status: "error",
        error: err instanceof Error ? err.message : "업로드 실패",
      });
    }
  }

  function DocCard({ docType }: { docType: DocType }) {
    const status = required[docType];
    const label = DOC_LABELS[docType];
    const badge = STATUS_BADGE[status];
    const monthEntries = entries[docType];

    if (status === "not_applicable") {
      return (
        <div className="rounded-2xl bg-surface p-4 opacity-50">
          <div className="flex items-center justify-between">
            <div className="text-[14.5px] font-bold text-ink">{label.title}</div>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${badge.className}`}>
              {badge.label}
            </span>
          </div>
          <div className="mt-1 text-[12px] text-muted">선택하신 연료엔 해당 없어요</div>
        </div>
      );
    }

    const isExcelTaxInvoice = docType === "tax_invoice" && taxMode === "excel";

    return (
      <div className="rounded-2xl bg-surface p-4">
        <div className="flex items-center justify-between">
          <div className="text-[14.5px] font-bold text-ink">{label.title}</div>
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${badge.className}`}>
            {badge.label}
          </span>
        </div>
        <div className="mt-1 text-[12px] text-muted">{label.hint}</div>

        {docType === "tax_invoice" && (
          <div className="mt-3 grid grid-cols-2 gap-1.5 rounded-xl bg-bg p-1">
            {(["ocr", "excel"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setTaxMode(m)}
                className={`rounded-lg py-2 text-[12.5px] font-semibold transition-colors ${
                  taxMode === m ? "bg-brand text-white" : "text-muted"
                }`}
              >
                {m === "ocr" ? "사진으로 올리기" : "홈택스 엑셀로 올리기"}
              </button>
            ))}
          </div>
        )}

        {isExcelTaxInvoice ? (
          <div className="mt-3">
            <label className="btn-cta flex w-full cursor-pointer items-center justify-center rounded-xl bg-brand py-3 text-[13.5px] font-bold text-white">
              {excelResult.status === "uploading" ? "업로드 중…" : "엑셀 파일 선택"}
              <input
                type="file"
                accept=".xlsx,.xls"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadExcel(f);
                  e.target.value = "";
                }}
              />
            </label>
            {excelResult.status === "done" && (
              <div className="mt-2 text-[12px] font-semibold text-brand-ink">
                {excelResult.count}건 업로드 완료
              </div>
            )}
            {excelResult.status === "error" && (
              <div className="mt-2 text-[12px] text-hitl-ink">{excelResult.error}</div>
            )}
          </div>
        ) : (
          <>
            <div className="mt-3 flex items-center gap-2">
              <select
                id={`${docType}-month`}
                className="rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-ink"
                defaultValue={1}
              >
                {MONTHS.map((m) => (
                  <option key={m} value={m}>
                    {m}월
                  </option>
                ))}
              </select>
              <label className="btn-cta flex flex-1 cursor-pointer items-center justify-center rounded-xl bg-brand py-2.5 text-[13px] font-bold text-white">
                사진·PDF 선택
                <input
                  type="file"
                  accept="image/*,.pdf"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    const files = Array.from(e.target.files ?? []);
                    const monthSelect = document.getElementById(
                      `${docType}-month`,
                    ) as HTMLSelectElement | null;
                    const month = Number(monthSelect?.value ?? 1);
                    files.forEach((f) => uploadOcr(docType, month, f));
                    e.target.value = "";
                  }}
                />
              </label>
            </div>

            {monthEntries.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {monthEntries
                  .sort((a, b) => a.month - b.month)
                  .map((m) => (
                    <span
                      key={m.month}
                      className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${
                        m.status === "done"
                          ? "bg-brand-soft text-brand-ink"
                          : m.status === "error"
                            ? "bg-hitl/25 text-hitl-ink"
                            : "bg-line text-muted"
                      }`}
                    >
                      {m.month}월{" "}
                      {m.status === "uploading" ? "업로드 중…" : m.status === "error" ? "실패" : "완료"}
                    </span>
                  ))}
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  const canProceed = (["tax_invoice", "electric_bill", "gas_bill"] as DocType[]).every((d) => {
    const status = required[d];
    if (status === "not_applicable" || status === "optional") return true;
    if (d === "tax_invoice" && taxMode === "excel") return excelResult.status === "done";
    return entries[d].some((m) => m.status === "done");
  });

  const relevantGaps = (coverage?.gaps ?? []).filter((g) => g.missing_months.length > 0);

  return (
    <section className="pt-4">
      <h2 className="text-[21px] font-bold leading-snug text-ink">
        연료를 선택하고
        <br />
        자료를 올려주세요
      </h2>
      <p className="mt-2 text-[14px] leading-relaxed text-muted">
        선택하신 연료에 맞춰 필요한 자료만 안내해 드려요.
      </p>

      <div className="mt-5 flex flex-wrap gap-2">
        {FUEL_PILLS.map((f) => (
          <Pill key={f.key} label={f.label} selected={fuel[f.key]} onClick={() => toggleFuel(f.key)} />
        ))}
        <Pill
          label={fuel.lpg === "unsure" ? "LPG · 잘 모르겠어요" : "LPG"}
          selected={fuel.lpg !== "no"}
          tone={fuel.lpg === "unsure" ? "hitl" : "brand"}
          onClick={cycleLpg}
        />
        <Pill label="전기" selected disabled />
      </div>

      {fuelError && (
        <div className="mt-3 rounded-xl bg-hitl/25 px-3.5 py-2.5 text-[12.5px] text-hitl-ink">
          {fuelError}
        </div>
      )}

      <div className="mt-5 space-y-2.5">
        <DocCard docType="tax_invoice" />
        <DocCard docType="electric_bill" />
        <DocCard docType="gas_bill" />
      </div>

      {relevantGaps.length > 0 && (
        <div className="mt-5 rounded-2xl bg-hitl/20 px-4 py-3.5 text-[12.5px] leading-relaxed text-hitl-ink">
          {relevantGaps.map((g) => (
            <div key={g.fuel}>
              {g.fuel} 자료가 {g.missing_months.join(", ")}월 안 보여요 — 다음 단계에서 자세히 확인할게요
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={onNext}
        disabled={!canProceed}
        className="btn-cta mt-5 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white disabled:opacity-40"
      >
        다음
      </button>
    </section>
  );
}
