/**
 * 백엔드(FastAPI) 호출 래퍼 — v0.1 뼈대.
 * 지금은 와이어프레임 단계라 실제 호출은 없다. 8월 확장 시 각 Scene 이 여기를 통해 API 를 부른다.
 */
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} 실패: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export { BASE_URL };
