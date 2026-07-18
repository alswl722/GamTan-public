/**
 * 관리자 대시보드 데이터 접근 — 실 API는 기존 fetch 래퍼(apiGet/apiPatch) 위에,
 * 목업(이상신호·우대금리)은 여기 상수로. 실데이터/목업 경계를 한곳에서 본다.
 *
 * 실API 연결: 포트폴리오·검토 큐·확정/수정/반려·실행 이력 = 백엔드 실제 응답.
 * 목업(예시): 이상 신호 알림, 우대금리 후보 = 결선 확장 대상(GET /admin/alerts 등 미구현).
 */
import { apiGet, apiPatch } from "@/lib/api";
import type {
  AlertItem,
  ClassificationEdit,
  HitlItem,
  PortfolioResponse,
  RateCandidateItem,
  TraceRunItem,
  TraceStep,
} from "@/lib/admin-types";

// ── 실 API ──────────────────────────────────────────────────────────────
export function getPortfolio(): Promise<PortfolioResponse> {
  return apiGet<PortfolioResponse>("/admin/portfolio");
}

export function getHitl(): Promise<HitlItem[]> {
  return apiGet<{ queue: HitlItem[] }>("/admin/hitl").then((r) => r.queue);
}

export function confirmVoucher(voucherId: number) {
  return apiPatch(`/admin/classifications/${voucherId}/confirm`);
}

export function editVoucher(voucherId: number, edits: ClassificationEdit) {
  return apiPatch(`/admin/classifications/${voucherId}`, edits);
}

export function rejectVoucher(voucherId: number) {
  return apiPatch(`/admin/classifications/${voucherId}/reject`);
}

export function getTraceRuns(): Promise<TraceRunItem[]> {
  return apiGet<{ runs: TraceRunItem[] }>("/admin/traces").then((r) => r.runs);
}

/** 실행 이력 드릴다운 — 기존 /trace/{session_id} 재사용. */
export function getTraceSteps(sessionId: string): Promise<TraceStep[]> {
  return apiGet<{ steps: TraceStep[] }>(`/trace/${sessionId}`).then((r) => r.steps);
}

// ── 목업 (예시 · 결선 확장) ────────────────────────────────────────────
export const MOCK_ALERTS: AlertItem[] = [
  { id: "a001", severity: "high", company_name: "동성금속㈜", message: "7월 경유 사용량 평월 대비 3.2배 급증 (자가검증 결과 정상 판정됨)" },
  { id: "a002", severity: "high", company_name: "삼양기계산업", message: "3개월 연속 전력 사용량 급감 → 가동률 하락 의심" },
  { id: "a003", severity: "medium", company_name: "경남철강㈜", message: "6개월간 전표 미연동 → 데이터 공백" },
  { id: "a004", severity: "medium", company_name: "울산석유화학", message: "5월~7월 전기요금 청구액 전년 동기 대비 41% 감소 → 조업 축소 가능성" },
  { id: "a005", severity: "low", company_name: "부산조선기자재", message: "중유 구입 단가 전월 대비 18% 급등 — 공급사 변경 여부 확인 필요" },
  { id: "a006", severity: "high", company_name: "광주자동차부품", message: "12개월 연속 5등급 유지 — 전표 연동 신청 독려 필요" },
  { id: "a007", severity: "medium", company_name: "평택도금공업", message: "도금 약품 보일러 가동 데이터 2개월 미수신" },
  { id: "a008", severity: "low", company_name: "포항특수강", message: "여름철 냉방 전력 급증 → 계절 이상치로 자동 플래그" },
  { id: "a009", severity: "medium", company_name: "창원금속㈜", message: "공장 용접 가스 전표 분류 오류 의심 — 담당자 검토 2건 연속 반려" },
  { id: "a010", severity: "low", company_name: "진흥산업개발", message: "가스요금 공급가액 전월 대비 35% 감소 — 계절 조정 또는 공급 중단 여부 확인" },
];

export const MOCK_RATE_CANDIDATES: RateCandidateItem[] = [
  { id: "r001", company_name: "동성금속㈜", current_grade: 5, target_grade: 3, missing: "전기요금 고지서 최근 6개월 + 경유 구매 전표", benefit: "대출금리 0.3%p 인하 (우대금리 적용)" },
  { id: "r002", company_name: "진흥산업개발", current_grade: 3, target_grade: 2, missing: "가스 고지서 2장 추가 연동 시 3등급 → 2등급", benefit: "우대금리 대상 + ESG 인증서 발급" },
  { id: "r003", company_name: "한빛화학공업", current_grade: 4, target_grade: 3, missing: "스팀 공급사 배출계수 확인서 제출", benefit: "여신 한도 5% 증액 검토 가능" },
  { id: "r004", company_name: "경남철강㈜", current_grade: 5, target_grade: 4, missing: "전기요금 KEPCO 연동 동의서 + 최근 3개월 전표", benefit: "금리 0.2%p 인하 가능" },
  { id: "r005", company_name: "동아플라스틱", current_grade: 4, target_grade: 3, missing: "작업차량 유류 대장 제출 (3개월)", benefit: "우대금리 검토 대상 진입" },
  { id: "r006", company_name: "광주자동차부품", current_grade: 5, target_grade: 3, missing: "전표 12개월 소급 연동 + 전기요금 연동", benefit: "금리 0.3%p 인하 + 녹색금융 인증 신청 가능" },
  { id: "r007", company_name: "대전반도체장비", current_grade: 3, target_grade: 2, missing: "클린룸 전용 계량기 데이터 3개월 + 냉매 사용 내역", benefit: "우대금리 + ESG 보고서 지원 서비스" },
];
