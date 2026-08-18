"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  createCompanyGoal,
  getRateCandidate,
  type CompanyGoal,
  type RateCandidate,
  type RateCandidateResponse,
} from "@/lib/api";

/** 홈 화면 목표 설정 바텀시트 — 탭 2개(배출량 감축 / 등급 올리기, 기획 결정으로 등급
 * 탭 안에 상품 조건 충족 안내가 같이 붙는다). 이 프로젝트에 아직 모달/바텀시트
 * 패턴이 없어 새로 만든다 — 카드 셸(rounded-3xl bg-surface shadow-card)은 기존
 * 규칙을 그대로 따른다. */

const SCOPE_LABEL: Record<string, string> = { scope_1: "Scope 1", scope_2: "Scope 2" };
const REDUCTION_PRESETS = [10, 20, 30];

export function GoalSheet({
  companyId,
  onClose,
  onSaved,
}: {
  companyId: number;
  onClose: () => void;
  onSaved: (goal: CompanyGoal) => void;
}) {
  const [tab, setTab] = useState<"emission_reduction" | "grade_upgrade">("emission_reduction");
  const [pct, setPct] = useState<number>(10);
  const [customPct, setCustomPct] = useState("");

  const [candidates, setCandidates] = useState<RateCandidateResponse | null>(null);
  const [scopeGroup, setScopeGroup] = useState<"scope_1" | "scope_2" | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRateCandidate(companyId)
      .then((r) => {
        setCandidates(r);
        if (r.candidates.length > 0) setScopeGroup(r.candidates[0].scope_group);
      })
      .catch((err) => console.error("등급 후보 조회 실패:", err));
  }, [companyId]);

  const selectedCandidate: RateCandidate | undefined = candidates?.candidates.find(
    (c) => c.scope_group === scopeGroup
  );

  async function submit() {
    setError(null);

    if (tab === "emission_reduction") {
      const value = customPct ? Number(customPct) : pct;
      if (!Number.isFinite(value) || value <= 0 || value >= 100) {
        setError("1~99 사이의 감축률을 입력해주세요.");
        return;
      }
      setSubmitting(true);
      try {
        const res = await createCompanyGoal(companyId, {
          goal_type: "emission_reduction",
          target_reduction_pct: value,
        });
        onSaved(res.goal);
      } catch (err) {
        console.error("목표 생성 실패:", err);
        setError("목표를 저장하지 못했어요. 잠시 후 다시 시도해주세요.");
      } finally {
        setSubmitting(false);
      }
      return;
    }

    if (!scopeGroup) {
      setError("먼저 데이터가 있는 Scope를 선택해주세요.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await createCompanyGoal(companyId, {
        goal_type: "grade_upgrade",
        scope_group: scopeGroup,
      });
      onSaved(res.goal);
    } catch (err) {
      console.error("목표 생성 실패:", err);
      setError("목표를 저장하지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-t-3xl bg-surface px-5 pb-8 pt-4 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <span className="text-[16px] font-extrabold text-ink">목표 설정</span>
          <button type="button" onClick={onClose} className="p-1 text-faint" aria-label="닫기">
            <X size={20} />
          </button>
        </div>

        <div className="mt-4 flex gap-1.5 rounded-full bg-bg p-1">
          {(
            [
              { key: "emission_reduction" as const, label: "배출량 감축" },
              { key: "grade_upgrade" as const, label: "등급 올리기" },
            ]
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`flex-1 rounded-full py-2 text-[13px] font-bold transition-colors ${
                tab === t.key ? "bg-surface text-ink shadow-card" : "text-faint"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "emission_reduction" ? (
          <div className="mt-5">
            <p className="text-[12.5px] text-muted">올해 배출량 대비 몇 % 감축을 목표로 할까요?</p>
            <div className="mt-3 flex gap-2">
              {REDUCTION_PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => {
                    setPct(p);
                    setCustomPct("");
                  }}
                  className={`flex-1 rounded-2xl py-3 text-[14px] font-extrabold transition-colors ${
                    !customPct && pct === p ? "bg-brand text-white" : "bg-bg text-ink"
                  }`}
                >
                  {p}%
                </button>
              ))}
            </div>
            <input
              type="number"
              inputMode="numeric"
              placeholder="직접 입력 (%)"
              value={customPct}
              onChange={(e) => setCustomPct(e.target.value)}
              className="mt-2 w-full rounded-2xl bg-bg px-4 py-3 text-[14px] font-semibold text-ink outline-none"
            />
            <p className="mt-2 text-[11px] leading-relaxed text-faint">
              다음 측정 때 실제로 줄었는지 비교해서 진행률을 보여드려요.
            </p>
          </div>
        ) : (
          <div className="mt-5">
            {candidates === null ? (
              <p className="text-[12.5px] text-muted">불러오는 중…</p>
            ) : candidates.candidates.length === 0 ? (
              <p className="text-[12.5px] text-muted">
                먼저 전표를 업로드하고 분류를 완료하면 등급 목표를 세울 수 있어요.
              </p>
            ) : (
              <>
                <div className="flex gap-2">
                  {candidates.candidates.map((c) => (
                    <button
                      key={c.scope_group}
                      type="button"
                      onClick={() => setScopeGroup(c.scope_group)}
                      className={`flex-1 rounded-2xl py-3 text-[13px] font-bold transition-colors ${
                        scopeGroup === c.scope_group ? "bg-brand text-white" : "bg-bg text-ink"
                      }`}
                    >
                      {SCOPE_LABEL[c.scope_group]}
                    </button>
                  ))}
                </div>

                {selectedCandidate && (
                  <div className="mt-3 rounded-2xl bg-bg p-3.5">
                    {selectedCandidate.status === "eligible" ? (
                      <p className="text-[12.5px] leading-relaxed text-ink">
                        이미 {selectedCandidate.candidate_score}등급 조건을 충족했어요.
                        {selectedCandidate.products?.[0] &&
                          ` ${selectedCandidate.products[0].product_name} 대상으로 목표를 확정할 수 있어요.`}
                      </p>
                    ) : (
                      <p className="text-[12.5px] leading-relaxed text-ink">
                        현재 {selectedCandidate.current_grade}등급 → 목표{" "}
                        {selectedCandidate.target_grade}등급
                        {selectedCandidate.target_products?.[0] &&
                          ` (${selectedCandidate.target_products[0].product_name} 우대금리 대상)`}
                      </p>
                    )}
                  </div>
                )}
                <p className="mt-2 text-[11px] leading-relaxed text-faint">
                  등급·혜택 목표는 데이터 완전성 개선을 제안할 뿐 등급 상승·자격을 보장하지
                  않아요.
                </p>
              </>
            )}
          </div>
        )}

        {error && <p className="mt-3 text-[12px] text-hitl-ink">{error}</p>}

        <button
          type="button"
          onClick={submit}
          disabled={submitting || (tab === "grade_upgrade" && !scopeGroup)}
          className="btn-cta mt-5 w-full rounded-2xl bg-brand py-3.5 text-[14.5px] font-extrabold text-white disabled:opacity-50"
        >
          {submitting ? "저장 중…" : "목표 확정하기"}
        </button>
      </div>
    </div>
  );
}
