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

let companyIdPromise: Promise<number> | null = null;

/**
 * 시연 기업 ID — GET /company 로 조회(모듈 캐시). 실패 시 캐시를 비우고
 * 에러를 그대로 던진다(호출한 Scene 의 에러 배너로 표시 — 무음 폴백 없음).
 */
export function getCompanyId(): Promise<number> {
  if (!companyIdPromise) {
    companyIdPromise = apiGet<{ id: number }>(`/company`)
      .then((c) => c.id)
      .catch((err) => {
        companyIdPromise = null; // 다음 시도에서 재조회
        throw err;
      });
  }
  return companyIdPromise;
}

export { BASE_URL };
