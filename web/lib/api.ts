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

/** 문서 업로드는 PaddleOCR(로컬 추론) 처리가 포함돼 기본 15초로는 부족할 수 있다
 * (모델 최초 로딩 시 특히) — apiUpload 호출부(SceneUpload.tsx, owner/uploads/page.tsx)
 * 에서 이 값을 timeoutMs로 넘긴다. */
export const DOCUMENT_UPLOAD_TIMEOUT_MS = 60_000;

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

// GET /owner/{company_id}/documents/grid — db/document_coverage.py::document_upload_grid.
// "데이터 업로드" 탭의 문서종류 × 월 그리드. status는 db/document_requirements.py
// ::required_documents가 사장님이 체크한 연료 기준으로 정한 필수/선택/해당없음이다.
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

/** 업로드 파일 삭제 — 거기서 만들어진 전표·분류까지 연쇄 삭제된다(되돌릴 수 없음). */
export function deleteDocument(
  companyId: number,
  documentId: number
): Promise<{ deleted: boolean; document_id: number }> {
  return apiDelete<{ deleted: boolean; document_id: number }>(
    `/owner/${companyId}/documents/${documentId}`
  );
}

export { BASE_URL };
