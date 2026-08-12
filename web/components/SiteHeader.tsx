"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell } from "lucide-react";
import { cn } from "@/lib/utils";

export function SiteHeader() {
  const pathname = usePathname();
  // admin(웹 대시보드)만 헤더를 전체 폭으로 — owner(모바일 앱 흐름)는 중앙정렬 좁은 폭 유지
  const isAdmin = pathname?.startsWith("/admin");
  // 사장님 앱(모바일 앱 흐름)에는 관리자 화면으로 넘어가는 버튼을 두지 않는다 —
  // 서로 다른 페르소나 전환용 버튼이 있으면 실제 앱처럼 안 보인다.
  const isOwner = pathname?.startsWith("/owner");

  return (
    <header className="sticky top-0 z-20 border-b border-line/70 bg-surface/80 backdrop-blur-md">
      <div
        className={cn(
          "flex h-16 items-center justify-between px-5",
          isAdmin ? "w-full" : "mx-auto max-w-5xl",
        )}
      >
        <Link href="/" className="flex items-center gap-2">
          <img src="/im-symbol.png" alt="iM Bank" className="h-6 w-auto" />
          <span
            className="text-[22px] tracking-tight text-ink"
            style={{ fontFamily: "MaruBuri, var(--font-sans)", fontWeight: 300 }}
          >
            감탄
          </span>
        </Link>
        <div className="flex items-center gap-3">
          {isOwner ? (
            // 사장님 앱은 실제 모바일 앱처럼 — 페르소나 전환 링크 대신 알림 아이콘만
            <button
              type="button"
              className="relative grid h-9 w-9 place-items-center rounded-full text-muted transition-colors hover:bg-brand-soft hover:text-brand-ink"
              aria-label="알림"
            >
              <Bell size={19} strokeWidth={2.2} />
              <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-red-500 ring-2 ring-surface" />
            </button>
          ) : (
            <nav className="flex items-center gap-1 text-[13.5px]">
              <Link
                href="/owner"
                className="rounded-full px-3.5 py-2 font-semibold text-muted transition-colors hover:bg-brand-soft hover:text-brand-ink"
              >
                사장님 화면
              </Link>
              <Link
                href="/admin"
                className="rounded-full px-3.5 py-2 font-semibold text-muted transition-colors hover:bg-brand-soft hover:text-brand-ink"
              >
                관리자
              </Link>
            </nav>
          )}

          {isAdmin && (
            <div className="flex items-center gap-2 border-l border-line pl-3">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand-ink">
                아
              </span>
              <div className="hidden leading-tight sm:block">
                <div className="text-xs font-semibold text-ink">아이엠 담당자</div>
                <div className="text-[10px] text-faint">여신·ESG팀</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
