import { WireframeBadge } from "./WireframeBadge";

/** 장면 ④ — PCAF Before/After + 벤치마킹 + 간단 리포트. */

// Tailwind 는 동적 조합 클래스(bg-pcaf-${n})를 못 잡으므로 완전한 문자열로 매핑.
const GRADE_BG: Record<number, string> = {
  1: "bg-pcaf-1",
  2: "bg-pcaf-2",
  3: "bg-pcaf-3",
  4: "bg-pcaf-4",
  5: "bg-pcaf-5",
};

function GradeBadge({ grade }: { grade: number }) {
  return (
    <span
      className={`grid h-10 w-10 place-items-center rounded-lg text-lg font-bold text-white ${GRADE_BG[grade]}`}
    >
      {grade}
    </span>
  );
}

export function ScenePcaf() {
  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">④ PCAF Before / After</h2>
        <WireframeBadge />
      </div>
      <p className="mt-1 text-sm text-muted">
        기존 매출 추정 방식(5등급 · 깜깜이)과 전표 기반 실측(2~3등급)의 데이터
        품질 비교입니다.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-line p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">
            Before · 기존 방식
          </div>
          <div className="mt-3 flex items-center gap-3">
            <GradeBadge grade={5} />
            <div>
              <div className="font-semibold">PCAF 5등급</div>
              <div className="text-sm text-muted">매출액 통계 대입 추정</div>
            </div>
          </div>
          <div className="mt-4 text-sm text-muted">
            추정 배출량{" "}
            <span className="font-semibold text-ink">~52.0 tCO₂e</span>
            <span className="ml-1 text-xs">(오차 미인지)</span>
          </div>
        </div>

        <div className="rounded-lg border-2 border-pcaf-2 p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-pcaf-2">
            After · 본 엔진
          </div>
          <div className="mt-3 flex items-center gap-3">
            <GradeBadge grade={2} />
            <div>
              <div className="font-semibold">PCAF 2등급</div>
              <div className="text-sm text-muted">전표 기반 실측 산정</div>
            </div>
          </div>
          <div className="mt-4 text-sm text-muted">
            산정 배출량{" "}
            <span className="font-semibold text-ink">38.4 tCO₂e</span>
            <span className="ml-1 text-xs">
              (Scope 1: 22.1 · Scope 2: 16.3)
            </span>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-lg bg-bg p-4 text-sm">
        <div className="font-semibold">동종 업종 벤치마킹</div>
        <p className="mt-1 text-muted">
          금속가공업(C251) 대비{" "}
          <span className="font-semibold text-ink">상위 34%</span> — 주 요인:
          노후 보일러(고정연소). 가스 고지서 2장을 추가 연동하면 3등급 → 2등급,
          우대금리 대상 안내.
        </p>
      </div>
    </section>
  );
}
