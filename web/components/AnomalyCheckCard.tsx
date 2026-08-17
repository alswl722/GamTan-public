"use client";

import { useEffect, useState } from "react";
import {
  answerAnomalyCheck,
  getAnomalyChecks,
  getCompanyId,
  type AnomalyCheckAnswer,
  type AnomalyCheckItem,
} from "@/lib/api";

/** 이상치 되묻기 — 에이전트가 코드로 판별한 이상치(평월 대비 N배 급증)를
 * 사장님에게 "맞나요?" 확인받는 카드(docs/tasks.md). 숫자는 절대 입력받지
 * 않는다 — 예/아니오/모르겠어요 + 짧은 사유만. "네"는 참고정보로만 남지만,
 * "아니요"·"모르겠어요"는 은행 담당자에게 확인 요청이 간다는 걸 문구로
 * 명시해 기대치를 흐리지 않는다. */

const ANSWER_LABEL: Record<AnomalyCheckAnswer, string> = {
  normal: "네, 정상이에요",
  disputed: "아니요, 확인해볼게요",
  unknown: "모르겠어요",
};

function Row({
  item,
  companyId,
  onAnswered,
}: {
  item: AnomalyCheckItem;
  companyId: number;
  onAnswered: (voucherId: number) => void;
}) {
  const [picked, setPicked] = useState<AnomalyCheckAnswer | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(answer: AnomalyCheckAnswer) {
    setPicked(answer);
    if (answer === "normal") {
      await send(answer);
    }
  }

  async function send(answer: AnomalyCheckAnswer) {
    setSubmitting(true);
    setError(null);
    try {
      await answerAnomalyCheck(companyId, item.voucher_id, {
        answer,
        reason: reason.trim() || undefined,
      });
      onAnswered(item.voucher_id);
    } catch (err) {
      console.error("이상치 확인 답변 실패:", err);
      setError("저장에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      setPicked(null);
    } finally {
      setSubmitting(false);
    }
  }

  const needsReason = picked === "disputed" || picked === "unknown";

  return (
    <div className="rounded-2xl border border-line bg-surface p-3.5">
      <p className="text-[13px] font-semibold leading-relaxed text-ink">
        {item.month}월 {item.fuel} 사용량이 평소보다 {item.ratio}배 많아요, 맞나요?
      </p>

      {!needsReason ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {(Object.keys(ANSWER_LABEL) as AnomalyCheckAnswer[]).map((answer) => (
            <button
              key={answer}
              type="button"
              disabled={submitting}
              onClick={() => submit(answer)}
              className="btn-cta rounded-lg border border-line bg-bg px-3 py-2 text-[12px] font-semibold text-ink disabled:opacity-60"
            >
              {ANSWER_LABEL[answer]}
            </button>
          ))}
        </div>
      ) : (
        <div className="mt-2.5">
          <p className="text-[11.5px] leading-relaxed text-muted">
            은행 담당자에게 확인 요청을 남길게요. 짧게 이유를 알려주시면 검토에 도움이 돼요(선택).
          </p>
          <div className="mt-2 flex items-center gap-1.5">
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="예: 잘 모르겠어요"
              className="flex-1 rounded-lg border border-line bg-bg px-2.5 py-2 text-[12.5px] text-ink outline-none focus:border-brand"
            />
            <button
              type="button"
              disabled={submitting}
              onClick={() => send(picked)}
              className="btn-cta shrink-0 rounded-lg bg-hitl-ink px-3.5 py-2 text-[12.5px] font-bold text-white disabled:opacity-60"
            >
              {submitting ? "저장 중…" : "전달"}
            </button>
          </div>
        </div>
      )}
      {error && <p className="mt-1.5 text-[11px] text-hitl-ink">{error}</p>}
    </div>
  );
}

export function AnomalyCheckCard() {
  const [items, setItems] = useState<AnomalyCheckItem[] | null>(null);
  const [companyId, setCompanyId] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    getCompanyId()
      .then((cid) => {
        if (!alive) return;
        setCompanyId(cid);
        return getAnomalyChecks(cid);
      })
      .then((list) => {
        if (alive && list) setItems(list);
      })
      .catch((err) => console.error("이상치 확인 대상 조회 실패:", err));
    return () => {
      alive = false;
    };
  }, []);

  function handleAnswered(voucherId: number) {
    setItems((prev) => prev?.filter((it) => it.voucher_id !== voucherId) ?? prev);
  }

  if (!items || items.length === 0 || companyId === null) return null;

  return (
    <div className="mt-3 rounded-2xl border border-line bg-bg p-3.5">
      <p className="text-[12.5px] font-bold text-ink">평소보다 사용량이 많은 달이 있어요</p>
      <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted">
        맞는지 확인해 주시면 리포트 정확도에 도움이 돼요.
      </p>
      <div className="mt-2.5 flex flex-col gap-2">
        {items.map((item) => (
          <Row key={item.voucher_id} item={item} companyId={companyId} onAnswered={handleAnswered} />
        ))}
      </div>
    </div>
  );
}
