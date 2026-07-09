import Link from "next/link";

export default function Home() {
  return (
    <div className="mx-auto max-w-3xl">
      <span className="inline-block rounded-full bg-brand/10 px-3 py-1 text-xs font-semibold text-brand">
        iM:POSSIBLE Challenger · v0.1 데모
      </span>
      <h1 className="mt-4 text-3xl font-bold leading-tight tracking-tight">
        전표를 읽는 AI 에이전트가
        <br />
        중소기업의 탄소를 대신 측정합니다.
      </h1>
      <p className="mt-4 text-muted">
        &ldquo;지게차 경유 외 1종&rdquo; 같은 비정형 세금계산서 텍스트를 AI가 읽어
        Scope 1/2 배출량을 자동 산정합니다. 사장님은 마이데이터 동의 1클릭 외에
        아무것도 입력하지 않습니다.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link
          href="/owner"
          className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-ink"
        >
          사장님 화면 보기 →
        </Link>
        <Link
          href="/admin"
          className="rounded-lg border border-line bg-surface px-5 py-2.5 text-sm font-semibold text-ink hover:bg-bg"
        >
          관리자 대시보드
        </Link>
      </div>

      <div className="mt-12 grid gap-4 sm:grid-cols-2">
        {[
          {
            n: "①",
            t: "마이데이터 연동 동의",
            d: "클릭 1회로 홈택스·한전 전표 자동 수집",
          },
          {
            n: "②",
            t: "에이전트 트레이스 뷰",
            d: "결손 감지 → 알림 → 보정 판단을 실시간 타임라인으로",
          },
          {
            n: "③",
            t: "AI 분류 + 근거",
            d: "비정형 전표 분류, evidence, 저신뢰 건 HITL",
          },
          {
            n: "④",
            t: "PCAF Before/After",
            d: "매출 추정(5등급) vs 전표 기반(2~3등급) 비교",
          },
        ].map((s) => (
          <div
            key={s.n}
            className="rounded-xl border border-line bg-surface p-4"
          >
            <div className="text-lg font-bold text-brand">{s.n}</div>
            <div className="mt-1 font-semibold">{s.t}</div>
            <div className="mt-1 text-sm text-muted">{s.d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
