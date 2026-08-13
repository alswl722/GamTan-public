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
export interface RateCandidate {
  scope_group: "scope_1" | "scope_2";
  status: "eligible" | "upgrade_needed";
  candidate_score: number;
  products?: RateProduct[];
  current_grade?: number;
  target_grade?: number;
  missing?: string;
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

export { BASE_URL };
