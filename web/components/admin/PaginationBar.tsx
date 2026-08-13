"use client";

// review-log/documents-access-log 등 로그 탭이 공유하는 페이지 이동 바.
// "N건 중 M~K" 표시 + 이전/다음 버튼. 페이지 번호 목록은 만들지 않는다 —
// 서버가 total만 주고 page_size가 고정이라 이전/다음만으로 충분하다.

export function PaginationBar({
  total,
  page,
  pageSize,
  onChange,
}: {
  total: number;
  page: number;
  pageSize: number;
  onChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="flex flex-shrink-0 items-center justify-between border-t border-line px-5 py-2.5">
      <span className="text-[11px] text-faint">
        전체 {total.toLocaleString()}건 중 {from}–{to}
      </span>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="rounded-md border border-line bg-surface px-2.5 py-1 text-[11px] font-medium text-muted transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
        >
          이전
        </button>
        <span className="text-[11px] tabular-nums text-faint">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => onChange(page + 1)}
          className="rounded-md border border-line bg-surface px-2.5 py-1 text-[11px] font-medium text-muted transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
        >
          다음
        </button>
      </div>
    </div>
  );
}
