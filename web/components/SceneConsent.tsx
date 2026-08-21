"use client";

import { useState } from "react";
import { BadgeCheck, ChevronDown, FileBarChart, IdCard, Receipt, Zap } from "lucide-react";
import { apiPost, getCompanyId } from "@/lib/api";
import { OnboardingRewardBanner } from "@/components/OnboardingRewardBanner";

/** 장면 ① — 마이데이터 연동 동의. 버튼 클릭 → Mock API로 5종 순차 수집.
 *
 * 홈택스 세금계산서·한전 전기고지서는 여기 없다 — 실제 한전·가스공사 마이데이터엔
 * 사용량(kWh 등)이 없어 "자동 수집"이 불가능하고, 반드시 업로드(OCR|엑셀)를 거쳐야
 * 하기 때문(3~4단계). 이 화면은 배출량과 무관한 기업 식별·재무 프로필 5종만 다룬다.
 *
 * 발급기관(국세청·중소벤처기업부·한국전력공사) 단위로 아코디언 박스를 묶고, 각
 * 박스 우측에 그 기관 항목들의 수집 진행률 링을 둔다 — 전부 완료되면 체크마크.
 */

type CollectResult = { source: string; extracted?: unknown };
type Phase = "consent" | "collecting" | "done" | "error";
type SourceStatus = "waiting" | "loading" | "done";

const SOURCES = [
  { key: "business-registration", icon: IdCard, name: "사업자등록증명", institutionKey: "nts", hint: "기업 식별 정보" },
  { key: "vat-tax-base", icon: Receipt, name: "부가세과세표준증명", institutionKey: "nts", hint: "매출 규모 참고" },
  { key: "financial-statement", icon: FileBarChart, name: "표준재무제표증명", institutionKey: "nts", hint: "PCAF 재무정보" },
  { key: "sme-certificate", icon: BadgeCheck, name: "중소기업확인서", institutionKey: "mss", hint: "중소기업 여부 확인" },
  { key: "kepco-payment-history", icon: Zap, name: "전기요금 납부내역", institutionKey: "kepco", hint: "결제기록(사용량은 이후 고지서 업로드에서 확인)" },
] as const;

// "국세청"은 그 자체가 이미 정식 명칭이라 줄임말이 없다 — 중기부·한전만 풀네임으로 표기.
// logo 파일은 web/public/ 에 그대로 둔다(파일이 없으면 InstitutionLogo가 자동으로
// 이니셜 뱃지로 대체 표시).
const INSTITUTIONS = [
  { key: "nts", fullName: "국세청", logo: "/nts.svg" },
  { key: "mss", fullName: "중소벤처기업부", logo: "/mss-mark.png" },
  { key: "kepco", fullName: "한국전력공사", logo: "/kepco.svg" },
] as const;

type SourceItem = (typeof SOURCES)[number];

function InstitutionLogo({ src, fallback }: { src: string; fallback: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-soft text-[13px] font-bold text-brand-ink">
        {fallback}
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- 파일 유무를 onError로 감지해야 해서 next/image 대신 사용
    <img
      src={src}
      alt=""
      className="h-9 w-9 shrink-0 rounded-full bg-white object-contain p-1 ring-1 ring-line"
      onError={() => setFailed(true)}
    />
  );
}

function ProgressRing({ total, done }: { total: number; done: number }) {
  const allDone = total > 0 && done === total;
  if (allDone) {
    return (
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand text-white">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path
            d="M3 8.5L6.2 11.5L13 4.5"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  const r = 13;
  const c = 2 * Math.PI * r;
  const pct = total === 0 ? 0 : done / total;
  return (
    <span className="relative grid h-8 w-8 shrink-0 place-items-center">
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 32 32">
        <circle cx="16" cy="16" r={r} fill="none" stroke="var(--color-line)" strokeWidth="3" />
        <circle
          cx="16"
          cy="16"
          r={r}
          fill="none"
          stroke="var(--color-brand)"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          style={{ transition: "stroke-dashoffset 0.4s ease-out" }}
        />
      </svg>
      <span className="text-[9px] font-bold text-muted">
        {done}/{total}
      </span>
    </span>
  );
}

function StatusDot({ status }: { status: SourceStatus }) {
  if (status === "done") {
    return (
      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand text-white">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
          <path
            d="M3 8.5L6.2 11.5L13 4.5"
            stroke="currentColor"
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  if (status === "loading") {
    return <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-line border-t-brand" />;
  }
  return <span className="h-5 w-5 shrink-0 rounded-full border-2 border-line" />;
}

export function SceneConsent({ onNext }: { onNext: () => void }) {
  const [phase, setPhase] = useState<Phase>("consent");
  const [agreed, setAgreed] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sourceStatus, setSourceStatus] = useState<Record<string, SourceStatus>>(
    Object.fromEntries(SOURCES.map((s) => [s.key, "waiting" as SourceStatus])),
  );
  const [error, setError] = useState<string | null>(null);

  function toggle(key: string) {
    setExpanded((e) => {
      const next = new Set(e);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function connect() {
    setPhase("collecting");
    setError(null);
    setSourceStatus(Object.fromEntries(SOURCES.map((s) => [s.key, "loading" as SourceStatus])));
    try {
      const cid = await getCompanyId();
      // 5종을 순차 await하면 매번 왕복 지연이 누적된다 — 서로 독립적인 호출이라
      // 병렬로 쏘고, 완료되는 대로 각자 상태만 개별 업데이트한다("클릭 1회, 즉시 반응").
      const results = await Promise.allSettled(
        SOURCES.map((s) =>
          apiPost<CollectResult>(`/mock/${s.key}/${cid}`).then(() => {
            setSourceStatus((st) => ({ ...st, [s.key]: "done" }));
          }),
        ),
      );
      const failed = results.some((r) => r.status === "rejected");
      if (failed) throw new Error("일부 항목 수집 실패");
      setPhase("done");
    } catch (err) {
      console.error("마이데이터 수집 실패:", err);
      setError("데이터 수집에 실패했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
      setPhase("error");
    }
  }

  return (
    <section className="pt-4">
      <h2 className="text-[21px] font-bold leading-snug text-ink">
        먼저 기업 정보부터
        <br />
        확인할게요
      </h2>
      <p className="mt-2 text-[14px] leading-relaxed text-muted">
        국세청·중소벤처기업부·한국전력공사 마이데이터로
        <br />
        기업 식별·재무 정보를 자동으로 확인해요.
      </p>

      <div className="mt-6 space-y-2.5">
        {INSTITUTIONS.map((inst) => {
          const sources: SourceItem[] = SOURCES.filter((s) => s.institutionKey === inst.key);
          const done = sources.filter((s) => sourceStatus[s.key] === "done").length;
          const isExpanded = expanded.has(inst.key);
          return (
            <div key={inst.key} className="overflow-hidden rounded-2xl bg-surface">
              <button
                type="button"
                onClick={() => toggle(inst.key)}
                className="flex w-full items-center gap-3.5 p-4 text-left"
              >
                <InstitutionLogo src={inst.logo} fallback={inst.fullName[0]} />
                <div className="min-w-0 flex-1">
                  <div className="text-[14.5px] font-bold text-ink">{inst.fullName}</div>
                </div>
                <ChevronDown
                  size={16}
                  className={`shrink-0 text-faint transition-transform ${isExpanded ? "rotate-180" : ""}`}
                />
                <ProgressRing total={sources.length} done={done} />
              </button>

              {isExpanded && (
                <div className="space-y-2.5 border-t border-line px-4 py-3.5">
                  {sources.map((s) => (
                    <div key={s.key} className="flex items-center gap-3">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-ink">
                        <s.icon size={16} strokeWidth={2} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] font-semibold text-ink">{s.name}</div>
                        <div className="text-[11.5px] text-muted">{s.hint}</div>
                      </div>
                      <StatusDot status={sourceStatus[s.key]} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {phase === "consent" && (
        <label className="mt-5 flex items-center gap-2.5 text-[13.5px] font-medium text-ink">
          <button
            type="button"
            role="checkbox"
            aria-checked={agreed}
            onClick={() => setAgreed((v) => !v)}
            className={`grid h-5 w-5 shrink-0 place-items-center rounded-md transition-colors ${
              agreed ? "bg-brand" : "bg-line"
            }`}
          >
            {agreed && (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <path
                  d="M3 8.5L6.2 11.5L13 4.5"
                  stroke="white"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </button>
          마이데이터 제공·활용에 동의합니다
        </label>
      )}

      {error && (
        <div className="mt-4 rounded-xl bg-hitl/25 px-3.5 py-2.5 text-[12.5px] text-hitl-ink">
          {error}
        </div>
      )}

      {/* 연동이 실제로 끝난 뒤에만 리워드 안내를 보여준다 — 수집 실패(phase === "error")
          상태에서 혜택 안내가 뜨면 안 된다(develop-plan §3.1). */}
      {phase === "done" && <OnboardingRewardBanner />}

      {/* 버튼은 항상 같은 자리에 있고, 진행 중엔 사라지는 대신 살짝 블러 처리된 채로 상태 문구만 바뀐다. */}
      <button
        type="button"
        onClick={phase === "done" ? onNext : connect}
        disabled={phase === "collecting" || (phase === "consent" && !agreed)}
        className={`btn-cta mt-4 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white transition-all duration-300 ${
          phase === "collecting" ? "blur-[1.5px] opacity-70" : ""
        }`}
      >
        {phase === "consent" && "동의하고 연동 시작"}
        {phase === "collecting" && "마이데이터 연동 중..."}
        {phase === "done" && "확인 완료 · 다음으로"}
        {phase === "error" && "다시 시도"}
      </button>

      {phase === "consent" && (
        <p className="mt-3 text-center text-[11.5px] text-faint">
          클릭 1회로 {SOURCES.length}개 항목 확인이 시작됩니다
        </p>
      )}
    </section>
  );
}
