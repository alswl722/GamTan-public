"use client";

// /owner 하위 라우트에서만 보이는 모바일 앱 스타일 하단바(web/app/owner/layout.tsx가 렌더).
// /admin·루트(/)엔 안 나온다 — 페르소나가 다른 화면에 사장님 전용 내비를 섞지 않는다.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Leaf } from "lucide-react";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/owner", label: "홈", icon: Home, exact: true },
  { href: "/owner/measure", label: "탄소측정", icon: Leaf, exact: false },
] as const;

export function OwnerBottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/95 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-2xl items-stretch">
        {ITEMS.map((item) => {
          const active = item.exact ? pathname === item.href : pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-semibold transition-colors",
                active ? "text-brand-ink" : "text-faint hover:text-muted",
              )}
            >
              <item.icon size={20} strokeWidth={active ? 2.4 : 2} />
              {item.label}
            </Link>
          );
        })}
      </div>
      {/* iOS 홈 인디케이터 영역 여백 */}
      <div className="h-[env(safe-area-inset-bottom)]" />
    </nav>
  );
}
