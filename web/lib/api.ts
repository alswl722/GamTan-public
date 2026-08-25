/**
 * 백엔드(FastAPI) 호출 래퍼.
 * 각 Scene 이 여기를 통해 API 를 부른다. 기본 대상은 로컬 dev(8000).
 *
 * - 타임아웃: 행 걸린 요청은 무한 "판단 중…" 대신 빠르게 실패로 드러낸다(실패 가시성).
 * - 기업 ID: 하드코딩하지 않고 GET /company 로 1회 조회 후 캐시 — DB 재시드에도 동작.
 */
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const DEFAULT_TIMEOUT_MS = 15_000;

export async function apiGet<T>(path: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    throw new Error(`API ${path} 실패: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    throw new Error(`API ${path} 실패: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function apiPatch<T>(
  path: string,
  body?: unknown,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "PATCH",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    throw new Error(`API ${path} 실패: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function apiDelete<T>(
  path: string,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "DELETE",
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `API ${path} 실패: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** multipart 업로드 전용 — Content-Type을 fetch가 boundary 포함해 자동 설정하게 둔다. */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    body: form,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `API ${path} 실패: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** 에이전트 실행은 분류(LLM 병렬 호출) 포함이라 더 길게 허용. */
export const AGENT_RUN_TIMEOUT_MS = 60_000;

/** 업로드 요청 자체는 파일 저장 + 잡(job) 접수만 하고 바로 202를 반환한다(v1 2주차
 * — 실제 OCR/LLM 추출은 백그라운드로 옮겨졌다, api/document_ingestion.py 참고).
 * 예전엔 PaddleOCR 콜드 로딩(~28초)+LLM 최후수단(최대 20초×2회)까지 이 요청 안에서
 * 다 끝내야 해서 최악 90초+ 걸렸고(실측, 2026-08-17) 타임아웃을 120초까지 올렸던
 * 이력이 있는데, 이제 그 무거운 처리가 요청 밖으로 빠졌으니 기본 타임아웃이면 된다.
 * 진행 상태는 apiUpload 호출부가 getUploadJob()으로 폴링해서 확인한다. */
export const DOCUMENT_UPLOAD_TIMEOUT_MS = DEFAULT_TIMEOUT_MS;

// 계정(로그인) 개념이 없어 "지금 어느 기업으로 보고 있는지"를 서버가 알 방법이 없다 —
// 브라우저에 선택값을 저장해두고 모든 /owner 호출이 이 값을 쓴다. 기업 선택 화면
// (web/app/owner/page.tsx)에서 setCompanyId()로 바꾸면 그 즉시 다음 getCompanyId()
// 호출부터 반영된다(모듈 캐시가 아니라 매번 localStorage를 다시 읽음).
const COMPANY_ID_STORAGE_KEY = "gamtan:companyId";

function readStoredCompanyId(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(COMPANY_ID_STORAGE_KEY);
  if (raw === null) return null;
  const id = Number(raw);
  return Number.isFinite(id) ? id : null;
}

/** 기업 선택 화면에서 호출 — 이후 모든 getCompanyId() 호출이 이 값을 즉시 반환한다. */
export function setCompanyId(id: number): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(COMPANY_ID_STORAGE_KEY, String(id));
  }
}

let firstFetchPromise: Promise<number> | null = null;

/**
 * 현재 보고 있는 기업 ID. 저장된 선택값이 있으면 그걸 그대로 쓰고, 없으면(최초 진입)
 * GET /company(첫 번째 기업)로 1회 조회해 기본 선택값으로 저장한다. 실패 시 캐시를
 * 비우고 에러를 그대로 던진다(호출한 Scene의 에러 배너로 표시 — 무음 폴백 없음).
 */
export function getCompanyId(): Promise<number> {
  const stored = readStoredCompanyId();
  if (stored !== null) return Promise.resolve(stored);

  if (!firstFetchPromise) {
    firstFetchPromise = apiGet<{ id: number }>(`/company`)
      .then((c) => {
        setCompanyId(c.id);
        return c.id;
      })
      .catch((err) => {
        firstFetchPromise = null; // 다음 시도에서 재조회
        throw err;
      });
  }
  return firstFetchPromise;
}

export interface CompanyListItem {
  id: number;
  name: string;
  industry_name: string | null;
  region: string | null;
}

/** 기업 선택기 목록 — 계정이 없어 사용자가 직접 자기 기업을 고른다. */
export function getCompanies(): Promise<CompanyListItem[]> {
  return apiGet<{ companies: CompanyListItem[] }>("/companies").then((r) => r.companies);
}

export interface OwnerProgress {
  steps: {
    consent: boolean;
    upload: boolean;
    trace: boolean;
    classify: boolean;
    report: boolean;
  };
  current_step: number;
}

/** 5단계 위저드 실제 완료 상태 — DB 기준(세션 아님). 홈 화면 진행바·위저드
 * 이어하기(어느 단계부터 시작할지)가 이 값을 쓴다. */
export function getOwnerProgress(companyId: number): Promise<OwnerProgress> {
  return apiGet<OwnerProgress>(`/owner/${companyId}/progress`);
}

// GET /owner/{company_id}/notifications — 확정 전송 알림(docs/v1-plan.md §6-2,
// docs/tasks.md). 홈 화면 배너가 폴링으로 조회한다.
export interface OwnerNotification {
  id: number;
  type: string;
  message: string;
  payload: { sent_count?: number; job_id?: number; source_document_id?: number } | null;
  created_at: string;
  read_at: string | null;
}

export function getOwnerNotifications(
  companyId: number,
  unreadOnly = false,
): Promise<OwnerNotification[]> {
  const q = unreadOnly ? "?unread=true" : "";
  return apiGet<{ notifications: OwnerNotification[] }>(
    `/owner/${companyId}/notifications${q}`,
  ).then((r) => r.notifications);
}

/** 배너 클릭 시 읽음 처리. */
export function markNotificationRead(
  companyId: number,
  notificationId: number,
): Promise<{ id: number; read_at: string }> {
  return apiPatch(`/owner/${companyId}/notifications/${notificationId}/read`);
}

// GET /owner/{company_id}/rate-candidate — db/rate_products.py::rate_product_status_for_company.
// status가 "eligible"(이미 상품 자격 충족) | "upgrade_needed"(등급 개선 필요)로 갈린다.
// 이전엔 ScenePcaf.tsx 로컬 타입이었으나 web/components/RateProductCard.tsx로 카드가
// 옮겨가며 공유 타입이 됐다.
export interface RateProduct {
  product_name: string;
  provider_name: string;
  rate_discount_pct: number;
  eligibility_description: string;
  source_reference: string;
}
export interface RateMissingItem {
  document_type: DocumentType;
  fuel_label: string;
  months: number[];
}
export interface RateCandidate {
  scope_group: "scope_1" | "scope_2";
  status: "eligible" | "upgrade_needed";
  candidate_score: number;
  products?: RateProduct[];
  current_grade?: number;
  target_grade?: number;
  missing?: string;
  missing_items?: RateMissingItem[];
  benefit?: string;
  target_products?: RateProduct[];
}
export interface RateCandidateResponse {
  candidates: RateCandidate[];
  disclaimer_text: string;
}

/** 사장님 메인 화면의 우대금리 카드 — Scope별 상품 자격 상태(0~2건), 읽기 전용
 * 안내(요청 제출 플로우는 관리자측 승인요청 큐가 이번 스코프에서 빠지며 함께 보류). */
export function getRateCandidate(companyId: number): Promise<RateCandidateResponse> {
  return apiGet<RateCandidateResponse>(`/owner/${companyId}/rate-candidate`);
}

// GET /owner/{company_id}/gov-support-candidates — db/gov_support/matching.py::match_gov_support_programs.
// 개인화된 정부 지원사업 매칭(docs/gov-support-matching-plan.md 정본). 매칭 목록
// 자체는 결정론적 코사인 유사도가 결정하고, evidence만 LLM 생성(실패 시 null).
export interface GovSupportCandidate {
  program_id: number;
  program_name: string;
  agency_name: string | null;
  apply_end_date: string | null;
  detail_url: string | null;
  similarity: number;
  evidence: string | null;
}
export interface GovSupportCandidatesResponse {
  as_of: string | null;
  candidates: GovSupportCandidate[];
}

/** "혜택" 페이지의 세 번째 카드(GovSupportCard) — 우대금리·K택소노미와 같은
 * "안내 레이어" 성격, 읽기 전용(신청 후보 안내이지 선정 보장 아님).
 *
 * 기본 타임아웃(15초)보다 넉넉한 25초를 쓴다 — 백엔드가 후보별 근거문장을
 * Gemini로 병렬 생성해도(api/routers/owner.py, asyncio.gather) 개별 호출이
 * 10초 가까이 걸릴 수 있어(2026-08-18 실측: 13초대) 기본 타임아웃과 여유가
 * 거의 없었다. */
export function getGovSupportCandidates(companyId: number): Promise<GovSupportCandidatesResponse> {
  return apiGet<GovSupportCandidatesResponse>(`/owner/${companyId}/gov-support-candidates`, 25_000);
}

// GET /owner/{company_id}/reporting-years — db/pcaf_quality.py::available_reporting_years.
// 리포트 화면·데이터 업로드 탭의 연도 선택기가 공유하는 목록(전표가 있는 연도만, 최신순).
export interface ReportingYearsResponse {
  years: number[];
}
export function getReportingYears(companyId: number): Promise<ReportingYearsResponse> {
  return apiGet<ReportingYearsResponse>(`/owner/${companyId}/reporting-years`);
}

// GET /owner/{company_id}/k-taxonomy-leads — db/k_taxonomy.py::k_taxonomy_leads_for_company.
// 룰 매칭 경로에서만 채워지는 필드라(LLM 분류 경로는 항상 비어 있음) 대다수 기업·기간은
// 빈 배열이 정상이다. 이전엔 ScenePcaf.tsx 로컬 타입이었으나 web/components/KTaxonomyCard.tsx로
// 카드가 옮겨가며 공유 타입이 됐다.
export interface KTaxonomyLead {
  k_taxonomy_facility_type: string;
  k_taxonomy_candidate_type: string | null;
  finance_lead_type: string;
  hint: string;
  item_description: string;
  voucher_month: number;
  occurrence_count: number;
}
export interface KTaxonomyLeadsResponse {
  leads: KTaxonomyLead[];
}

/** 사장님 메인 화면의 K택소노미(친환경 설비 투자) 안내 카드 — 읽기 전용(요청 제출
 * 플로우는 관리자측 승인요청 큐가 이번 스코프에서 빠지며 함께 보류, 우대금리 카드와 동일). */
export function getKTaxonomyLeads(companyId: number): Promise<KTaxonomyLeadsResponse> {
  return apiGet<KTaxonomyLeadsResponse>(`/owner/${companyId}/k-taxonomy-leads`);
}

// GET /owner/{company_id}/anomaly-checks — api/queries.py::get_pending_anomaly_checks.
// 이상치 되묻기(docs/tasks.md) — 에이전트가 코드로 판별한 이상치를 사장님에게
// "맞나요?" 확인받는다. 숫자는 절대 안 받는다 — 예/아니오/모르겠어요만.
export interface AnomalyCheckItem {
  voucher_id: number;
  month: number;
  fuel: string;
  ratio: number;
}
export function getAnomalyChecks(companyId: number): Promise<AnomalyCheckItem[]> {
  return apiGet<{ items: AnomalyCheckItem[] }>(`/owner/${companyId}/anomaly-checks`).then((r) => r.items);
}

export type AnomalyCheckAnswer = "normal" | "disputed" | "unknown";

/** 이상치 확인 답변 — "아니요"·"모르겠어요"는 담당자 우선순위 알림으로 이어진다. */
export function answerAnomalyCheck(
  companyId: number,
  voucherId: number,
  body: { answer: AnomalyCheckAnswer; reason?: string },
): Promise<{ voucher_id: number; anomaly_check_status: string; status: string }> {
  return apiPatch(`/owner/${companyId}/classifications/${voucherId}/anomaly-check`, body);
}

// GET /owner/{company_id}/documents/grid — db/document_coverage.py::document_upload_grid.
// "데이터 업로드" 탭의 문서종류 × 월 그리드. status는 db/document_requirements.py
// ::required_documents가 사장님이 체크한 연료 기준으로 정한 필수/선택/해당없음이다.
// water_bill은 **의도적으로 빠져 있다.** 이 유니온은 단순 어휘 목록이 아니라
// `Record<DocumentType, ...>`의 키로 전수 사용된다(app/owner/uploads/page.tsx의 라벨 맵,
// SceneUpload.tsx의 entries) — 추가하면 그 Record들이 전부 water_bill 항목을 요구해서
// 컴파일이 깨지고, 채우면 파서도 없는 수도 칸이 화면에 생긴다(실제로 tsc가 이걸 잡았다).
// 즉 백엔드 _DOCUMENT_TYPES와 함께 열어야 하는 자리다.
export type DocumentType = "tax_invoice" | "electric_bill" | "gas_bill";
export type DocumentStatus = "required" | "optional" | "not_applicable";
export interface DocumentGridRow {
  document_type: DocumentType;
  status: DocumentStatus;
  months: Record<string, number>; // "1".."12" → 그 달 업로드 건수
}
export interface DocumentGridResponse {
  reporting_year: number;
  document_types: DocumentGridRow[];
}
export function getDocumentGrid(companyId: number, year?: number): Promise<DocumentGridResponse> {
  const q = year ? `?year=${year}` : "";
  return apiGet<DocumentGridResponse>(`/owner/${companyId}/documents/grid${q}`);
}

// GET /owner/{company_id}/upload-streak — db/document_coverage.py::upload_streak.
// 도장판 위 동기부여 배지: 필수 문서를 전부 채운 달이 이번 달 직전부터 몇 개월 연속인지.
export interface UploadStreakResponse {
  streak_months: number;
}
export function getUploadStreak(companyId: number): Promise<UploadStreakResponse> {
  return apiGet<UploadStreakResponse>(`/owner/${companyId}/upload-streak`);
}

// GET /owner/{company_id}/documents?document_type=&year=&month= — 그리드 한 칸의 파일 목록.
export interface UploadedDocument {
  id: number;
  original_filename: string | null;
  created_at: string | null;
  verification_status: string;
}
export function getDocumentsForCell(
  companyId: number,
  documentType: DocumentType,
  year: number,
  month: number
): Promise<{ documents: UploadedDocument[] }> {
  return apiGet<{ documents: UploadedDocument[] }>(
    `/owner/${companyId}/documents?document_type=${documentType}&year=${year}&month=${month}`
  );
}

// GET /owner/{company_id}/documents/{document_id}/review-status — db/document_coverage.py::
// document_pending_review_count. 업로드 완료 모달용 — 방금 올린 문서에서 만들어진 전표 중
// 몇 건이 담당자 검토 대기(review_required)인지. 판단 근거 등 세부 내용은 안 실려 온다
// (get_classifications()와 같은 원칙 — 건수만).
export function getDocumentReviewStatus(
  companyId: number,
  documentId: number
): Promise<{ pending_review_count: number }> {
  return apiGet<{ pending_review_count: number }>(
    `/owner/${companyId}/documents/${documentId}/review-status`
  );
}

// GET /owner/{company_id}/documents/jobs[/{job_id}] — 업로드 백그라운드 처리 잡
// (api/document_ingestion.py::DocumentUploadJob). 업로드 응답은 이제 job_id만
// 담고 있고, 실제 결과(document_type·month·vouchers_created 등)는 이 잡을
// done이 될 때까지 폴링해서 얻는다.
export interface UploadJob {
  job_id: number;
  status: "processing" | "done" | "failed";
  original_filename: string;
  document_type_hint: DocumentType | null;
  mode: "ocr" | "excel";
  result_source_document_id: number | null;
  result_document_type: DocumentType | null;
  result_year: number | null;
  result_month: number | null;
  vouchers_created: number | null;
  skipped_rows: number | null;
  guidance_message: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export function getUploadJob(companyId: number, jobId: number): Promise<UploadJob> {
  return apiGet<UploadJob>(`/owner/${companyId}/documents/jobs/${jobId}`);
}

/** 처리 중인 잡 목록 — 페이지 재진입 시 "N건 처리 중" 표시 복원용. */
export function getActiveUploadJobs(companyId: number): Promise<UploadJob[]> {
  return apiGet<{ jobs: UploadJob[] }>(
    `/owner/${companyId}/documents/jobs?status=processing`,
  ).then((r) => r.jobs);
}

/** job이 done|failed가 될 때까지 짧은 간격으로 반복 조회한다. 호출부가 이 Promise를
 * await하면(SceneUpload.tsx) "완료까지 기다리는" 기존 UX를 그대로 유지할 수 있고,
 * await 없이 fire-and-forget으로 두면(owner/uploads/page.tsx) 페이지를 떠나도
 * 무관하게 서버에선 계속 처리된다 — 다음 방문 때 그리드/알림으로 결과를 알 수 있다.
 * maxAttempts를 넘기면 "시간 초과"로 명확히 실패시킨다(무한정 처리 중으로 걸어두지
 * 않음 — 실패 가시성 원칙). */
export async function pollUploadJob(
  companyId: number,
  jobId: number,
  { intervalMs = 2500, maxAttempts = 60 }: { intervalMs?: number; maxAttempts?: number } = {},
): Promise<UploadJob> {
  for (let i = 0; i < maxAttempts; i++) {
    const job = await getUploadJob(companyId, jobId);
    if (job.status !== "processing") return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("업로드 처리 상태 확인이 시간 초과됐어요 — 잠시 후 새로고침해 확인해 주세요.");
}

/** 업로드 파일 삭제 — 거기서 만들어진 전표·분류까지 연쇄 삭제된다(되돌릴 수 없음). */
export function deleteDocument(
  companyId: number,
  documentId: number
): Promise<{ deleted: boolean; document_id: number }> {
  return apiDelete<{ deleted: boolean; document_id: number }>(
    `/owner/${companyId}/documents/${documentId}`
  );
}

// GET /classify/{company_id} — api/queries.py::get_unclassified_count. "데이터 업로드"
// 탭의 "분류 다시 실행" 버튼을 조건부로(실제 미분류 건이 남아있을 때만) 보여주는 용도라
// 이 값만 뽑아 쓴다(분류 결과 상세는 SceneClassify.tsx가 자체 타입으로 따로 조회).
export function getUnclassifiedCount(companyId: number): Promise<{ unclassified_count: number }> {
  return apiGet<{ unclassified_count: number }>(`/classify/${companyId}`);
}

// GET/POST /owner/{company_id}/goal, POST /owner/{company_id}/goal/{id}/cancel —
// db/pcaf_engine/company_goals.py. 5단계 위저드 완료 후 홈 화면 박스가 목표 카드로
// 바뀔 때 쓰는 API. 진행률·체크리스트는 저장값이 아니라 조회할 때마다 다시 계산된다.
export type GoalType = "emission_reduction" | "grade_upgrade";
// 월(1~12) × 연료 대분류 실측 배출량 — db/pcaf_engine/pcaf.py::monthly_by_fuel.
// 리포트(ScenePcaf.tsx)의 "월별 배출 추이"와 홈 화면 배출량 감축 목표 카드
// (GoalCard.tsx)가 완전히 같은 차트(MonthlyTrendChart.tsx)로 이 데이터를 그린다
// (사용자 요청, 2026-08-18 — 두 화면의 시각 언어를 통일).
export interface MonthlyRow {
  month: number;
  total_tco2e: number;
  by_fuel: Record<string, number>;
}
export interface MonthlyCoveragePoint {
  month: number;
  covered: boolean;
}
export interface CompanyGoal {
  id: number;
  goal_type: GoalType;
  scope_group: "scope_1" | "scope_2" | null;
  baseline_reporting_year: number;
  baseline_value: number;
  target_value: number;
  target_reduction_pct: number | null;
  target_product_name: string | null;
  status: "active" | "achieved" | "cancelled" | "superseded";
  created_at: string | null;
  achieved: boolean;
  measured: boolean;
  current_value: number | null;
  progress_pct: number;
  missing_items?: RateMissingItem[];
  disclaimer_text?: string;
  monthly_emission_detail?: MonthlyRow[]; // emission_reduction 전용 — 이번 해(또는 비교연도) 월별 배출(연료별 분해)
  monthly_coverage?: MonthlyCoveragePoint[]; // grade_upgrade 전용 — 월별 데이터 완전성(링·막대 공용)
}

export function getCompanyGoal(companyId: number): Promise<{ goal: CompanyGoal | null }> {
  return apiGet(`/owner/${companyId}/goal`);
}

export interface CreateGoalInput {
  goal_type: GoalType;
  target_reduction_pct?: number; // emission_reduction 필수
  scope_group?: "scope_1" | "scope_2"; // grade_upgrade 필수
  target_grade?: number; // grade_upgrade 선택(생략 시 추천 목표)
}

export function createCompanyGoal(
  companyId: number,
  body: CreateGoalInput,
): Promise<{ goal: CompanyGoal }> {
  return apiPost(`/owner/${companyId}/goal`, body);
}

export function cancelCompanyGoal(
  companyId: number,
  goalId: number,
): Promise<{ cancelled: boolean; goal_id: number }> {
  return apiPost(`/owner/${companyId}/goal/${goalId}/cancel`);
}

// GET /owner/{company_id}/calendar — 탄소 캘린더. 그 달의 날짜별 구매·탄소
// 배출·리포트·신청 내역을 반환. entry_type이 "voucher"인 건만 사장님에게
// 노출 가능한 분류로 필터링됨(담당자 확정·전송 완료 건 — HITL 대기 중인 건은
// 안 보임). "report"(탄소리포트 생성 시점)·"carbon_point_application"(탄소중립
// 포인트 신청서 초안 생성일)은 분류 상태와 무관하게 노출됨. 에이전트 트레이스
// (결손 감지·이상치 검증 등 내부 판단 로그)는 포함하지 않는다 — 사장님이 보고
// 싶은 건 "이날 뭘 샀고 탄소가 얼마나 나왔는지"이지 AI 활동 일지가 아니다.
export type CalendarEntryType = "voucher" | "report" | "carbon_point_application";

export interface CalendarEvent {
  date: string; // YYYY-MM-DD
  entry_type: CalendarEntryType;
  voucher_id: number | null;
  scope: number | null;
  fuel_type: string | null;
  item_description: string | null;
  supply_amount_krw: number | null;
  emission_tco2e: number | null;
  source: string;
  // 그 날짜에 같은 entry_type이 여러 건이면 몇 건이 합쳐졌는지("voucher"는 항상 1).
  // "report"·"carbon_point_application"은 날짜당 1개 이벤트로 묶여서 오므로
  // 캘린더가 점으로 뒤덮이지 않는다 — 상세 카드에 "N건"으로 표시한다.
  count: number;
}

export interface CalendarResponse {
  year: number;
  month: number;
  events: CalendarEvent[];
}

export function getOwnerCalendar(
  companyId: number,
  year?: number,
  month?: number,
): Promise<CalendarResponse> {
  const params = new URLSearchParams();
  if (year) params.set("year", String(year));
  if (month) params.set("month", String(month));
  const q = params.toString() ? `?${params.toString()}` : "";
  return apiGet(`/owner/${companyId}/calendar${q}`);
}

// GET /owner/{company_id}/briefing — 월간 AI 브리핑. 이번 달 vs 지난달
// 연료별 활동을 편지 문단(paragraphs)으로 조립해 반환. 문장은 백엔드가
// 결정론적으로 조립한 것 — 프론트는 그대로 렌더만 한다(LLM 미사용).
export interface BriefingFuelStat {
  fuel_type: string;
  this_month_co2e: number;
  last_month_co2e: number | null;
  delta_pct: number | null;
  direction: "up" | "down" | "flat" | "new";
}

export interface MonthlyBriefing {
  year: number;
  month: number;
  has_previous_month: boolean;
  paragraphs: string[];
  fuel_stats: BriefingFuelStat[];
  // "llm" | "llm_cache" | "template" — 문장이 실제 Gemini 생성인지 폴백
  // 템플릿인지 구분(서버 로그·디버깅용). 화면에는 노출하지 않는다 —
  // 사용자에게는 "AI 생성" vs "폴백" 구분 없이 편지로만 보이면 된다.
  generated_by: "llm" | "llm_cache" | "template";
}

export function getOwnerBriefing(
  companyId: number,
  year?: number,
  month?: number,
): Promise<MonthlyBriefing> {
  const params = new URLSearchParams();
  if (year) params.set("year", String(year));
  if (month) params.set("month", String(month));
  const q = params.toString() ? `?${params.toString()}` : "";
  return apiGet(`/owner/${companyId}/briefing${q}`);
}

// ── 소상공인 탄소중립포인트 (docs/small-business-green-supply-data-plan.md §9.1) ──
//
// 2026-08-25에 web/lib/carbon-point-fixture.ts를 걷고 실제 API로 붙였다. 타입은 그
// fixture가 백엔드 응답 스키마와 필드명까지 맞춰 뒀던 것을 그대로 옮긴 것이라 컴포넌트
// 수정 없이 교체됐다. `?cp=` 시나리오 토글도 함께 사라졌다.

/** 저장하지 않고 조회마다 계산되는 값(data-plan §5·§6.1) — 전기고지서 계약종별에서 유도된다.
 *
 * "가정용/개인참여"는 2026-08-25 추가(법인참여만 지원하기로 확정). 주택용 계약은 우리 트랙
 * 대상이 아니다 — 제도가 가정용을 포함하는 건 개인참여 트랙이고, 아래 포인트 구간표는 별표2
 * 상업(법인) 기준이라 포인트가 3~4배 다르다. 화면 분기는 `=== "소상공인/상업시설"` 비교로만
 * 이뤄지므로 카드는 자동으로 숨고, "미확인" 안내 박스도 뜨지 않는다(의도된 동작 — 계약종별을
 * 못 읽은 게 아니라 읽었고 대상이 아니므로 재업로드를 안내하면 거짓이 된다). */
export type BusinessScaleHint =
  | "제조업/산업체"
  | "소상공인/상업시설"
  | "가정용/개인참여"
  | "미확인";

export interface CarbonPointEligibility {
  business_scale_hint: BusinessScaleHint;
  baseline_year: number;
  target_year: number;
  /** 감탄의 자체 **예상치**. 계산에 필요한 데이터가 없으면 null(0이 아니다 — CLAUDE.md 원칙7). */
  reduction_rate_pct: number | null;
  eligible: boolean;
  /** 예: "상수도 요금고지서(수도 사용량)" — 무엇이 없어서 정확도가 떨어지는지 그대로 노출한다. */
  missing_data: string[];
}

export function getCarbonPointEligibility(
  companyId: number,
  targetYear?: number,
): Promise<CarbonPointEligibility> {
  const q = targetYear ? `?target_year=${targetYear}` : "";
  return apiGet<CarbonPointEligibility>(`/owner/${companyId}/carbon-point/eligibility${q}`);
}

export interface CarbonPointDraftField {
  label: string;
  /** 아직 못 채운 항목은 null — 빈 문자열로 가리지 않는다(실패 가시성). */
  value: string | null;
  source: string;
}

/** 3단계("없는 데이터 입력하기") 폼 한 칸의 명세 + 현재 값.
 *
 * 라벨·필수여부·선택지 어휘까지 백엔드(`db/carbon_neutral_point.py::APPLICANT_FIELDS`)가
 * 정본이다 — 프론트가 옵션 목록을 따로 들고 있으면 DB CHECK 제약과 어긋나는 값을 보낼 수
 * 있고, 그때 실패가 422로만 드러난다. 서식이 개정되면 백엔드만 고친다. */
export interface CarbonPointApplicantField {
  key: string;
  label: string;
  input_type: "text" | "tel" | "email" | "date" | "select" | "radio";
  required: boolean;
  group: string;
  placeholder: string | null;
  help_text: string | null;
  options: { value: string; label: string }[];
  /** 다른 칸의 값이 이 값일 때만 보인다(서식의 조건부 항목). 조건이 안 맞으면 렌더하지 않는다. */
  visible_when: { key: string; equals: string } | null;
  value: string | null;
}

export interface CarbonPointDraft {
  application_id: number | null;
  status: "draft" | "submitted" | "approved" | "rejected";
  fields: CarbonPointDraftField[];
  applicant_fields: CarbonPointApplicantField[];
  /** 감탄도 사장님도 여기서 채울 수 없어 안내만 하는 항목(현재는 포털 비밀번호뿐). */
  remaining_fields: string[];
  /** 초안 파일 생성이 아직 없어 항상 null — 화면은 다운로드 버튼을 비활성으로 둔다. */
  draft_document_url: string | null;
}

/** 초안 생성 — 같은 기업·같은 감축년도의 미제출 초안이 있으면 그 행을 재사용해 갱신한다.
 * 그래서 위저드를 다시 열어도 3단계 입력이 살아 있다. */
export function createCarbonPointApplication(
  companyId: number,
  targetYear?: number,
): Promise<CarbonPointDraft> {
  const q = targetYear ? `?target_year=${targetYear}` : "";
  return apiPost<CarbonPointDraft>(`/owner/${companyId}/carbon-point/applications${q}`);
}

export interface CarbonPointApplicantInputResult {
  application_id: number;
  values: Record<string, string | null>;
  /** 필수인데 아직 안 채워진 key — 화면이 "다음" 버튼을 막는 근거. */
  missing_required: string[];
}

/** 3단계 입력 저장(부분 저장). 보낸 key만 갱신되므로 폼을 다 채우기 전에도 호출할 수 있다. */
export function saveCarbonPointApplicantInput(
  companyId: number,
  applicationId: number,
  values: Record<string, string | null>,
): Promise<CarbonPointApplicantInputResult> {
  return apiPatch<CarbonPointApplicantInputResult>(
    `/owner/${companyId}/carbon-point/applications/${applicationId}/applicant-input`,
    { values },
  );
}

export { BASE_URL };
