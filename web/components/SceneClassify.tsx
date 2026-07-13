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

const ROWS: Row[] = [
  {
    raw: "지게차 경유 외 1종",
    scope: 1,
    category: "이동연소",
    fuel: "경유",
    amount: 654000,
    confidence: 0.87,
    evidence: "품목명에 ‘지게차’와 ‘경유’가 명시되어 직접배출(이동연소)로 분류",
  },
  {
    raw: "전기요금 (산업용 을)",
    scope: 2,
    category: "간접배출",
    fuel: "전기",
    amount: 1240000,
    confidence: 0.99,
    evidence: "한전 고지서 · ‘전기요금’ 키워드 룰로 확정 (LLM 미사용)",
  },
  {
    raw: "유류대금",
    scope: 1,
    category: "연료종류 불명",
    fuel: "",
    amount: 320000,
    confidence: 0.52,
    evidence: "경유/휘발유 구분 불가 → 사람 검토 큐로 이관 (보조수단성 원칙)",
    hitl: true,
  },
];

function ScopeTag({ scope }: { scope: 1 | 2 }) {
  const cls =
    scope === 1
      ? "text-scope1 bg-scope1/10"
      : "text-scope2 bg-scope2/10";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>
      Scope {scope}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const low = value < 0.7;
  return (
    <span className="ml-auto flex items-center gap-1.5">
      <span className="text-[11.5px] text-muted">신뢰도</span>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <span
          className={`block h-full ${low ? "bg-hitl" : "bg-ok"}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      <span className="tabular-nums text-[11.5px] font-medium">
        {value.toFixed(2)}
      </span>
    </span>
  );
}

export function SceneClassify() {
  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">
          ③ AI 분류 + 근거
          <span className="ml-2 rounded bg-scope2/10 px-2 py-0.5 text-[11px] font-bold text-scope2">
            킬러씬 B
          </span>
        </h2>
        <WireframeBadge />
      </div>
      <p className="mt-1 text-[13.5px] text-muted">
        비정형 전표를 Scope·연료로 분류하고 판단 근거를 남깁니다. 신뢰도가 낮으면
        스스로 사람 검토(HITL)로 넘깁니다.
      </p>

      <div className="mt-[18px] space-y-3">
        {ROWS.map((r, i) => (
          <div
            key={i}
            className={`rounded-lg border p-4 ${
              r.hitl ? "border-hitl/40 bg-hitl/5" : "border-line"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[13.5px] font-semibold">
                  “{r.raw}”
                </span>
                {r.hitl && (
                  <span className="rounded bg-hitl px-2 py-0.5 text-[11px] font-bold text-white">
                    검토필요 · HITL
                  </span>
                )}
              </div>
              <span className="text-[13.5px] tabular-nums text-muted">
                {r.amount.toLocaleString()}원
              </span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px]">
              <ScopeTag scope={r.scope} />
              <span className="rounded border border-line px-2 py-0.5 text-muted">
                {r.category}
              </span>
              {r.fuel && (
                <span className="rounded border border-line px-2 py-0.5 text-muted">
                  {r.fuel}
                </span>
              )}
              <ConfidenceBar value={r.confidence} />
            </div>

            <div className="mt-2.5 rounded-lg bg-bg px-2.5 py-2 text-[12.5px] text-muted">
              <span className="font-semibold text-ink">근거</span> · {r.evidence}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
