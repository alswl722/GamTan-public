"use client";

// 목업: 검증 오차율 — 예시 · 검증 수치 확정 후 반영
// { track_a_mape: 34.2, track_b_error: 8.7 } (트랙 A/B 백테스트 확정 전 고정값)

const MOCK_VERIFICATION = {
  track_a_mape: 34.2, // 기존 매출 추정 방식 평균 오차
  track_b_error: 8.7, // 본 엔진 실물대조 오차
};

export function VerificationBadge() {
  const { track_a_mape, track_b_error } = MOCK_VERIFICATION;
  const improvement = Math.round(((track_a_mape - track_b_error) / track_a_mape) * 100);

  return (
    <div className="flex h-full flex-col rounded-2xl border border-[#e8eaed] bg-white p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#222222]">검증 오차율 배지</h2>
          <p className="mt-0.5 text-[11px] text-[#9ca3af]">Track A vs Track B 백테스트</p>
        </div>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-semibold text-slate-500">
          예시 · 검증 수치 확정 후 반영
        </span>
      </div>

      <div className="flex gap-3">
        <div className="flex-1 rounded-xl border border-[#e8eaed] bg-[#f7f8fa] p-3 text-center">
          <p className="mb-1 text-[11px] leading-tight text-[#9ca3af]">기존 매출 추정 방식</p>
          <p className="text-2xl font-bold tabular-nums text-[#222222]">{track_a_mape}%</p>
          <p className="mt-0.5 text-[10px] text-[#9ca3af]">평균 오차 (MAPE)</p>
        </div>
        <div className="flex items-center">
          <span className="text-sm text-[#9ca3af]">vs</span>
        </div>
        <div className="flex-1 rounded-xl border border-[#00c7a9]/40 bg-[#e3faf5] p-3 text-center">
          <p className="mb-1 text-[11px] leading-tight text-[#00967f]">본 엔진 실물대조</p>
          <p className="text-2xl font-bold tabular-nums text-[#00967f]">{track_b_error}%</p>
          <p className="mt-0.5 text-[10px] text-[#00967f]">평균 오차</p>
        </div>
      </div>

      <div className="mt-3 rounded-lg bg-[#e3faf5] px-3 py-2 text-center">
        <span className="text-xs font-semibold text-[#00967f]">
          오차율 {improvement}% 감소 — 실물 전표 기반 산정의 신뢰성 근거
        </span>
      </div>
    </div>
  );
}
