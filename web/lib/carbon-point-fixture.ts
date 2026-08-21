"use client";

import { useSyncExternalStore } from "react";

/** 탄소중립포인트 화면의 **임시 대역(fixture)** — API 경계의 유일한 지점.
 * docs/small-business-green-supply-develop-plan.md §3.0 정본.
 *
 * ⚠️ 이 파일은 백엔드 §9.1 API가 나오면 **삭제 대상**이다. 교체 절차:
 *   1. `web/lib/api.ts`에 아래 타입(CarbonPointEligibility·CarbonPointDraft)을 그대로 옮기고
 *      `getCarbonPointEligibility(companyId)` / `createCarbonPointApplication(companyId)`를 추가
 *      (data-plan.md §9.1: GET /owner/{id}/carbon-point/eligibility,
 *       POST /owner/{id}/carbon-point/applications)
 *   2. `useCarbonPointScenario()` + `getEligibilityFixture()` 호출부를 그 fetch로 교체
 *      — 현재 호출부는 세 곳뿐이다:
 *          web/components/CarbonPointCard.tsx        (자격 + getDraftFixture)
 *          web/components/CarbonPointNoticeBanner.tsx (자격)
 *          web/app/owner/benefits/page.tsx           (자격 + resolveScenario로 조회 게이팅)
 *        CarbonPointDraftSheet.tsx는 타입과 칩 문구만 import하므로 교체 대상이 아니다.
 *   3. 이 파일과 `?cp=` 쿼리 규약, FIXTURE_BADGE_LABEL 칩을 함께 제거
 *
 * 타입은 §9.1 응답 스키마와 **필드명까지 동일**하게 맞춰 뒀다 — 그래야 위 교체가
 * 컴포넌트 수정 없이 끝난다. `is_estimate` 같은 플래그는 의도적으로 없다
 * (develop-plan §2.2·data-plan §14-8 확정: 이 경로는 항상 예상치만 반환하므로
 * 항상 true인 플래그는 정보량이 없고, "예상치" 표기는 프론트 정적 문구가 담당한다).
 */

/** 저장하지 않고 조회마다 계산되는 값(data-plan §5·§6.1) — 전기고지서 계약종별에서 유도된다. */
export type BusinessScaleHint = "제조업/산업체" | "소상공인/상업시설" | "미확인";

/** GET /owner/{company_id}/carbon-point/eligibility */
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

export interface CarbonPointDraftField {
  label: string;
  /** 아직 못 채운 항목은 null — 빈 문자열로 가리지 않는다(실패 가시성). */
  value: string | null;
  source: string;
}

/** POST /owner/{company_id}/carbon-point/applications 의 초안 응답 */
export interface CarbonPointDraft {
  application_id: number | null;
  status: "draft" | "submitted" | "approved" | "rejected";
  /** 실물 hwp 서식 미확인(data-plan §14-1)이라 배열을 그대로 렌더한다 — 서식이 확인되면 이 배열만 고친다. */
  fields: CarbonPointDraftField[];
  /** 마이데이터에 없어 사장님이 직접 입력해야 하는 항목(data-plan §6.3 "잔여 필드"). */
  remaining_fields: string[];
  /** 초안 생성 함수(§2.3)가 아직 없어 항상 null — 화면은 다운로드 버튼을 비활성으로 둔다. */
  draft_document_url: string | null;
}

/** 탄소중립포인트 에너지분야 자격 임계값(data-plan §6.2). 화면 문구에서 공유한다. */
export const CARBON_POINT_THRESHOLD_PCT = 5;

/** fixture로 그린 화면임을 사용자에게 그대로 알리는 칩 문구(data-plan §3.3 — 실제
 * 파이프라인이 아니라는 사실을 화면에 명시). API 연동 시 이 상수와 함께 사라진다. */
export const FIXTURE_BADGE_LABEL = "예시 데이터 · API 연동 전";

export type CarbonPointScenario =
  | "manufacturing"
  | "commercial_eligible"
  | "commercial_not_eligible"
  | "unknown";

/** 쿼리 없이 들어온 화면은 기존과 완전히 동일해야 한다 — 그래서 기본값이 제조업이다
 * (제조업 분기는 탄소중립포인트 카드를 숨기므로 회귀가 없다). */
export const DEFAULT_SCENARIO: CarbonPointScenario = "manufacturing";

const SCENARIO_KEYS: readonly CarbonPointScenario[] = [
  "manufacturing",
  "commercial_eligible",
  "commercial_not_eligible",
  "unknown",
];

const ELIGIBILITY_FIXTURES: Record<CarbonPointScenario, CarbonPointEligibility> = {
  // 산업용 전기 계약 → 탄소중립포인트 에너지분야 원천 제외(data-plan §6.2). 감축률을
  // 계산하지 않으므로 null이다.
  manufacturing: {
    business_scale_hint: "제조업/산업체",
    baseline_year: 2024,
    target_year: 2025,
    reduction_rate_pct: null,
    eligible: false,
    missing_data: [],
  },
  // 전기·가스만으로 임계값을 넘긴 상태. 수도 데이터가 없다는 사실은 숨기지 않는다.
  commercial_eligible: {
    business_scale_hint: "소상공인/상업시설",
    baseline_year: 2024,
    target_year: 2025,
    reduction_rate_pct: 7.4,
    eligible: true,
    missing_data: ["상수도 요금고지서(수도 사용량)"],
  },
  commercial_not_eligible: {
    business_scale_hint: "소상공인/상업시설",
    baseline_year: 2024,
    target_year: 2025,
    reduction_rate_pct: 2.1,
    eligible: false,
    missing_data: [],
  },
  // 계약종별을 못 읽은 상태 → HITL(data-plan §6.1). 판별 실패라 감축률도 없다.
  unknown: {
    business_scale_hint: "미확인",
    baseline_year: 2024,
    target_year: 2025,
    reduction_rate_pct: null,
    eligible: false,
    missing_data: ["전기요금고지서의 계약종별"],
  },
};

/** 잘못된 값·빈 쿼리는 조용히 기본값으로 떨어진다 — 데모 중 오타로 화면이 깨지지 않게. */
export function resolveScenario(search: string): CarbonPointScenario {
  const raw = new URLSearchParams(search).get("cp");
  if (raw === null) return DEFAULT_SCENARIO;
  return SCENARIO_KEYS.find((key) => key === raw) ?? DEFAULT_SCENARIO;
}

export function getEligibilityFixture(scenario: CarbonPointScenario): CarbonPointEligibility {
  return ELIGIBILITY_FIXTURES[scenario];
}

/** 초안 필드는 eligibility와 어긋나면 안 된다(같은 화면에 두 숫자가 다르게 보이면 안 됨)
 * — 감축률·연도는 위 fixture에서 그대로 가져와 채운다.
 *
 * 값은 전부 명백한 예시다(사업자번호 000-00-00000, 대표자 김○○) — fixture라는 걸
 * 숨기지 않는다. 매핑 출처는 data-plan §6.3의 잠정 매핑표를 그대로 따랐다. */
export function getDraftFixture(scenario: CarbonPointScenario): CarbonPointDraft {
  const e = getEligibilityFixture(scenario);
  const rate = e.reduction_rate_pct;
  return {
    application_id: null,
    status: "draft",
    fields: [
      { label: "사업자명 / 대표자", value: "행복상회 / 김○○", source: "마이데이터 · 사업자등록증명" },
      { label: "사업자등록번호", value: "000-00-00000", source: "마이데이터 · 사업자등록증명" },
      { label: "사업장 주소", value: "대구광역시 중구 ○○로 00", source: "마이데이터 · 사업자등록증명" },
      // data-plan §6.3이 "Company 또는 InstitutionBorrower (확인 필요)"로 남겨둔 항목 —
      // 확인되기 전까진 값을 지어내지 않고 null로 둔다.
      { label: "담당자 연락처", value: null, source: "출처 확인 중(data-plan §6.3)" },
      {
        label: `기준년도(${e.baseline_year}) 사용량`,
        value: "전기 12,480 kWh · 도시가스 1,120 m³",
        source: "감탄 계산값",
      },
      {
        label: `감축년도(${e.target_year}) 사용량`,
        value: "전기 11,560 kWh · 도시가스 1,038 m³",
        source: "감탄 계산값",
      },
      {
        label: "예상 감축률",
        value: rate === null ? null : `${rate}%`,
        source: "감탄 계산값(예상치)",
      },
    ],
    remaining_fields: ["계좌정보(은행 · 계좌번호 · 예금주) — 마이데이터에 없어 사장님이 직접 입력해야 해요"],
    draft_document_url: null,
  };
}

// ---------------------------------------------------------------------------
// 시나리오 토글 — URL 쿼리 ?cp= 를 읽는다.
//
// useSearchParams()를 쓰지 않는다: 정적 프리렌더 라우트에서 Suspense 경계를 요구해
// 기존 페이지 구조를 건드려야 하기 때문. useEffect + setState도 쓰지 않는다: 이
// 프로젝트 lint(react-hooks/set-state-in-effect)가 error로 잡는다. 브라우저의 외부
// 상태를 읽는 정석 훅인 useSyncExternalStore를 쓰면 서버 스냅숏(기본 시나리오)과
// 클라이언트 스냅숏(실제 쿼리)을 React가 알아서 맞춰준다 — 하이드레이션 경고도 없다.
// ---------------------------------------------------------------------------

function subscribe(onChange: () => void): () => void {
  // 뒤로/앞으로 이동으로 쿼리가 바뀌는 경우만 반영하면 충분하다(데모용 토글).
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function getClientSnapshot(): CarbonPointScenario {
  return resolveScenario(window.location.search);
}

function getServerSnapshot(): CarbonPointScenario {
  return DEFAULT_SCENARIO;
}

export function useCarbonPointScenario(): CarbonPointScenario {
  return useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot);
}
