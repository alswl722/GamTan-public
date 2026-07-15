import Link from "next/link";

const STEPS = [
  { t: "마이데이터 연동 동의", d: "클릭 한 번으로 홈택스·한전 전표 자동 수집" },
  { t: "에이전트 트레이스 뷰", d: "결손 감지 → 알림 → 보정 판단을 실시간으로" },
  { t: "AI 분류 + 근거", d: "비정형 전표 분류, evidence, 저신뢰 건 HITL" },
  { t: "PCAF Before/After", d: "매출 추정(5등급) vs 전표 기반(2~3등급) 비교" },
];

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center px-5 pb-20 pt-16 text-center">
      <h1 className="mt-6 max-w-lg text-[32px] font-extrabold leading-[1.28] tracking-tight text-ink">
        전표를 읽는 AI 에이전트가
        <br />
        <span className="text-brand">중소기업의 탄소</span>
        를 대신 측정합니다
      </h1>

      <p className="mt-4 max-w-md text-[15px] leading-relaxed text-muted">
        &ldquo;지게차 경유 외 1종&rdquo; 같은 비정형 세금계산서 텍스트를 AI가
        읽어 Scope 1/2 배출량을 자동 산정합니다. 사장님은 마이데이터 동의
        1클릭 외에 아무것도 입력하지 않습니다.
      </p>

      <Link
        href="/owner"
        className="mt-8 rounded-2xl bg-brand px-8 py-4 text-[15.5px] font-bold text-white shadow-float transition-transform hover:-translate-y-0.5 hover:bg-brand-ink"
      >
        사장님 여정 시작하기 →
      </Link>
      <Link
        href="/admin"
        className="mt-3 text-[13px] font-semibold text-muted hover:text-ink"
      >
        관리자 대시보드 보기
      </Link>

      <ol className="mt-16 grid w-full max-w-lg gap-3 text-left">
        {STEPS.map((s, i) => (
          <li
            key={s.t}
            className="flex items-center gap-4 rounded-2xl bg-surface p-4"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-[13px] font-extrabold text-brand-ink">
              {i + 1}
            </span>
            <div>
              <div className="text-[14px] font-bold text-ink">{s.t}</div>
              <div className="mt-0.5 text-[12.5px] text-muted">{s.d}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
