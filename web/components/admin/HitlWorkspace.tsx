"use client";

// 실API: GET /admin/hitl → queue (검토 대기 + 확정·미전송 건)
// 실API: PATCH /admin/classifications/{id}/confirm | /{id} (수정) | /{id}/reject
// 실API: POST /admin/companies/{id}/send-classifications
//
// 담당자가 확정해도 이 작업대에서 즉시 사라지지 않는다 — "검토 완료" 표시만
// 남기고, 기업별로 모아 "전송" 버튼을 눌러야 사장님 화면에 실제로 노출된다.

import { useEffect, useMemo, useState } from "react";
import { Check } from "lucide-react";
import {
  bulkConfirm,
  bulkReject,
  confirmVoucher,
  documentFileUrl,
  editVoucher,
  rejectVoucher,
  sendClassificationsToOwner,
} from "@/lib/admin-data";
import type { HitlItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

// 별도 로그인 체계 도입 전 임시 열람자 식별자.
const VIEWED_BY = "은행 담당자";

/** 전표 원본 미리보기 — 파일이 없거나(구 레코드) 서버 오류가 나면 폴백 텍스트를
 * 보여준다. <iframe onError>는 크로스 오리진 응답 상태코드를 못 잡으므로 렌더링
 * 전에 먼저 존재 여부와 실제 파일 종류를 확인한다(GET — 서버가 이 라우트에 HEAD를
 * 노출하지 않는다). 원본은 PDF만이 아니라 사장님이 찍은 사진(JPEG/PNG/HEIC 등)일
 * 수도 있다(CLAUDE.md §7 업로드 3종) — Content-Type으로 실제 종류를 판별해
 * 이미지는 <img>로, 그 외는 <iframe>(PDF 뷰어)으로 렌더링한다. */
function DocumentPreview({ documentId }: { documentId: number }) {
  const [state, setState] = useState<
    { kind: "loading" } | { kind: "missing" } | { kind: "ok"; isImage: boolean }
  >({ kind: "loading" });
  const url = documentFileUrl(documentId, VIEWED_BY);

  useEffect(() => {
    let alive = true;
    setState({ kind: "loading" });
    fetch(url)
      .then((res) => {
        if (!alive) return;
        if (!res.ok) {
          setState({ kind: "missing" });
          return;
        }
        const contentType = res.headers.get("content-type") ?? "";
        setState({ kind: "ok", isImage: contentType.startsWith("image/") });
      })
      .catch(() => alive && setState({ kind: "missing" }));
    return () => {
      alive = false;
    };
  }, [url]);

  if (state.kind === "loading") {
    return (
      <div className="flex h-[32rem] items-center justify-center text-xs text-faint">
        불러오는 중…
      </div>
    );
  }

  if (state.kind === "missing") {
    return (
      <div className="flex h-[32rem] flex-col items-center justify-center gap-1 text-xs text-faint">
        <span>원본 파일을 찾을 수 없어요</span>
        <span>
          이 문서는 파일 저장 기능 도입 이전에 등록됐거나 삭제됐을 수 있어요
        </span>
      </div>
    );
  }

  return (
    <>
      <div className="mb-2 flex items-center justify-between">
        <span className="rounded bg-line px-1.5 py-0.5 text-[10px] font-semibold text-muted">
          {state.isImage ? "이미지" : "PDF"}
        </span>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-brand-ink hover:underline"
        >
          원본 크게 보기 →
        </a>
      </div>
      {state.isImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- 원격 API가 서빙하는 원본 파일이라 next/image 최적화 대상이 아님
        <img
          src={url}
          className="h-[32rem] w-full rounded border border-line bg-white object-contain"
          alt="전표 원본"
        />
      ) : (
        <iframe
          src={url}
          className="h-[32rem] w-full rounded border border-line bg-white"
          title="전표 원본 PDF"
        />
      )}
    </>
  );
}

const CATEGORY_OPTIONS = [
  "고정연소",
  "이동연소",
  "간접배출",
  "공정배출",
  "기타",
];
const FUEL_OPTIONS = [
  "경유",
  "휘발유",
  "등유",
  "중유",
  "천연가스",
  "도시가스",
  "LPG",
  "전기",
  "스팀",
  "기타",
];

function ConfidenceBadge({ value }: { value: number }) {
  const isLow = value < 0.5;
  const isMid = value >= 0.5 && value < 0.65;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        isLow && "border-hitl-ink/30 bg-hitl/30 text-hitl-ink",
        isMid && "border-hitl-ink/20 bg-hitl/15 text-hitl-ink",
        !isLow && !isMid && "border-brand-ink/25 bg-brand-soft text-brand-ink",
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

function StatusBadge({
  status,
  edited,
}: {
  status: "review_required" | "confirmed";
  /** 확정 시 값을 고쳤으면 "수정됨"으로, 그대로 확정했으면 "확정됨"으로 표시. */
  edited?: boolean;
}) {
  const label =
    status === "confirmed" ? (edited ? "수정됨" : "확정됨") : "검토 대기";
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        status === "confirmed"
          ? "border-brand-ink/25 bg-brand-soft text-brand-ink"
          : "border-hitl-ink/30 bg-hitl/30 text-hitl-ink",
      )}
    >
      {label}
    </span>
  );
}

interface DetailPaneProps {
  item: HitlItem;
  /** 확정은 큐에 "검토 완료"로 남기고(mode: "confirm"), 반려는 큐에서 뺀다(mode: "reject"). */
  onDone: (voucherId: number, mode: "confirm" | "reject") => void;
}

function DetailPane({ item, onDone }: DetailPaneProps) {
  const isConfirmed = item.status === "confirmed";
  const [scope, setScope] = useState<string>(
    item.scope !== null ? String(item.scope) : "",
  );
  const [category, setCategory] = useState(item.category ?? "");
  const [fuel, setFuel] = useState(item.fuel ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scopeDirty = scope !== String(item.scope ?? "");
  const categoryDirty = category !== (item.category ?? "");
  const fuelDirty = fuel !== (item.fuel ?? "");
  const hasEdits = scopeDirty || categoryDirty || fuelDirty;

  // evidence는 "AI 판단 근거 | 담당자 조치"로 누적된다(아직 조치 전이면 " | "가
  // 없어 원본 판단 근거만 있다) — 원본만 판단 근거 박스에 보여주고, 담당자 조치는
  // 뱃지로만 표시한다("담당자 수정: ..." 같은 문장은 숨김).
  const evidenceSplitIdx = (item.evidence ?? "").lastIndexOf(" | ");
  const evidenceOriginal =
    evidenceSplitIdx === -1 ? item.evidence : item.evidence!.slice(0, evidenceSplitIdx);
  const evidenceAction =
    evidenceSplitIdx === -1 ? null : item.evidence!.slice(evidenceSplitIdx + 3);
  const actionKind: "confirmed" | "edited" | null = !evidenceAction
    ? null
    : evidenceAction.startsWith("담당자 수정")
      ? "edited"
      : evidenceAction.startsWith("담당자")
        ? "confirmed"
        : null;

  // 기업이 체크한 연료만 보여준다(CLAUDE.md §5 원칙6) — 단, AI가 이미 판정한 현재
  // 값은 체크 목록에 없어도 항상 옵션에 남긴다. 그래야 "체크 안 한 연료로 잘못
  // 분류된 건"을 담당자가 보고 다른 값으로 고칠 수 있다(필터가 오류를 숨기면 안 됨).
  const allowedFuels = item.company_fuel_types
    ? new Set([...(item.fuel ? [item.fuel] : []), ...item.company_fuel_types])
    : null;
  const fuelOptions = allowedFuels
    ? FUEL_OPTIONS.filter((f) => allowedFuels.has(f))
    : FUEL_OPTIONS;

  async function run(action: () => Promise<unknown>, mode: "confirm" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await action();
      onDone(item.voucher_id, mode);
    } catch (err) {
      // 실패를 무음 처리하지 않는다 — 인라인 에러 + 재시도 가능 상태 유지
      console.error("담당자 조치 실패:", err);
      setError("처리에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      setBusy(false);
    }
  }

  const handleConfirm = () =>
    run(
      () =>
        hasEdits
          ? editVoucher(item.voucher_id, {
              scope: scope ? Number(scope) : null,
              category,
              fuel_type: fuel,
            })
          : confirmVoucher(item.voucher_id),
      "confirm",
    );

  const handleReject = () => run(() => rejectVoucher(item.voucher_id), "reject");

  const selectCls =
    "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink transition-colors focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand";

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-6 overflow-hidden">
        {/* 좌측: 전표 원문 요약 + 검토가 필요한 이유 + AI 분류 결과 */}
        <div className="flex h-full flex-col gap-5 overflow-y-auto pr-1">
          {/* 1. 전표 원문 */}
          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">
              전표 원문
            </h4>
            <div className="space-y-2 rounded-md border border-line bg-bg p-4">
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-ink">{item.raw}</span>
                <MethodBadge method={item.method} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <div>
                  <span className="text-faint">공급가액</span>
                  <span className="ml-2 font-semibold text-ink">
                    {item.amount_krw != null
                      ? `${item.amount_krw.toLocaleString("ko-KR")}원`
                      : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-faint">발행월</span>
                  <span className="ml-2 font-semibold text-ink">
                    {item.month}월
                  </span>
                </div>
                <div>
                  <span className="text-faint">기업</span>
                  <span className="ml-2 font-semibold text-ink">
                    {item.company_name}
                  </span>
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

          {/* 2. 판단 근거 / 계산 실패 사유 / 담당자 조치 — 성격이 다른 정보라 구역을 나눈다 */}
          <section>
            <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-faint">
              검토가 필요한 이유
              <StatusBadge status={item.status} edited={actionKind === "edited"} />
            </h4>
            <div className="space-y-2">
              <div className="rounded-md border border-hitl/60 bg-hitl/10 p-4">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="text-[11px] font-semibold text-muted">AI 판단 근거</span>
                  <ConfidenceBadge value={item.confidence} />
                </div>
                <p className="text-sm leading-relaxed text-ink">
                  {evidenceOriginal ?? "판단 근거 없음"}
                </p>
              </div>
              {item.calc_failure_reason && (
                <div className="rounded-md border border-line bg-bg p-4">
                  <span className="mb-1.5 block text-[11px] font-semibold text-muted">
                    계산 실패 사유
                  </span>
                  <p className="text-sm leading-relaxed text-ink">
                    {item.calc_failure_reason}
                  </p>
                </div>
              )}
              {item.anomaly_check_status && item.anomaly_check_status !== "pending" && (
                <div
                  className={cn(
                    "rounded-md border p-4",
                    item.anomaly_check_status === "confirmed_normal"
                      ? "border-brand/40 bg-brand-soft/40"
                      : "border-hitl/60 bg-hitl/10",
                  )}
                >
                  <span
                    className={cn(
                      "mb-1.5 block text-[11px] font-semibold",
                      item.anomaly_check_status === "confirmed_normal" ? "text-brand-ink" : "text-hitl-ink",
                    )}
                  >
                    이상치 확인 — 사장님 답변 (참고용)
                    {item.anomaly_ratio && ` · 평월 대비 ${item.anomaly_ratio}배`}
                  </span>
                  <p className="text-sm leading-relaxed text-ink">
                    {item.anomaly_check_status === "confirmed_normal" && "네, 정상이에요"}
                    {item.anomaly_check_status === "disputed" && "아니요, 확인해볼게요"}
                    {item.anomaly_check_status === "unknown" && "모르겠어요"}
                    {item.anomaly_check_reason && ` — "${item.anomaly_check_reason}"`}
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* 3. 분류 (전송 전까지는 확정 건도 수정 가능) */}
          <section>
            <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-faint">
              분류
            </h4>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
                  Scope
                  {scopeDirty && <EditedBadge />}
                </label>
                <select
                  className={selectCls}
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                >
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
                <select
                  className={selectCls}
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
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
                <select
                  className={selectCls}
                  value={fuel}
                  onChange={(e) => setFuel(e.target.value)}
                >
                  <option value="">미분류</option>
                  {fuelOptions.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                {item.company_fuel_types && (
                  <p className="mt-1 text-[11px] text-faint">
                    {item.company_name}이(가) 체크한 연료만 표시됩니다
                  </p>
                )}
              </div>
            </div>
          </section>

          {/* 4. Actions — 전송 전까지는 확정 건도 재확정·반려 가능 */}
          <section className="mt-auto border-t border-line pt-4">
            {error && (
              <div className="mb-2 rounded-md bg-hitl/20 px-3 py-2 text-[12px] text-hitl-ink">
                {error}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleConfirm}
                disabled={busy}
                className="w-32 rounded-md bg-brand px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-ink disabled:opacity-60"
              >
                {busy
                  ? "처리 중…"
                  : hasEdits
                    ? "수정 확정"
                    : isConfirmed
                      ? "확정됨"
                      : "확정"}
              </button>
              <button
                onClick={handleReject}
                disabled={busy}
                className="w-32 rounded-md border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-bg disabled:opacity-60"
              >
                반려
              </button>
            </div>
          </section>
        </div>

        {/* 우측: 원본 문서 — 좌측이 스크롤돼도 계속 보이도록 고정 */}
        <div className="h-full overflow-y-auto">
          <div className="sticky top-0">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">
              원본 문서
            </h4>
            <div className="rounded-md border border-line bg-bg p-4">
              {item.source_document_id ? (
                <DocumentPreview documentId={item.source_document_id} />
              ) : (
                <div className="flex h-[32rem] items-center justify-center text-xs text-faint">
                  원본 파일 없음
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface CompanySummary {
  name: string;
  count: number;
  minConfidence: number;
  /** 확정됐지만 아직 전송 안 한 건수 — 0보다 크면 "전송" 버튼을 강조. */
  confirmedCount: number;
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
              selected === c.name
                ? "border-l-2 border-l-brand bg-brand-soft"
                : "hover:bg-line/40",
            )}
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-line text-[11px] font-semibold text-ink">
              {c.name.slice(0, 1)}
            </span>
            <span className="text-[10px] font-semibold text-muted">
              {c.count}
            </span>
            {c.minConfidence < 0.5 && (
              <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-hitl-ink" />
            )}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="w-48 flex-shrink-0 overflow-y-auto border-r border-line bg-bg">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-faint">
          기업
        </h3>
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
            selected === c.name
              ? "border-l-2 border-l-brand bg-brand-soft"
              : "hover:bg-line/40",
          )}
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-ink">
              {c.name}
            </div>
            {c.minConfidence < 0.5 && (
              <div className="mt-0.5 text-[10px] font-medium text-hitl-ink">
                긴급 건 포함
              </div>
            )}
            {c.confirmedCount > 0 && (
              <div className="mt-0.5 text-[10px] font-medium text-brand-ink">
                전송 대기 {c.confirmedCount}건
              </div>
            )}
          </div>
          <span className="flex-shrink-0 rounded-full bg-line px-2 py-0.5 text-[11px] font-semibold text-ink">
            {c.count}
          </span>
        </button>
      ))}
    </div>
  );
}

export function HitlWorkspace({
  initialQueue,
  onChanged,
}: {
  initialQueue: HitlItem[];
  /** 확정/수정/반려(단건·일괄)가 성공할 때마다 호출 — 변경 이력 탭을 최신으로 유지. */
  onChanged?: () => void;
}) {
  const [queue, setQueue] = useState<HitlItem[]>(initialQueue);
  const [selectedCompany, setSelectedCompany] = useState<string | null>(
    initialQueue[0]?.company_name ?? null,
  );
  const [selectedId, setSelectedId] = useState<number | null>(
    initialQueue[0]?.voucher_id ?? null,
  );
  const [filterFuel, setFilterFuel] = useState("전체");
  const [filterConfidence, setFilterConfidence] = useState("전체");
  const [filterMonth, setFilterMonth] = useState("전체");
  const [filterSearch, setFilterSearch] = useState("");
  const [sortBy, setSortBy] = useState<"confidence" | "month">("confidence");
  const [companyListCollapsed, setCompanyListCollapsed] = useState(false);
  const [voucherListCollapsed, setVoucherListCollapsed] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

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
        confirmedCount: items.filter((i) => i.status === "confirmed").length,
      }))
      .sort((a, b) => a.minConfidence - b.minConfidence);
  }, [queue]);

  const selectedCompanyId = queue.find((i) => i.company_name === selectedCompany)?.company_id ?? null;
  const selectedCompanyConfirmedCount =
    companies.find((c) => c.name === selectedCompany)?.confirmedCount ?? 0;

  const fuels = useMemo(
    () => [
      "전체",
      ...Array.from(new Set(initialQueue.map((i) => i.fuel ?? "미분류"))),
    ],
    [initialQueue],
  );

  const months = useMemo(
    () =>
      Array.from(new Set(initialQueue.map((i) => i.month))).sort(
        (a, b) => a - b,
      ),
    [initialQueue],
  );

  const companyQueue = useMemo(
    () => queue.filter((i) => i.company_name === selectedCompany),
    [queue, selectedCompany],
  );

  const filtered = useMemo(() => {
    let list = [...companyQueue];
    if (filterFuel !== "전체")
      list = list.filter((i) => (i.fuel ?? "미분류") === filterFuel);
    if (filterConfidence === "0.0–0.5")
      list = list.filter((i) => i.confidence < 0.5);
    if (filterConfidence === "0.5–0.65")
      list = list.filter((i) => i.confidence >= 0.5 && i.confidence < 0.65);
    if (filterConfidence === "0.65+")
      list = list.filter((i) => i.confidence >= 0.65);
    if (filterMonth !== "전체")
      list = list.filter((i) => i.month === Number(filterMonth));
    if (filterSearch.trim()) {
      const q = filterSearch.trim().toLowerCase();
      list = list.filter((i) => i.raw.toLowerCase().includes(q));
    }
    list.sort((a, b) =>
      sortBy === "confidence" ? a.confidence - b.confidence : a.month - b.month,
    );
    return list;
  }, [
    companyQueue,
    filterFuel,
    filterConfidence,
    filterMonth,
    filterSearch,
    sortBy,
  ]);

  const selected = queue.find((i) => i.voucher_id === selectedId) ?? null;

  function selectCompany(name: string) {
    setSelectedCompany(name);
    const first = queue.find((i) => i.company_name === name);
    setSelectedId(first?.voucher_id ?? null);
    setSelectedIds(new Set());
    setBulkError(null);
  }

  function toggleSelect(voucherId: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(voucherId)) next.delete(voucherId);
      else next.add(voucherId);
      return next;
    });
  }

  function toggleSelectAllFiltered() {
    setSelectedIds((prev) => {
      const allSelected =
        filtered.length > 0 && filtered.every((i) => prev.has(i.voucher_id));
      return allSelected
        ? new Set()
        : new Set(filtered.map((i) => i.voucher_id));
    });
  }

  async function runBulk(
    action: (ids: number[]) => ReturnType<typeof bulkConfirm>,
    mode: "confirm" | "reject",
  ) {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    try {
      const { results } = await action(ids);
      const succeeded = results.filter((r) => r.ok).map((r) => r.voucher_id);
      const failed = results.filter((r) => !r.ok);
      // 확정은 큐에 "검토 완료"로 남기고, 반려는 집계 제외 대상이라 큐에서 뺀다.
      if (mode === "confirm") succeeded.forEach((id) => markConfirmed(id));
      else succeeded.forEach((id) => removeItem(id));
      setSelectedIds(new Set(failed.map((r) => r.voucher_id)));
      if (failed.length > 0) {
        // 부분 실패를 숨기지 않는다 — 실패 건은 선택 상태로 남겨 재시도할 수 있게 한다
        setBulkError(
          `${failed.length}건 처리 실패(이미 처리됐거나 상태가 바뀐 건) — 선택은 유지됩니다.`,
        );
      }
    } catch (err) {
      console.error("일괄 처리 실패:", err);
      setBulkError(
        "일괄 처리 요청이 실패했습니다. 잠시 후 다시 시도해 주세요.",
      );
    } finally {
      setBulkBusy(false);
    }
  }

  const handleBulkConfirm = () => runBulk(bulkConfirm, "confirm");
  const handleBulkReject = () => runBulk(bulkReject, "reject");

  /** 확정 성공 — 큐에서 빼지 않고 status만 "confirmed"로 바꿔 "검토 완료" 표시만 남긴다. */
  function markConfirmed(voucherId: number) {
    onChanged?.();
    setQueue((prev) =>
      prev.map((i) =>
        i.voucher_id === voucherId ? { ...i, status: "confirmed" as const } : i,
      ),
    );
  }

  /** 반려 성공 — 집계 제외 대상이라 큐에서 완전히 뺀다. */
  function removeItem(voucherId: number) {
    onChanged?.();
    setQueue((prev) => {
      const next = prev.filter((i) => i.voucher_id !== voucherId);
      setSelectedId((cur) => {
        if (cur !== voucherId) return cur;
        const nextInCompany = next.find(
          (i) => i.company_name === selectedCompany,
        );
        if (nextInCompany) return nextInCompany.voucher_id;
        // 해당 기업 큐가 비면 다음 기업으로 자동 이동
        const nextCompany = next[0];
        setSelectedCompany(nextCompany?.company_name ?? null);
        return nextCompany?.voucher_id ?? null;
      });
      return next;
    });
  }

  async function handleSendToOwner() {
    if (selectedCompanyId === null) return;
    setSendBusy(true);
    setSendError(null);
    try {
      await sendClassificationsToOwner(selectedCompanyId);
      onChanged?.();
      // 전송된 건은 이제 검토 작업대에서 완전히 빠진다.
      setQueue((prev) => {
        const next = prev.filter(
          (i) => !(i.company_name === selectedCompany && i.status === "confirmed"),
        );
        setSelectedId((cur) => {
          const stillThere = next.find((i) => i.voucher_id === cur);
          if (stillThere) return cur;
          const nextInCompany = next.find((i) => i.company_name === selectedCompany);
          return nextInCompany?.voucher_id ?? next[0]?.voucher_id ?? null;
        });
        return next;
      });
    } catch (err) {
      console.error("전송 실패:", err);
      setSendError("전송에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSendBusy(false);
    }
  }

  const selectCls =
    "rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-ink transition-colors focus:outline-none focus:ring-1 focus:ring-brand";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between gap-4 border-b border-line px-6 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <select
            className={selectCls}
            value={filterFuel}
            onChange={(e) => setFilterFuel(e.target.value)}
          >
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
            value={filterMonth}
            onChange={(e) => setFilterMonth(e.target.value)}
          >
            <option value="전체">월 전체</option>
            {months.map((m) => (
              <option key={m} value={m}>
                {m}월
              </option>
            ))}
          </select>
          <select
            className={selectCls}
            value={sortBy}
            onChange={(e) =>
              setSortBy(e.target.value as "confidence" | "month")
            }
          >
            <option value="confidence">신뢰도 낮은 순</option>
            <option value="month">발행월 순</option>
          </select>
        </div>
        {selectedCompanyId !== null && selectedCompanyConfirmedCount > 0 && (
          <div className="flex flex-shrink-0 items-center gap-2">
            {sendError && (
              <span className="text-xs text-hitl-ink">{sendError}</span>
            )}
            <button
              type="button"
              onClick={handleSendToOwner}
              disabled={sendBusy}
              className="rounded-md bg-brand px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-ink disabled:opacity-60"
            >
              {sendBusy
                ? "전송 중…"
                : `${selectedCompany} 전송 (${selectedCompanyConfirmedCount}건)`}
            </button>
          </div>
        )}
      </div>

      {selectedIds.size > 0 && (
        <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-3 border-b border-line bg-brand-soft/40 px-6 py-2.5">
          <div className="flex items-center gap-3">
            <span className="text-xs font-semibold text-brand-ink">
              {selectedIds.size}건 선택됨
            </span>
            {bulkError && (
              <span className="text-xs text-hitl-ink">{bulkError}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              disabled={bulkBusy}
              className="rounded-md px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-ink disabled:opacity-60"
            >
              선택 해제
            </button>
            <button
              type="button"
              onClick={handleBulkReject}
              disabled={bulkBusy}
              className="rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-bg disabled:opacity-60"
            >
              일괄 반려
            </button>
            <button
              type="button"
              onClick={handleBulkConfirm}
              disabled={bulkBusy}
              className="rounded-md bg-brand px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-ink disabled:opacity-60"
            >
              {bulkBusy ? "처리 중…" : "일괄 확정"}
            </button>
          </div>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <CompanyList
          companies={companies}
          selected={selectedCompany}
          onSelect={selectCompany}
          collapsed={companyListCollapsed}
          onToggleCollapsed={() => setCompanyListCollapsed((v) => !v)}
        />

        {voucherListCollapsed ? (
          <div className="flex w-14 flex-shrink-0 flex-col overflow-y-auto border-r border-line bg-bg">
            <button
              onClick={() => setVoucherListCollapsed(false)}
              className="flex items-center justify-center border-b border-line py-3 text-faint transition-colors hover:text-ink"
              aria-label="전표 목록 펼치기"
              title="전표 목록 펼치기"
            >
              »
            </button>
            {filtered.map((item) => (
              <button
                key={item.voucher_id}
                onClick={() => setSelectedId(item.voucher_id)}
                title={`${item.raw} · ${item.fuel || "미분류"} · ${item.month}월`}
                className={cn(
                  "relative flex flex-col items-center gap-1 border-b border-line py-3 transition-colors",
                  selectedId === item.voucher_id
                    ? "border-l-2 border-l-brand bg-brand-soft"
                    : "hover:bg-line/40",
                )}
              >
                <span className="text-[10px] font-semibold text-muted">
                  {item.month}월
                </span>
                {item.confidence < 0.5 && (
                  <span className="h-1.5 w-1.5 rounded-full bg-hitl-ink" />
                )}
              </button>
            ))}
          </div>
        ) : (
          <div className="w-72 flex-shrink-0 overflow-y-auto border-r border-line bg-bg xl:w-80">
            {filtered.length === 0 ? (
              <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
                검토 항목 없음
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2">
                  <label className="flex items-center gap-2 text-xs text-muted">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 accent-brand"
                      checked={filtered.every((i) =>
                        selectedIds.has(i.voucher_id),
                      )}
                      onChange={toggleSelectAllFiltered}
                      aria-label="현재 목록 전체 선택"
                    />
                    전체 선택 ({filtered.length}건)
                  </label>
                  <button
                    onClick={() => setVoucherListCollapsed(true)}
                    className="text-faint transition-colors hover:text-ink"
                    aria-label="전표 목록 접기"
                    title="전표 목록 접기"
                  >
                    «
                  </button>
                </div>
                {filtered.map((item) => {
                  const isConfirmed = item.status === "confirmed";
                  return (
                  <div
                    key={item.voucher_id}
                    className={cn(
                      "flex items-start gap-2 border-b border-line px-3 py-3.5 transition-colors",
                      selectedId === item.voucher_id
                        ? "border-l-2 border-l-brand bg-brand-soft"
                        : "hover:bg-bg",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-3.5 w-3.5 flex-shrink-0 accent-brand disabled:opacity-30"
                      checked={selectedIds.has(item.voucher_id)}
                      onChange={() => toggleSelect(item.voucher_id)}
                      disabled={isConfirmed}
                      aria-label={`${item.raw} 선택`}
                    />
                    <button
                      type="button"
                      onClick={() => setSelectedId(item.voucher_id)}
                      className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left"
                    >
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate text-sm font-semibold text-ink">
                          {item.raw}
                        </span>
                        {(item.anomaly_check_status === "disputed" ||
                          item.anomaly_check_status === "unknown") && (
                          <span
                            className="flex-shrink-0 rounded-full bg-hitl-ink px-1.5 py-0.5 text-[10px] font-bold text-white"
                            title="사장님이 이상하다고 답함"
                          >
                            이상 확인 요청
                          </span>
                        )}
                      </span>
                      <span className="flex flex-shrink-0 items-center gap-1.5">
                        <ConfidenceBadge value={item.confidence} />
                        {isConfirmed && (
                          <span
                            className="flex h-4 w-4 items-center justify-center rounded-full bg-brand text-white"
                            title="검토 완료"
                          >
                            <Check className="h-3 w-3" strokeWidth={3} />
                          </span>
                        )}
                      </span>
                    </button>
                  </div>
                  );
                })}
              </>
            )}
          </div>
        )}

        <div className="flex-1 overflow-hidden">
          {selected ? (
            <div className="h-full p-6">
              <DetailPane
                key={selected.voucher_id}
                item={selected}
                onDone={(voucherId, mode) =>
                  mode === "confirm" ? markConfirmed(voucherId) : removeItem(voucherId)
                }
              />
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
