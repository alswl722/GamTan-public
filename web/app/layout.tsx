import type { Metadata } from "next";
import "./globals.css";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata: Metadata = {
  title: "IM 뱅크 - 탄소 측정 에이전트",
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
        <SiteHeader />
        <main className="flex w-full flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
