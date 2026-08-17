"use client";

import { useEffect, useMemo, useState } from "react";
import { UploadCloud } from "lucide-react";
import { DOCUMENT_UPLOAD_TIMEOUT_MS, apiGet, apiPatch, apiUpload, getCompanyId } from "@/lib/api";

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
type UploadStatus = "uploading" | "done" | "error";
// id로 개별 업로드 시도를 구분한다 — 이제 월은 업로드 전에 사용자가 지정하지 않고
// 서버가 문서 내용에서 읽어 응답으로 알려준다(db/document_text_extractor.py) — 그래서
// 파일명 대신 시도 단위 id로 항목을 구분해야 여러 파일을 한 번에 올려도 안 섞인다.
type FileEntry = { id: string; fileName: string; status: UploadStatus; month?: number; error?: string };

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
    tone === "hitl" ? "border-hitl bg-hitl/25 text-hitl-ink" : "border-brand-soft bg-brand-soft text-brand-ink";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      className={`flex-1 whitespace-nowrap rounded-full border-2 px-2 py-2 text-center text-[13px] font-bold transition-colors ${
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
  const [entries, setEntries] = useState<Record<DocType, FileEntry[]>>({
    tax_invoice: [],
    electric_bill: [],
    gas_bill: [],
  });
  const [excelResult, setExcelResult] = useState<{
    status: "idle" | UploadStatus;
    count?: number;
    skipped?: number;
    error?: string;
  }>({ status: "idle" });
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [autoUploading, setAutoUploading] = useState(0);
  const [autoUploadErrors, setAutoUploadErrors] = useState<string[]>([]);

  async function refreshCoverage() {
    try {
      const cid = await getCompanyId();
      const cov = await apiGet<Coverage>(`/owner/${cid}/coverage`);
      setCoverage(cov);
      return cov;
    } catch (err) {
      console.error("결손 조회 실패:", err);
      return null;
    }
  }

  useEffect(() => {
    // 리뷰 지적사항 — fuel_types_json이 저장 안 된 채(null) "다음"으로 넘어가면 필터가 안
    // 걸려 안전하지만, 사용자가 도시가스 pill을 실수로 안 누르고 다른 연료만 저장하면
    // city_gas:false가 박혀 3~5월 도시가스 결손 킬러씬이 조용히 꺼진다. 이걸 막기 위해
    // 이미 쌓여있는 과거 전표(coverage)를 근거로 첫 진입 시 연료 pill 기본값을 추론해
    // 저장해둔다 — "이 회사는 실제로 이 연료를 써왔다"는 사실이 사람의 클릭보다 우선한다.
    // initialFuel이 있으면(뒤로가기 등으로 이미 선택된 적 있음) 건드리지 않는다.
    if (initialFuel !== undefined) return;
    let cancelled = false;
    refreshCoverage().then((cov) => {
      if (cancelled || !cov) return;
      const hasData = (bucket: string) =>
        Object.values(cov.matrix[bucket] ?? {}).some((v) => v > 0);
      const inferred: FuelTypesState = {
        diesel: hasData("경유/유류"),
        gasoline: false,
        cityGas: hasData("가스"),
        lpg: "no",
      };
      if (inferred.diesel || inferred.cityGas) {
        saveFuel(inferred);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 마운트 시 1회만, initialFuel 변화엔 반응 안 함
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

  async function uploadOcr(docType: DocType, file: File, entryId: string) {
    setEntries((e) => ({
      ...e,
      [docType]: [
        ...e[docType].filter((m) => m.id !== entryId),
        { id: entryId, fileName: file.name, status: "uploading" },
      ],
    }));
    try {
      const cid = await getCompanyId();
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", docType);
      form.append("mode", "ocr");
      // year/month는 안 보낸다 — 서버가 문서 내용에서 직접 읽어낸다
      // (db/document_text_extractor.py). 응답에 실려오는 month를 그대로 배지에 쓴다.
      const res = await apiUpload<{ month?: number }>(
        `/owner/${cid}/documents/upload`,
        form,
        DOCUMENT_UPLOAD_TIMEOUT_MS,
      );
      setEntries((e) => ({
        ...e,
        [docType]: [
          ...e[docType].filter((m) => m.id !== entryId),
          { id: entryId, fileName: file.name, status: "done", month: res.month },
        ],
      }));
      refreshCoverage();
    } catch (err) {
      console.error(`${docType} 업로드 실패:`, err);
      setEntries((e) => ({
        ...e,
        [docType]: [
          ...e[docType].filter((m) => m.id !== entryId),
          {
            id: entryId,
            fileName: file.name,
            status: "error",
            error: err instanceof Error ? err.message : "업로드 실패",
          },
        ],
      }));
    }
  }

  /** 슬롯 지정 카드의 "여러 장 한 번에 올리기" — uploadAuto와 같은 이유로 순차 처리.
   * 각 파일은 독립적인 entryId로 카드에 uploading→done/error 상태가 개별 반영된다. */
  async function uploadOcrFiles(docType: DocType, files: File[]) {
    for (let i = 0; i < files.length; i++) {
      const entryId = `${Date.now()}-${i}-${files[i].name}`;
      await uploadOcr(docType, files[i], entryId);
    }
  }

  /** "어떤 문서인지 모르겠다면" 박스 — document_type을 안 보내 OCR이 스스로 종류를
   * 판별한다("그냥 업로드", /owner/uploads 탭의 같은 박스와 동일 계약). 판별된
   * 종류의 카드(entries[docType])에 그대로 꽂아 넣어 그 카드의 뱃지·진행 상태가
   * 자연스럽게 갱신되게 한다 — 위저드 안이라 AI 분류(4단계)를 따로 트리거할
   * 필요는 없다(/owner/uploads처럼 위저드 밖 별도 탭이 아님).
   *
   * 여러 장을 한 번에 골라도 순차로 하나씩 올린다 — 백엔드 OCR(PaddleOCR)이
   * 프로세스당 한 번에 한 건만 처리하도록 락이 걸려 있어서(db/document_ocr_extractor.py,
   * 동시 predict() 호출 시 네이티브 엔진이 죽는 버그가 실측 확인됨), 여러 장을
   * 동시에 쏴봐야 뒤 순번 파일은 앞 파일들의 처리 시간만큼 대기가 쌓여 클라이언트
   * 타임아웃(60초)을 넘겨버린다. 한 장이 실패해도 나머지 장은 계속 올라간다. */
  async function uploadAuto(file: File) {
    const entryId = `auto-${Date.now()}-${file.name}`;
    setAutoUploading((n) => n + 1);
    try {
      const cid = await getCompanyId();
      const form = new FormData();
      form.append("file", file);
      form.append("mode", "ocr");
      const res = await apiUpload<{ document_type: DocType; month?: number }>(
        `/owner/${cid}/documents/upload`,
        form,
        DOCUMENT_UPLOAD_TIMEOUT_MS,
      );
      setEntries((e) => ({
        ...e,
        [res.document_type]: [
          ...e[res.document_type],
          { id: entryId, fileName: file.name, status: "done", month: res.month },
        ],
      }));
      refreshCoverage();
    } catch (err) {
      console.error("자동 업로드 실패:", err);
      const message = err instanceof Error ? err.message : "업로드에 실패했습니다.";
      setAutoUploadErrors((errs) => [...errs, `${file.name}: ${message}`]);
    } finally {
      setAutoUploading((n) => n - 1);
    }
  }

  async function uploadAutoFiles(files: File[]) {
    setAutoUploadErrors([]);
    for (const f of files) {
      await uploadAuto(f);
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
      const res = await apiUpload<{ vouchers_created: number; skipped_rows: number }>(
        `/owner/${cid}/documents/upload`,
        form,
        DOCUMENT_UPLOAD_TIMEOUT_MS,
      );
      setExcelResult({ status: "done", count: res.vouchers_created, skipped: res.skipped_rows });
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
    const fileEntries = entries[docType];

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
                  taxMode === m ? "bg-surface text-ink shadow-sm" : "text-muted"
                }`}
              >
                {m === "ocr" ? "사진·PDF" : "홈택스 엑셀"}
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
                accept=".xlsx"
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
                {!!excelResult.skipped && ` · ${excelResult.skipped}건은 날짜·금액이 비어 있어 건너뜀`}
              </div>
            )}
            {excelResult.status === "error" && (
              <div className="mt-2 text-[12px] text-hitl-ink">{excelResult.error}</div>
            )}
          </div>
        ) : (
          <>
            <label className="btn-cta mt-3 flex cursor-pointer items-center justify-center rounded-xl bg-brand py-2.5 text-[13px] font-bold text-white">
              사진·PDF 여러 장 한 번에 올리기
              <input
                type="file"
                accept="image/*,.pdf,.html,.htm,.mhtml"
                multiple
                className="hidden"
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  if (files.length > 0) void uploadOcrFiles(docType, files);
                  e.target.value = "";
                }}
              />
            </label>

            {fileEntries.length > 0 && (
              <div className="mt-2.5 space-y-1.5">
                {fileEntries.map((entry) =>
                  entry.status === "error" ? (
                    <div
                      key={entry.id}
                      className="rounded-lg bg-hitl/25 px-2.5 py-2 text-[11.5px] text-hitl-ink"
                    >
                      <span className="font-semibold">{entry.fileName}</span> — {entry.error}
                    </div>
                  ) : (
                    <span
                      key={entry.id}
                      className={`mr-1.5 inline-block rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${
                        entry.status === "done" ? "bg-brand-soft text-brand-ink" : "bg-line text-muted"
                      }`}
                    >
                      {entry.status === "uploading"
                        ? `${entry.fileName} 업로드 중…`
                        : `${entry.month}월 접수 완료`}
                    </span>
                  ),
                )}
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

      <div className="mt-5 flex gap-1.5 overflow-x-auto">
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

      <div className="mt-4 rounded-2xl bg-surface p-4 shadow-card">
        <div className="text-[13.5px] font-bold text-ink">어떤 문서인지 모르겠다면</div>
        <p className="mt-1 text-[12px] leading-relaxed text-muted">
          사진이나 PDF를 올리면 AI가 문서종류와 월을 알아서 인식해요.
        </p>
        <label className="btn-cta mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-xl bg-brand py-2.5 text-[13px] font-bold text-white disabled:opacity-60">
          <UploadCloud size={16} />
          {autoUploading > 0 ? `인식하는 중…(${autoUploading}개)` : "여러 장 한 번에 그냥 업로드하기"}
          <input
            type="file"
            accept="image/*,.pdf,.html,.htm,.mhtml"
            multiple
            className="hidden"
            disabled={autoUploading > 0}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length > 0) uploadAutoFiles(files);
              e.target.value = "";
            }}
          />
        </label>
        {autoUploadErrors.length > 0 && (
          <div className="mt-2 space-y-1">
            {autoUploadErrors.map((msg, i) => (
              <p key={i} className="text-[11.5px] text-hitl-ink">
                {msg}
              </p>
            ))}
          </div>
        )}
      </div>

      <div className="mt-5">
        <div className="mb-2 text-[12.5px] font-bold text-ink">계산서</div>
        <DocCard docType="tax_invoice" />
      </div>

      <div className="mt-4">
        <div className="mb-2 text-[12.5px] font-bold text-ink">고지서</div>
        <div className="space-y-2.5">
          <DocCard docType="electric_bill" />
          <DocCard docType="gas_bill" />
        </div>
      </div>

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
