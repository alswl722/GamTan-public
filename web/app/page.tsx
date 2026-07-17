import Link from "next/link";
import { LiveTraceFeed } from "@/components/LiveTraceFeed";

const STEPS = [
  {
    t: "마이데이터 연동 동의",
    preview: "실제 홈택스·한전 마이데이터와 동일한 구조로 자동 연동돼요",
  },
  {
    t: "에이전트 트레이스 뷰",
    preview: "빠진 전표까지 에이전트가 먼저 찾아내고 스스로 보정해요",
  },
  {
    t: "AI 분류 + 근거",
    preview:
      "왜 그렇게 판단했는지 근거를 남기고, 확신이 낮은 건 AI가 스스로 은행 담당자에게 넘겨요",
  },
  {
    t: "PCAF Before/After",
    preview: "전표를 실제로 읽을수록 등급이 오르고 우대금리로 이어져요",
  },
];

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center px-5 pb-20">
      <div className="grid w-full max-w-5xl items-center gap-12 pt-14 lg:grid-cols-[1fr_1fr] lg:gap-8 lg:pt-20">
        <div className="text-center lg:text-left">
          <span
            className="hero-enter inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1.5 text-[11.5px] font-bold tracking-wide text-brand-ink"
            style={{ animationDelay: "0ms" }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-brand" />
            We:iM 데모 시나리오
          </span>

          <h1
            className="hero-enter mt-5 text-[34px] font-extrabold leading-[1.22] tracking-[-0.02em] text-ink lg:text-[42px]"
            style={{ animationDelay: "90ms" }}
          >
            AI 에이전트가
            <br />
            <span className="text-brand-ink">중소기업의 탄소</span>를
            <br />
            대신 측정합니다
          </h1>

          <div
            className="hero-enter mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center lg:justify-start"
            style={{ animationDelay: "180ms" }}
          >
            <Link
              href="/owner"
              className="rounded-2xl bg-brand px-8 py-4 text-[15.5px] font-bold text-white shadow-float transition-transform hover:-translate-y-0.5 hover:bg-brand-ink"
            >
              사장님 여정 시작하기 →
            </Link>
            <Link
              href="/admin"
              className="rounded-2xl px-8 py-4 text-[15.5px] font-bold text-muted transition-colors hover:bg-surface hover:text-ink"
            >
              관리자 대시보드 보기 →
            </Link>
          </div>
        </div>

        <div
          className="hero-enter flex justify-center lg:justify-end"
          style={{ animationDelay: "240ms" }}
        >
          <LiveTraceFeed />
        </div>
      </div>

      <ol className="mt-20 grid w-full max-w-5xl gap-3 text-left sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((s, i) => (
          <li
            key={s.t}
            className="hero-enter group relative overflow-hidden rounded-2xl bg-surface p-4 shadow-card transition-all duration-300 hover:-translate-y-1 hover:shadow-float"
            style={{ animationDelay: `${320 + i * 70}ms` }}
          >
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-[13px] font-extrabold text-brand-ink transition-colors duration-300 group-hover:bg-brand group-hover:text-white">
                {i + 1}
              </span>
              <div className="text-[15.5px] font-bold text-ink">{s.t}</div>
            </div>

            <div className="grid grid-rows-[0fr] transition-[grid-template-rows] duration-300 ease-out group-hover:grid-rows-[1fr]">
              <div className="overflow-hidden">
                <div className="mt-1 break-keep text-[13.5px] leading-relaxed text-muted">
                  {s.preview}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
