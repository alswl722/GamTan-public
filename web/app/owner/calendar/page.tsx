"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  getCompanyId,
  getOwnerCalendar,
  type CalendarEvent,
  type CalendarResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 탄소 캘린더 — Figma "⑨ 탄소 캘린더" 시안. 월 그리드에 그 달 이벤트를
// 날짜별 점으로 표시하고, 날짜를 탭하면 아래에 그날 이벤트가 상세히 펼쳐진다.
// 조회 전용 — 여기서 데이터를 수정하지 않는다(확정/반려는 여전히 담당자 HITL 몫).

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function buildWeeks(year: number, month: number): (number | null)[][] {
  const firstDay = new Date(year, month - 1, 1).getDay(); // 0=일요일
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function eventDotColor(e: CalendarEvent): string {
  if (e.entry_type === "trace") return "bg-brand";
  if (e.scope === 1) return "bg-scope1";
  if (e.scope === 2) return "bg-scope2";
  return "bg-muted";
}

export default function CarbonCalendarPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<{ year: number; month: number } | null>(null);
  const [selectedDay, setSelectedDay] = useState<number | null>(null);

  useEffect(() => {
    getCompanyId()
      .then((cid) => {
        setCompanyId(cid);
        const now = new Date();
        setCursor({ year: now.getFullYear(), month: now.getMonth() + 1 });
      })
      .catch((err) => {
        console.error("기업 정보 조회 실패:", err);
        setError("기업 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      });
  }, []);

  useEffect(() => {
    if (companyId === null || cursor === null) return;
    let cancelled = false;
    getOwnerCalendar(companyId, cursor.year, cursor.month)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setSelectedDay(null);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("캘린더 조회 실패:", err);
        setError("캘린더를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, cursor]);

  // data가 지금 보려는 달(cursor)의 응답인지로 로딩 여부를 판단 — effect 안에서
  // setData(null)을 직접 호출하지 않고도 "달 전환 직후엔 이전 달 데이터를
  // 순간적으로 보여주지 않는다"를 달성한다.
  const isLoadingCurrentMonth =
    cursor !== null && (!data || data.year !== cursor.year || data.month !== cursor.month);

  const eventsByDay = useMemo(() => {
    const map = new Map<number, CalendarEvent[]>();
    if (!data) return map;
    for (const e of data.events) {
      const day = Number(e.date.split("-")[2]);
      const list = map.get(day) ?? [];
      list.push(e);
      map.set(day, list);
    }
    return map;
  }, [data]);

  function shiftMonth(delta: number) {
    setCursor((prev) => {
      if (!prev) return prev;
      const d = new Date(prev.year, prev.month - 1 + delta, 1);
      return { year: d.getFullYear(), month: d.getMonth() + 1 };
    });
  }

  const weeks = cursor ? buildWeeks(cursor.year, cursor.month) : [];
  const selectedEvents = selectedDay !== null ? eventsByDay.get(selectedDay) ?? [] : [];

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-16">
      <div className="pt-5">
        <Link
          href="/owner"
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-faint transition-colors hover:text-ink"
        >
          ← 홈으로
        </Link>
      </div>

      <h1 className="mt-4 text-[17px] font-bold leading-snug text-ink">탄소 캘린더</h1>

      {error ? (
        <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
          {error}
        </div>
      ) : !cursor || isLoadingCurrentMonth || !data ? (
        <p className="mt-4 text-[13px] text-faint">불러오는 중…</p>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          {/* 이번 달 브리핑 축약 카드 */}
          <Link
            href="/owner/briefing"
            className="btn-cta flex items-center gap-2.5 rounded-2xl bg-brand-soft px-3.5 py-3 transition-transform"
          >
            <span className="text-2xl leading-none">🌳</span>
            <span className="flex-1">
              <span className="block text-[12px] font-bold text-brand-ink">
                우디의 {cursor.month}월 브리핑 도착!
              </span>
              <span className="block text-[11px] text-brand-ink">이번 달 편지 읽어보기</span>
            </span>
            <span className="text-[18px] font-bold text-brand-ink">›</span>
          </Link>

          {/* 캘린더 카드 */}
          <div className="rounded-3xl bg-surface p-4 shadow-card">
            <div className="flex items-center justify-between px-1">
              <button
                type="button"
                onClick={() => shiftMonth(-1)}
                className="px-2 text-[15px] font-bold text-muted"
                aria-label="이전 달"
              >
                ‹
              </button>
              <span className="text-[15px] font-extrabold text-ink">
                {cursor.year}년 {cursor.month}월
              </span>
              <button
                type="button"
                onClick={() => shiftMonth(1)}
                className="px-2 text-[15px] font-bold text-muted"
                aria-label="다음 달"
              >
                ›
              </button>
            </div>

            <div className="mt-3 grid grid-cols-7 text-center">
              {WEEKDAYS.map((d, i) => (
                <span
                  key={d}
                  className={cn(
                    "text-[11px] font-bold",
                    i === 0 ? "text-faint" : "text-muted",
                  )}
                >
                  {d}
                </span>
              ))}
            </div>

            <div className="mt-1.5 flex flex-col gap-1.5">
              {weeks.map((week, wi) => (
                <div key={wi} className="grid grid-cols-7">
                  {week.map((day, di) => {
                    if (day === null) return <div key={di} />;
                    const events = eventsByDay.get(day) ?? [];
                    const isSelected = day === selectedDay;
                    return (
                      <button
                        key={di}
                        type="button"
                        onClick={() => setSelectedDay(isSelected ? null : day)}
                        className="flex flex-col items-center gap-1 py-1"
                      >
                        <span
                          className={cn(
                            "flex h-[26px] w-[26px] items-center justify-center rounded-full text-[12px] font-bold",
                            isSelected
                              ? "bg-brand text-white"
                              : di === 0
                                ? "text-faint"
                                : "text-ink",
                          )}
                        >
                          {day}
                        </span>
                        <span className="flex h-1.5 items-center gap-0.5">
                          {events.slice(0, 3).map((e, ei) => (
                            <span
                              key={ei}
                              className={cn("h-1 w-1 rounded-full", eventDotColor(e))}
                            />
                          ))}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="mt-3 flex items-center gap-3.5 px-1">
              <span className="flex items-center gap-1 text-[10px] font-medium text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-scope1" />
                경유·유류(Scope1)
              </span>
              <span className="flex items-center gap-1 text-[10px] font-medium text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-scope2" />
                전기(Scope2)
              </span>
              <span className="flex items-center gap-1 text-[10px] font-medium text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-brand" />
                AI 측정 활동
              </span>
            </div>
          </div>

          {/* 선택된 날짜 상세 */}
          {selectedDay !== null && (
            <div className="rounded-3xl bg-surface shadow-card">
              <div className="flex items-center justify-between px-5 py-4">
                <span className="text-[14px] font-bold text-ink">
                  {cursor.month}월 {selectedDay}일
                </span>
                <span className="rounded-full bg-bg px-2 py-0.5 text-[10px] font-bold text-muted">
                  {selectedEvents.length}건
                </span>
              </div>
              {selectedEvents.length === 0 ? (
                <p className="px-5 pb-4 text-[12.5px] text-faint">이날은 기록된 활동이 없어요.</p>
              ) : (
                selectedEvents.map((e, i) => (
                  <div
                    key={i}
                    className={cn(
                      "flex items-start gap-2.5 px-5 py-3",
                      i < selectedEvents.length - 1 && "border-b border-line",
                    )}
                  >
                    <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", eventDotColor(e))} />
                    <div className="min-w-0 flex-1">
                      {e.entry_type === "voucher" ? (
                        <>
                          <span className="mb-1 inline-block rounded bg-bg px-1.5 py-0.5 text-[9px] font-bold text-muted">
                            {e.source === "kepco" ? "전기고지서" : "세금계산서"}
                          </span>
                          <p className="text-[13px] font-bold text-ink">
                            {e.item_description ?? "전표"}
                            {e.supply_amount_krw != null &&
                              ` · ${e.supply_amount_krw.toLocaleString("ko-KR")}원`}
                          </p>
                          {e.fuel_type && (
                            <p className="text-[11px] text-faint">
                              Scope {e.scope} · {e.fuel_type}
                            </p>
                          )}
                        </>
                      ) : (
                        <>
                          <span className="mb-1 inline-block rounded bg-bg px-1.5 py-0.5 text-[9px] font-bold text-muted">
                            AI 활동 · {e.step_type}
                          </span>
                          <p className="text-[13px] font-bold text-ink">{e.message}</p>
                        </>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
