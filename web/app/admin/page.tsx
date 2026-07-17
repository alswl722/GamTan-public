/**
 * 관리자 대시보드 — 은행 ESG·여신 담당자 화면.
 * 실데이터 3패널: 포트폴리오 집계 / HITL 검토 큐(확정) / 트레이스 뷰(읽기 전용).
 * (검증 오차율 배지는 트랙 A/B 검증 후 결선에서 확장 — CLAUDE.md §9)
 */
import { PortfolioPanel } from "@/components/admin/PortfolioPanel";
import { HitlQueue } from "@/components/admin/HitlQueue";
import { AdminTracePanel } from "@/components/admin/AdminTracePanel";

export default function AdminPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">관리자 대시보드</h1>
        <p className="mt-1 text-sm text-muted">은행 ESG·여신 담당자용 집계 화면</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 좌: 포트폴리오 집계 (넓게) */}
        <div className="lg:row-span-2">
          <PortfolioPanel />
        </div>
        {/* 우상: HITL 큐 */}
        <HitlQueue />
        {/* 우하: 트레이스 패널 */}
        <AdminTracePanel />
      </div>
    </div>
  );
}
