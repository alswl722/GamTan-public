"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  getOwnerNotifications,
  markNotificationRead,
  type OwnerNotification,
} from "@/lib/api";

const POLL_INTERVAL_MS = 12_000;

/** 홈 화면 배너 — "확정 전송 → 사장님 알림"(docs/v1-plan.md §6-2, docs/tasks.md).
 * 담당자가 분류를 확정·전송하면 생기는 미확인 알림을 폴링으로 감지해 보여준다.
 * 평상시(알림 없음)엔 아무것도 렌더링하지 않는다 — 빈 상태 UI 없음(Figma 디자인 그대로).
 * Figma: "홈" 프레임 328:5(Owner Notification Banner), 328:8(States 비교). */
export default function OwnerNotificationBanner({ companyId }: { companyId: number }) {
  const [notification, setNotification] = useState<OwnerNotification | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    function poll() {
      getOwnerNotifications(companyId, true)
        .then((list) => {
          if (!cancelled) setNotification(list[0] ?? null);
        })
        .catch(() => {}); // 폴링 1회 실패는 다음 틱이 재시도
    }

    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [companyId]);

  if (!notification) return null;

  function handleClick() {
    if (notification) markNotificationRead(companyId, notification.id).catch(() => {});
  }

  // 업로드 백그라운드 처리(v1 2주차) 알림은 "데이터 업로드" 탭으로, 그 외(확정
  // 전송 등 기존 알림)는 지금처럼 리포트로 보낸다.
  const href =
    notification.type === "document_processed" || notification.type === "document_failed"
      ? "/owner/uploads"
      : "/owner/report";

  return (
    <Link
      href={href}
      onClick={handleClick}
      className="mt-3 flex items-center gap-2 rounded-xl bg-brand-soft px-3.5 py-2.5 transition-opacity hover:opacity-90"
    >
      <span className="size-1.5 shrink-0 rounded-full bg-brand" />
      <span className="flex-1 text-[12px] font-bold text-brand-ink">{notification.message}</span>
      <ChevronRight size={16} strokeWidth={2.6} className="shrink-0 text-brand-ink" />
    </Link>
  );
}
