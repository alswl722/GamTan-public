import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "iM-Bridge — 전표를 읽는 탄소 측정 에이전트",
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
      <body className="min-h-full flex flex-col">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <Link href="/" className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-brand text-sm font-bold text-white">
                iM
              </span>
              <span className="text-base font-semibold tracking-tight">
                iM-Bridge
              </span>
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              <Link
                href="/owner"
                className="rounded-md px-3 py-1.5 font-medium text-muted hover:bg-bg hover:text-ink"
              >
                사장님
              </Link>
              <Link
                href="/admin"
                className="rounded-md px-3 py-1.5 font-medium text-muted hover:bg-bg hover:text-ink"
              >
                관리자
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
