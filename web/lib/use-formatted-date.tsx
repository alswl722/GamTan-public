"use client";

import { useEffect, useState } from "react";

/** 날짜는 마운트 후에만 포맷 — SSR/hydration 불일치 회피. TraceHistory·AuditLog 공용. */
export function useFormattedDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions) {
  const [formatted, setFormatted] = useState<string | null>(null);
  // opts 는 호출부에서 매번 새 객체로 넘어오는 게 보통이라(고정 포맷) deps 에서 제외 —
  // iso 가 바뀔 때만 재포맷하면 된다.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (iso) setFormatted(new Date(iso).toLocaleString("ko-KR", opts));
  }, [iso]);
  return formatted;
}

export function DateText({
  iso,
  opts,
}: {
  iso: string | null | undefined;
  opts: Intl.DateTimeFormatOptions;
}) {
  return <>{useFormattedDate(iso, opts) ?? "—"}</>;
}
