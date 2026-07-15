import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "감탄 — 전표를 읽는 탄소 측정 에이전트",
  description:
    "세금계산서·전기 고지서를 AI 에이전트가 읽어 중소기업 탄소 배출량을 자동 산정",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-bg">
        <header className="sticky top-0 z-20 border-b border-line/70 bg-surface/80 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-5">
            <Link href="/" className="flex items-center gap-2">
              <img src="/im-symbol.png" alt="iM Bank" className="h-6 w-auto" />
              <span className="text-[15px] font-bold tracking-tight text-ink">
                감탄
              </span>
            </Link>
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
          </div>
        </header>
        <main className="flex w-full flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
