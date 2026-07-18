"use client";

// 실API: GET /admin/hitl → queue
// 실API: PATCH /admin/classifications/{id}/confirm | /{id} (수정) | /{id}/reject

import { useMemo, useState } from "react";
import { confirmVoucher, editVoucher, rejectVoucher } from "@/lib/admin-data";
import type { HitlItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

const CATEGORY_OPTIONS = ["고정연소", "이동연소", "간접배출", "공정배출", "기타"];
const FUEL_OPTIONS = ["경유", "휘발유", "등유", "중유", "천연가스", "도시가스", "LPG", "전기", "스팀", "기타"];

function ConfidenceBadge({ value }: { value: number }) {
  const isLow = value < 0.5;
  const isMid = value >= 0.5 && value < 0.65;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
        isLow && "bg-[#d1b5ff]/30 text-[#7a4fd9]",
        isMid && "bg-amber-100 text-amber-700",
        !isLow && !isMid && "bg-[#e3faf5] text-[#00967f]",
      )}
    >
      신뢰도 {value.toFixed(2)}
    </span>
  );
}

function EditedBadge() {
  return (
    <span className="rounded-full bg-[#00c7a9]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[#00967f]">
      수정됨
    </span>
  );
}

function MethodBadge({ method }: { method: "rule" | "llm" }) {
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5 text-[10px] font-medium",
        method === "rule"
          ? "border-slate-200 bg-slate-50 text-slate-500"
          : "border-blue-100 bg-blue-50 text-blue-500",
      )}
    >
      {method === "rule" ? "규칙" : "AI"}
    </span>
  );
}

interface DetailPaneProps {
  item: HitlItem;
  onDone: (voucherId: number) => void;
}

function DetailPane({ item, onDone }: DetailPaneProps) {
  const [scope, setScope] = useState<string>(item.scope !== null ? String(item.scope) : "");
  const [category, setCategory] = useState(item.category ?? "");
  const [fuel, setFuel] = useState(item.fuel ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scopeDirty = scope !== String(item.scope ?? "");
  const categoryDirty = category !== (item.category ?? "");
  const fuelDirty = fuel !== (item.fuel ?? "");
  const hasEdits = scopeDirty || categoryDirty || fuelDirty;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onDone(item.voucher_id);
    } catch (err) {
      // 실패를 무음 처리하지 않는다 — 인라인 에러 + 재시도 가능 상태 유지
      console.error("담당자 조치 실패:", err);
      setError("처리에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      setBusy(false);
    }
  }

  const handleConfirm = () =>
    run(() =>
      hasEdits
        ? editVoucher(item.voucher_id, {
            scope: scope ? Number(scope) : null,
            category,
            fuel_type: fuel,
          })
        : confirmVoucher(item.voucher_id),
    );

  const handleReject = () => run(() => rejectVoucher(item.voucher_id));

  const selectCls =
    "w-full rounded-lg border border-[#e8eaed] bg-white px-3 py-2 text-sm text-[#222222] transition-colors focus:border-[#00c7a9] focus:outline-none focus:ring-2 focus:ring-[#00c7a9]";

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto pr-1">
      {/* 1. 전표 원문 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#9ca3af]">전표 원문</h4>
        <div className="space-y-2 rounded-xl border border-[#e8eaed] bg-[#f7f8fa] p-4">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-[#222222]">{item.raw}</span>
            <MethodBadge method={item.method} />
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <div>
              <span className="text-[#9ca3af]">공급가액</span>
              <span className="ml-2 font-semibold text-[#222222]">
                {item.amount_krw != null ? `${item.amount_krw.toLocaleString("ko-KR")}원` : "—"}
              </span>
            </div>
            <div>
              <span className="text-[#9ca3af]">발행월</span>
              <span className="ml-2 font-semibold text-[#222222]">{item.month}월</span>
            </div>
            <div>
              <span className="text-[#9ca3af]">기업</span>
              <span className="ml-2 font-semibold text-[#222222]">{item.company_name}</span>
            </div>
            <div>
              <span className="text-[#9ca3af]">출처</span>
              <span className="ml-2 font-semibold text-[#222222]">
                {item.scope === 2 ? "kepco" : "hometax"}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 2. 검토가 필요한 이유 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#9ca3af]">
          검토가 필요한 이유
        </h4>
        <div className="space-y-2 rounded-xl border border-[#d1b5ff]/60 bg-[#d1b5ff]/10 p-4">
          <div className="flex items-center gap-2">
            <ConfidenceBadge value={item.confidence} />
            <MethodBadge method={item.method} />
            {item.method === "rule" && (
              <span className="text-[11px] text-[#9ca3af]">규칙 분류 경로 적용</span>
            )}
          </div>
          <p className="text-sm leading-relaxed text-[#222222]">{item.evidence ?? "판단 근거 없음"}</p>
          <div className="mt-1 text-xs font-medium text-[#7a4fd9]">
            {item.confidence < 0.5
              ? "→ 담당자 확인 필요: 연료종류 또는 활동 유형 불확실"
              : "→ 검토 권장: 경계값 근처의 분류"}
          </div>
        </div>
      </section>

      {/* 3. AI 분류 결과 (수정 가능) */}
      <section>
        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#9ca3af]">
          AI 분류 결과 (수정 가능)
        </h4>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-[#666666]">
              Scope
              {scopeDirty && <EditedBadge />}
            </label>
            <select className={selectCls} value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">미분류</option>
              <option value="1">Scope 1 (직접)</option>
              <option value="2">Scope 2 (간접)</option>
            </select>
          </div>
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-[#666666]">
              카테고리
              {categoryDirty && <EditedBadge />}
            </label>
            <select className={selectCls} value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">미분류</option>
              {CATEGORY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-[#666666]">
              연료 종류
              {fuelDirty && <EditedBadge />}
            </label>
            <select className={selectCls} value={fuel} onChange={(e) => setFuel(e.target.value)}>
              <option value="">미분류</option>
              {FUEL_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <span className="text-xs text-[#9ca3af]">공급가액</span>
          <span className="text-sm font-semibold text-[#222222]">
            {item.amount_krw != null ? `${item.amount_krw.toLocaleString("ko-KR")}원` : "—"}
          </span>
          <span className="text-xs text-[#9ca3af]">(읽기 전용)</span>
        </div>
      </section>

      {/* 4. Actions */}
      <section className="mt-auto border-t border-[#e8eaed] pt-4">
        {error && (
          <div className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-[12px] text-red-600">{error}</div>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={handleConfirm}
            disabled={busy}
            className="min-w-[120px] flex-1 rounded-lg bg-[#00c7a9] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#00967f] disabled:opacity-60"
          >
            {busy ? "처리 중…" : hasEdits ? "수정 확정" : "확정"}
          </button>
          <button
            onClick={handleReject}
            disabled={busy}
            className="min-w-[100px] flex-1 rounded-lg border border-[#e8eaed] bg-white px-4 py-2.5 text-sm font-semibold text-[#666666] transition-colors hover:bg-slate-50 disabled:opacity-60"
          >
            반려
          </button>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-[#9ca3af]">
          확정 시 &quot;담당자 검토 완료&quot; 이력이 기록됩니다. AI는 이 값을 단독으로 변경할 수 없습니다 —
          보조수단성 원칙 (AI = 1차 선별, 담당자 = 최종 판단).
        </p>
      </section>
    </div>
  );
}

export function HitlWorkspace({ initialQueue }: { initialQueue: HitlItem[] }) {
  const [queue, setQueue] = useState<HitlItem[]>(initialQueue);
  const [selectedId, setSelectedId] = useState<number | null>(initialQueue[0]?.voucher_id ?? null);
  const [filterCompany, setFilterCompany] = useState("전체");
  const [filterFuel, setFilterFuel] = useState("전체");
  const [filterConfidence, setFilterConfidence] = useState("전체");
  const [sortBy, setSortBy] = useState<"confidence" | "month">("confidence");

  const companies = useMemo(
    () => ["전체", ...Array.from(new Set(queue.map((i) => i.company_name)))],
    [queue],
  );
  const fuels = useMemo(
    () => ["전체", ...Array.from(new Set(initialQueue.map((i) => i.fuel ?? "미분류")))],
    [initialQueue],
  );

  const filtered = useMemo(() => {
    let list = [...queue];
    if (filterCompany !== "전체") list = list.filter((i) => i.company_name === filterCompany);
    if (filterFuel !== "전체") list = list.filter((i) => (i.fuel ?? "미분류") === filterFuel);
    if (filterConfidence === "0.0–0.5") list = list.filter((i) => i.confidence < 0.5);
    if (filterConfidence === "0.5–0.65")
      list = list.filter((i) => i.confidence >= 0.5 && i.confidence < 0.65);
    if (filterConfidence === "0.65+") list = list.filter((i) => i.confidence >= 0.65);
    list.sort((a, b) => (sortBy === "confidence" ? a.confidence - b.confidence : a.month - b.month));
    return list;
  }, [queue, filterCompany, filterFuel, filterConfidence, sortBy]);

  const selected = queue.find((i) => i.voucher_id === selectedId) ?? null;

  function removeItem(voucherId: number) {
    setQueue((prev) => {
      const next = prev.filter((i) => i.voucher_id !== voucherId);
      setSelectedId((cur) => (cur === voucherId ? next[0]?.voucher_id ?? null : cur));
      return next;
    });
  }

  const selectCls =
    "rounded-lg border border-[#e8eaed] bg-white px-2.5 py-1.5 text-xs text-[#666666] transition-colors focus:outline-none focus:ring-1 focus:ring-[#00c7a9]";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[#e8eaed] bg-white shadow-card">
      <div className="flex items-center justify-between gap-4 border-b border-[#e8eaed] px-6 py-4">
        <div>
          <h2 className="text-base font-semibold text-[#222222]">담당자 검토</h2>
          <p className="mt-0.5 text-xs text-[#9ca3af]">담당자 검토 대기 {queue.length}건</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className={selectCls} value={filterCompany} onChange={(e) => setFilterCompany(e.target.value)}>
            {companies.map((c) => (
              <option key={c} value={c}>
                {c === "전체" ? "기업 전체" : c}
              </option>
            ))}
          </select>
          <select className={selectCls} value={filterFuel} onChange={(e) => setFilterFuel(e.target.value)}>
            {fuels.map((f) => (
              <option key={f} value={f}>
                {f === "전체" ? "연료 전체" : f}
              </option>
            ))}
          </select>
          <select
            className={selectCls}
            value={filterConfidence}
            onChange={(e) => setFilterConfidence(e.target.value)}
          >
            <option value="전체">신뢰도 전체</option>
            <option value="0.0–0.5">0.0 – 0.5 (긴급)</option>
            <option value="0.5–0.65">0.5 – 0.65 (주의)</option>
            <option value="0.65+">0.65 이상</option>
          </select>
          <select
            className={selectCls}
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "confidence" | "month")}
          >
            <option value="confidence">신뢰도 낮은 순</option>
            <option value="month">발행월 순</option>
          </select>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="w-72 flex-shrink-0 overflow-y-auto border-r border-[#e8eaed] bg-[#f7f8fa] xl:w-80">
          {filtered.length === 0 ? (
            <div className="flex h-40 flex-col items-center justify-center text-sm text-[#9ca3af]">
              검토 항목 없음
            </div>
          ) : (
            filtered.map((item) => (
              <button
                key={item.voucher_id}
                onClick={() => setSelectedId(item.voucher_id)}
                className={cn(
                  "w-full border-b border-[#e8eaed] px-4 py-3.5 text-left transition-colors",
                  selectedId === item.voucher_id
                    ? "border-l-2 border-l-[#00c7a9] bg-[#e3faf5]"
                    : "hover:bg-white",
                )}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold text-[#222222]">
                    {item.company_name}
                  </span>
                  <ConfidenceBadge value={item.confidence} />
                </div>
                <div className="truncate text-sm font-medium text-[#222222]">{item.raw}</div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-xs text-[#9ca3af]">{item.fuel || "미분류"}</span>
                  <span className="text-xs text-[#9ca3af]">·</span>
                  <span className="text-xs text-[#9ca3af]">{item.month}월</span>
                  <MethodBadge method={item.method} />
                </div>
              </button>
            ))
          )}
        </div>

        <div className="flex-1 overflow-hidden">
          {selected ? (
            <div className="h-full p-6">
              <DetailPane key={selected.voucher_id} item={selected} onDone={removeItem} />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[#9ca3af]">
              좌측에서 항목을 선택하세요
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
