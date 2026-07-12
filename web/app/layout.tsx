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
        <header className="sticky top-0 z-10 border-b border-line bg-surface">
          <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-5">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-brand text-[13px] font-extrabold tracking-tight text-white">
                iM
              </span>
              <span className="text-[15px] font-semibold tracking-tight">
                iM-Bridge
              </span>
            </Link>
            <nav className="flex items-center gap-1 text-[13.5px]">
              <Link
                href="/owner"
                className="rounded-lg px-3 py-1.5 font-medium text-muted hover:bg-brand-soft hover:text-brand-ink"
              >
                사장님
              </Link>
              <Link
                href="/admin"
                className="rounded-lg px-3 py-1.5 font-medium text-muted hover:bg-brand-soft hover:text-brand-ink"
              >
                관리자
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
