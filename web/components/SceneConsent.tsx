import { WireframeBadge } from "./WireframeBadge";

/** 장면 ① — 마이데이터 연동 동의. 클릭 1회 → 수집 프로그레스 (정적 목업). */
export function SceneConsent() {
  const collected = 24;
  const total = 33;
  const pct = Math.round((collected / total) * 100);

  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">① 마이데이터 연동 동의</h2>
        <WireframeBadge />
      </div>
      <p className="mt-1 text-sm text-muted">
        클릭 1회로 홈택스 세금계산서 · 한전 전기요금 고지서를 자동 수집합니다.
        입력 제로.
      </p>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <div className="rounded-lg border border-line bg-bg p-5">
          <div className="text-sm font-medium text-muted">○○정밀 (구미 · 금속가공 · 12명)</div>
          <button
            type="button"
            className="mt-4 w-full rounded-lg bg-brand px-5 py-3 text-sm font-semibold text-white hover:bg-brand-ink"
          >
            마이데이터 연동에 동의하고 시작하기
          </button>
          <div className="mt-3 text-center text-[11px] text-muted">
            홈택스 · 한전과 동일 스키마의 Mock API (데모)
          </div>
        </div>

        <div className="rounded-lg border border-line p-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">전표 수집 진행</span>
            <span className="text-muted">
              {collected} / {total}건
            </span>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-brand"
              style={{ width: `${pct}%` }}
            />
          </div>
          <ul className="mt-4 space-y-2 text-sm">
            <li className="flex items-center justify-between">
              <span className="text-muted">홈택스 세금계산서</span>
              <span className="font-medium text-scope1">22건</span>
            </li>
            <li className="flex items-center justify-between">
              <span className="text-muted">한전 전기 고지서</span>
              <span className="font-medium text-scope2">12건</span>
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}
