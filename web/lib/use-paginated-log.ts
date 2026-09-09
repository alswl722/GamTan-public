"use client";

// review-log/documents-access-log 등 관리자 로그 탭이 공유하는 서버사이드
// 페이지네이션 상태 관리 — 검색어 입력 시 300ms debounce 후 1페이지로 리셋해
// 재조회한다.
import { useEffect, useRef, useState } from "react";
import type { PageMeta } from "@/lib/admin-types";
import type { PageParams } from "@/lib/admin-data";

const SEARCH_DEBOUNCE_MS = 300;

export interface DateRange {
  fromTime?: string;
  toTime?: string;
}

export function usePaginatedLog<T>(
  fetcher: (params: PageParams) => Promise<T & PageMeta>,
  pageSize = 50,
  /** 넘기면 검색창 대신 이 기업으로 정확히 고정 필터한다(company_id 일치) —
   * 기업 상세 탭이 사용. 이름 부분일치가 아니라 id 기준이라 비슷한 이름의
   * 다른 기업 로그가 섞이지 않는다. */
  fixedCompanyId?: number,
  /** 기간 필터(ISO 문자열) — traces 탭의 기간 프리셋용. 바뀌면 1페이지로 리셋.
   * review-log/access-log는 안 넘기므로 옵셔널. */
  dateRange?: DateRange,
) {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [data, setData] = useState<(T & PageMeta) | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const fromTime = dateRange?.fromTime;
  const toTime = dateRange?.toTime;

  // 검색어 입력을 debounce해 companyName(실제 조회 트리거)에 반영 — 1페이지로 리셋.
  // 고정 필터 모드(fixedCompanyId)에서는 검색창 자체가 없으니 이 effect가 불필요.
  useEffect(() => {
    if (fixedCompanyId !== undefined) return;
    const timer = setTimeout(() => {
      setPage(1);
      setCompanyName(searchInput);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput, fixedCompanyId]);

  // 고정 필터 대상 기업이 바뀌면(다른 기업 선택) 1페이지로 리셋해 재조회.
  useEffect(() => {
    if (fixedCompanyId === undefined) return;
    setPage(1);
  }, [fixedCompanyId]);

  // 기간 필터가 바뀌면 1페이지로 리셋해 재조회.
  useEffect(() => {
    setPage(1);
  }, [fromTime, toTime]);

  const load = (
    targetPage: number,
    name: string,
    companyId: number | undefined,
    from: string | undefined,
    to: string | undefined,
  ) => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    fetcherRef
      .current({ page: targetPage, pageSize, companyName: name, companyId, fromTime: from, toTime: to })
      .then((res) => {
        if (id !== requestId.current) return; // 늦게 도착한 응답 무시(경쟁 상태 방지)
        setData(res);
      })
      .catch((err) => {
        if (id !== requestId.current) return;
        console.error("로그 조회 실패:", err);
        setError("조회에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      })
      .finally(() => {
        if (id !== requestId.current) return;
        setLoading(false);
      });
  };

  useEffect(() => {
    load(page, companyName, fixedCompanyId, fromTime, toTime);
    // page/companyName/fixedCompanyId/fromTime/toTime 변경 시에만 재조회.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, companyName, fixedCompanyId, fromTime, toTime, pageSize]);

  return {
    data,
    loading,
    error,
    page,
    setPage,
    searchInput,
    setSearchInput,
    retry: () => load(page, companyName, fixedCompanyId, fromTime, toTime),
  };
}
