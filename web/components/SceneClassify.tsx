import { WireframeBadge } from "./WireframeBadge";

/** 장면 ③ — AI 분류 + 근거 (킬러씬 B). evidence 노출 + 저신뢰 HITL 뱃지. */

type Row = {
  raw: string;
  scope: 1 | 2;
  category: string;
  fuel: string;
  amount: number;
  confidence: number;
  evidence: string;
  hitl?: boolean;
};

// 목업 — CLAUDE.md 스키마 기반 (계산 필드 없음: 물량·탄소량은 백엔드 코드가 산출)
const ROWS: Row[] = [
  {
    raw: "지게차 경유 외 1종",
    scope: 1,
    category: "이동연소",
    fuel: "경유",
    amount: 654000,
    confidence: 0.87,
    evidence: "품목명에 '지게차'와 '경유' 명시",
  },
  {
    raw: "전기요금 (7월분)",
    scope: 2,
    category: "간접배출",
    fuel: "전기",
    amount: 1240000,
    confidence: 0.99,
    evidence: "한전 고지서 · '전기요금' 키워드 룰 확정",
  },
  {
    raw: "유류대금",
    scope: 1,
    category: "고정연소",
    fuel: "경유(보일러)",
    amount: 320000,
    confidence: 0.52,
    evidence: "연료 종류 불명확 — 이동/고정 연소 구분 애매",
    hitl: true,
  },
];

function ScopeTag({ scope }: { scope: 1 | 2 }) {
  const color = scope === 1 ? "text-scope1 bg-scope1/10" : "text-scope2 bg-scope2/10";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${color}`}>
      Scope {scope}
    </span>
  );
}

export function SceneClassify() {
  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          ③ AI 분류 + 근거
          <span className="ml-2 rounded bg-scope2/10 px-2 py-0.5 text-xs font-semibold text-scope2">
            킬러씬 B
          </span>
        </h2>
        <WireframeBadge />
      </div>
      <p className="mt-1 text-sm text-muted">
        비정형 전표를 Scope·연료로 분류하고 판단 근거를 남깁니다. 신뢰도가 낮으면
        스스로 HITL 검토 큐로 넘깁니다.
      </p>

      <div className="mt-6 space-y-3">
        {ROWS.map((r, i) => (
          <div
            key={i}
            className={`rounded-lg border p-4 ${
              r.hitl ? "border-hitl/40 bg-hitl/5" : "border-line"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-medium">
                  &ldquo;{r.raw}&rdquo;
                </span>
                {r.hitl && (
                  <span className="rounded bg-hitl px-2 py-0.5 text-[11px] font-semibold text-white">
                    검토필요 · HITL
                  </span>
                )}
              </div>
              <span className="text-sm tabular-nums text-muted">
                {r.amount.toLocaleString()}원
              </span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <ScopeTag scope={r.scope} />
              <span className="rounded border border-line px-2 py-0.5 text-xs text-muted">
                {r.category}
              </span>
              <span className="rounded border border-line px-2 py-0.5 text-xs text-muted">
                {r.fuel}
              </span>
              <ConfidenceBar value={r.confidence} />
            </div>

            <details className="mt-2 text-sm">
              <summary className="cursor-pointer text-muted hover:text-ink">
                근거(evidence) 펼치기
              </summary>
              <p className="mt-1.5 rounded bg-bg p-2 text-muted">{r.evidence}</p>
            </details>
          </div>
        ))}
      </div>
    </section>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const low = value < 0.7;
  return (
    <span className="ml-auto flex items-center gap-1.5">
      <span className="text-[11px] text-muted">신뢰도</span>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <span
          className={`block h-full ${low ? "bg-hitl" : "bg-ok"}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      <span className="tabular-nums text-[11px] font-medium">
        {value.toFixed(2)}
      </span>
    </span>
  );
}
