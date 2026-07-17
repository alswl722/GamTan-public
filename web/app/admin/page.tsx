/**
 * 관리자 대시보드 — v0.1 스코프에서는 placeholder 스텁.
 * (CLAUDE.md §9: 관리자 대시보드는 8월 결선 확장 대상)
 * 라우트·자리만 잡아두고, 결선에서 이 뼈대 위에 실데이터를 얹는다.
 */
const CARDS = [
  {
    t: "포트폴리오 금융배출량 집계",
    d: "거래 기업 전체의 Scope 1/2 합산 · PCAF 등급 분포",
  },
  {
    t: "HITL 검토 큐",
    d: "신뢰도 미달로 사람 확인이 필요한 분류 건 목록",
  },
  {
    t: "트레이스 뷰 패널",
    d: "에이전트 실행 로그 타임라인 (계획/관찰/행동)",
  },
  {
    t: "검증 오차율 배지",
    d: "트랙 A(기존 방식 오차) / 트랙 B(본 엔진 검증치)",
  },
];

export default function AdminPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">관리자 대시보드</h1>
        <p className="mt-1 text-sm text-muted">
          은행 ESG·여신 담당자용 집계 화면
        </p>
      </div>

      <div className="mb-6 rounded-lg border border-dashed border-line bg-surface p-4 text-sm text-muted">
        ⓘ 관리자 대시보드는 <span className="font-medium text-ink">결선(8월) 확장 범위</span>입니다.
        v0.1 데모는 사장님 화면 4장면 중심이며, 아래는 확장 자리만 잡아둔 스텁입니다.
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {CARDS.map((c) => (
          <div
            key={c.t}
            className="rounded-xl border border-line bg-surface p-5"
          >
            <div className="flex items-center justify-between">
              <div className="font-semibold">{c.t}</div>
              <span className="rounded bg-bg px-2 py-0.5 text-[11px] font-medium text-muted">
                결선 확장 예정
              </span>
            </div>
            <p className="mt-1.5 text-sm text-muted">{c.d}</p>
            <div className="mt-4 grid h-24 place-items-center rounded-lg border border-dashed border-line bg-bg text-xs text-muted">
              데이터 시각화 자리
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
