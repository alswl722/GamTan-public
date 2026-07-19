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
        isLow && "bg-hitl/30 text-hitl-ink",
        isMid && "bg-hitl/15 text-hitl-ink",
        !isLow && !isMid && "bg-brand-soft text-brand-ink",
      )}
    >
      신뢰도 {value.toFixed(2)}
    </span>
  );
}

function EditedBadge() {
  return (
    <span className="rounded-full bg-brand/15 px-1.5 py-0.5 text-[10px] font-semibold text-brand-ink">
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
          ? "border-line bg-bg text-muted"
          : "border-scope2/40 bg-scope2/15 text-ink",
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
    "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink transition-colors focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand";

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto pr-1">
      {/* 1. 전표 원문 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">전표 원문</h4>
        <div className="space-y-2 rounded-md border border-line bg-bg p-4">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-ink">{item.raw}</span>
            <MethodBadge method={item.method} />
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <div>
              <span className="text-faint">공급가액</span>
              <span className="ml-2 font-semibold text-ink">
                {item.amount_krw != null ? `${item.amount_krw.toLocaleString("ko-KR")}원` : "—"}
              </span>
            </div>
            <div>
              <span className="text-faint">발행월</span>
              <span className="ml-2 font-semibold text-ink">{item.month}월</span>
            </div>
            <div>
              <span className="text-faint">기업</span>
              <span className="ml-2 font-semibold text-ink">{item.company_name}</span>
            </div>
            <div>
              <span className="text-faint">출처</span>
              <span className="ml-2 font-semibold text-ink">
                {item.scope === 2 ? "kepco" : "hometax"}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 2. 검토가 필요한 이유 */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">
          검토가 필요한 이유
        </h4>
        <div className="space-y-2 rounded-md border border-hitl/60 bg-hitl/10 p-4">
          <div className="flex items-center gap-2">
            <ConfidenceBadge value={item.confidence} />
            <MethodBadge method={item.method} />
            {item.method === "rule" && (
              <span className="text-[11px] text-faint">규칙 분류 경로 적용</span>
            )}
          </div>
          <p className="text-sm leading-relaxed text-ink">{item.evidence ?? "판단 근거 없음"}</p>
          <div className="mt-1 text-xs font-medium text-hitl-ink">
            {item.confidence < 0.5
              ? "→ 담당자 확인 필요: 연료종류 또는 활동 유형 불확실"
              : "→ 검토 권장: 경계값 근처의 분류"}
          </div>
        </div>
      </section>

      {/* 3. AI 분류 결과 (수정 가능) */}
      <section>
        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-faint">
          AI 분류 결과 (수정 가능)
        </h4>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
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
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
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
            <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
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
          <span className="text-xs text-faint">공급가액</span>
          <span className="text-sm font-semibold text-ink">
            {item.amount_krw != null ? `${item.amount_krw.toLocaleString("ko-KR")}원` : "—"}
          </span>
          <span className="text-xs text-faint">(읽기 전용)</span>
        </div>
      </section>

      {/* 4. Actions */}
      <section className="mt-auto border-t border-line pt-4">
        {error && (
          <div className="mb-2 rounded-md bg-hitl/20 px-3 py-2 text-[12px] text-hitl-ink">{error}</div>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={handleConfirm}
            disabled={busy}
            className="min-w-[120px] flex-1 rounded-md bg-brand px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-ink disabled:opacity-60"
          >
            {busy ? "처리 중…" : hasEdits ? "수정 확정" : "확정"}
          </button>
          <button
            onClick={handleReject}
            disabled={busy}
            className="min-w-[100px] flex-1 rounded-md border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-muted transition-colors hover:bg-bg disabled:opacity-60"
          >
            반려
          </button>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-faint">
          확정 시 &quot;담당자 검토 완료&quot; 이력이 기록됩니다. AI는 이 값을 단독으로 변경할 수 없습니다 —
          보조수단성 원칙 (AI = 1차 선별, 담당자 = 최종 판단).
        </p>
      </section>
    </div>
  );
}

interface CompanySummary {
  name: string;
  count: number;
  minConfidence: number;
}

function CompanyList({
  companies,
  selected,
  onSelect,
  collapsed,
  onToggleCollapsed,
}: {
  companies: CompanySummary[];
  selected: string | null;
  onSelect: (name: string) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  if (collapsed) {
    return (
      <div className="flex w-14 flex-shrink-0 flex-col overflow-y-auto border-r border-line bg-bg">
        <button
          onClick={onToggleCollapsed}
          className="flex items-center justify-center border-b border-line py-3 text-faint transition-colors hover:text-ink"
          aria-label="기업 목록 펼치기"
          title="기업 목록 펼치기"
        >
          »
        </button>
        {companies.map((c) => (
          <button
            key={c.name}
            onClick={() => onSelect(c.name)}
            title={`${c.name} (${c.count}건)`}
            className={cn(
              "relative flex flex-col items-center gap-1 border-b border-line py-3 transition-colors",
              selected === c.name ? "border-l-2 border-l-brand bg-brand-soft" : "hover:bg-line/40",
            )}
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-line text-[11px] font-semibold text-ink">
              {c.name.slice(0, 1)}
            </span>
            <span className="text-[10px] font-semibold text-muted">{c.count}</span>
            {c.minConfidence < 0.5 && (
              <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-hitl-ink" />
            )}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="w-56 flex-shrink-0 overflow-y-auto border-r border-line bg-bg">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-faint">기업</h3>
        <button
          onClick={onToggleCollapsed}
          className="text-faint transition-colors hover:text-ink"
          aria-label="기업 목록 접기"
          title="기업 목록 접기"
        >
          «
        </button>
      </div>
      {companies.map((c) => (
        <button
          key={c.name}
          onClick={() => onSelect(c.name)}
          className={cn(
            "flex w-full items-center justify-between gap-2 border-b border-line px-4 py-3 text-left transition-colors",
            selected === c.name ? "border-l-2 border-l-brand bg-brand-soft" : "hover:bg-line/40",
          )}
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-ink">{c.name}</div>
            {c.minConfidence < 0.5 && (
              <div className="mt-0.5 text-[10px] font-medium text-hitl-ink">긴급 건 포함</div>
            )}
          </div>
          <span className="flex-shrink-0 rounded-full bg-line px-2 py-0.5 text-[11px] font-semibold text-muted">
            {c.count}
          </span>
        </button>
      ))}
    </div>
  );
}

export function HitlWorkspace({ initialQueue }: { initialQueue: HitlItem[] }) {
  const [queue, setQueue] = useState<HitlItem[]>(initialQueue);
  const [selectedCompany, setSelectedCompany] = useState<string | null>(
    initialQueue[0]?.company_name ?? null,
  );
  const [selectedId, setSelectedId] = useState<number | null>(initialQueue[0]?.voucher_id ?? null);
  const [filterFuel, setFilterFuel] = useState("전체");
  const [filterConfidence, setFilterConfidence] = useState("전체");
  const [sortBy, setSortBy] = useState<"confidence" | "month">("confidence");
  const [companyListCollapsed, setCompanyListCollapsed] = useState(false);

  const companies = useMemo<CompanySummary[]>(() => {
    const byCompany = new Map<string, HitlItem[]>();
    for (const item of queue) {
      const list = byCompany.get(item.company_name) ?? [];
      list.push(item);
      byCompany.set(item.company_name, list);
    }
    return Array.from(byCompany.entries())
      .map(([name, items]) => ({
        name,
        count: items.length,
        minConfidence: Math.min(...items.map((i) => i.confidence)),
      }))
      .sort((a, b) => a.minConfidence - b.minConfidence);
  }, [queue]);

  const fuels = useMemo(
    () => ["전체", ...Array.from(new Set(initialQueue.map((i) => i.fuel ?? "미분류")))],
    [initialQueue],
  );

  const companyQueue = useMemo(
    () => queue.filter((i) => i.company_name === selectedCompany),
    [queue, selectedCompany],
  );

  const filtered = useMemo(() => {
    let list = [...companyQueue];
    if (filterFuel !== "전체") list = list.filter((i) => (i.fuel ?? "미분류") === filterFuel);
    if (filterConfidence === "0.0–0.5") list = list.filter((i) => i.confidence < 0.5);
    if (filterConfidence === "0.5–0.65")
      list = list.filter((i) => i.confidence >= 0.5 && i.confidence < 0.65);
    if (filterConfidence === "0.65+") list = list.filter((i) => i.confidence >= 0.65);
    list.sort((a, b) => (sortBy === "confidence" ? a.confidence - b.confidence : a.month - b.month));
    return list;
  }, [companyQueue, filterFuel, filterConfidence, sortBy]);

  const selected = queue.find((i) => i.voucher_id === selectedId) ?? null;

  function selectCompany(name: string) {
    setSelectedCompany(name);
    const first = queue.find((i) => i.company_name === name);
    setSelectedId(first?.voucher_id ?? null);
  }

  function removeItem(voucherId: number) {
    setQueue((prev) => {
      const next = prev.filter((i) => i.voucher_id !== voucherId);
      setSelectedId((cur) => {
        if (cur !== voucherId) return cur;
        const nextInCompany = next.find((i) => i.company_name === selectedCompany);
        if (nextInCompany) return nextInCompany.voucher_id;
        // 해당 기업 큐가 비면 다음 기업으로 자동 이동
        const nextCompany = next[0];
        setSelectedCompany(nextCompany?.company_name ?? null);
        return nextCompany?.voucher_id ?? null;
      });
      return next;
    });
  }

  const selectCls =
    "rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-muted transition-colors focus:outline-none focus:ring-1 focus:ring-brand";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between gap-4 border-b border-line px-6 py-4">
        <div>
          <h2 className="text-base font-semibold text-ink">담당자 검토</h2>
          <p className="mt-0.5 text-xs text-faint">
            담당자 검토 대기 {queue.length}건 · {companies.length}개 기업
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
        <CompanyList
          companies={companies}
          selected={selectedCompany}
          onSelect={selectCompany}
          collapsed={companyListCollapsed}
          onToggleCollapsed={() => setCompanyListCollapsed((v) => !v)}
        />

        <div className="w-72 flex-shrink-0 overflow-y-auto border-r border-line bg-bg xl:w-80">
          {filtered.length === 0 ? (
            <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
              검토 항목 없음
            </div>
          ) : (
            filtered.map((item) => (
              <button
                key={item.voucher_id}
                onClick={() => setSelectedId(item.voucher_id)}
                className={cn(
                  "w-full border-b border-line px-4 py-3.5 text-left transition-colors",
                  selectedId === item.voucher_id
                    ? "border-l-2 border-l-brand bg-brand-soft"
                    : "hover:bg-bg",
                )}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-ink">{item.raw}</span>
                  <ConfidenceBadge value={item.confidence} />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-faint">{item.fuel || "미분류"}</span>
                  <span className="text-xs text-faint">·</span>
                  <span className="text-xs text-faint">{item.month}월</span>
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
            <div className="flex h-full items-center justify-center text-sm text-faint">
              좌측에서 항목을 선택하세요
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
