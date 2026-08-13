"use client";

// review-log/documents-access-log/quality-issues 3개 관리자 로그 탭이 공유하는
// 서버사이드 페이지네이션 상태 관리 — 검색어 입력 시 300ms debounce 후 1페이지로
// 리셋해 재조회한다.
import { useEffect, useRef, useState } from "react";
import type { PageMeta } from "@/lib/admin-types";
import type { PageParams } from "@/lib/admin-data";

const SEARCH_DEBOUNCE_MS = 300;

export function usePaginatedLog<T>(
  fetcher: (params: PageParams) => Promise<T & PageMeta>,
  pageSize = 50,
  /** 넘기면 검색창 대신 이 기업명으로 고정 필터한다 — 기업 상세 탭이 사용. */
  fixedCompanyName?: string,
) {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [companyName, setCompanyName] = useState(fixedCompanyName ?? "");
  const [data, setData] = useState<(T & PageMeta) | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // 검색어 입력을 debounce해 companyName(실제 조회 트리거)에 반영 — 1페이지로 리셋.
  // 고정 필터 모드(fixedCompanyName)에서는 검색창 자체가 없으니 이 effect가 불필요.
  useEffect(() => {
    if (fixedCompanyName !== undefined) return;
    const timer = setTimeout(() => {
      setPage(1);
      setCompanyName(searchInput);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput, fixedCompanyName]);

  // 고정 필터 대상 기업이 바뀌면(다른 기업 선택) 1페이지로 리셋해 재조회.
  useEffect(() => {
    if (fixedCompanyName === undefined) return;
    setPage(1);
    setCompanyName(fixedCompanyName);
  }, [fixedCompanyName]);

  const load = (targetPage: number, name: string) => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    fetcherRef
      .current({ page: targetPage, pageSize, companyName: name })
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
    load(page, companyName);
    // page/companyName 변경 시에만 재조회.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, companyName, pageSize]);

  return {
    data,
    loading,
    error,
    page,
    setPage,
    searchInput,
    setSearchInput,
    retry: () => load(page, companyName),
  };
}
