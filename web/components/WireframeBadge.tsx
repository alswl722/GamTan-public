/** 와이어프레임 단계임을 명시하는 뱃지 — 목업 데이터라는 것을 화면에서 정직하게 표기. */
export function WireframeBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-line bg-bg px-2.5 py-1 text-[11px] font-medium text-muted">
      <span className="h-1.5 w-1.5 rounded-full bg-estimated" />
      와이어프레임 · 목업 데이터
    </span>
  );
}
