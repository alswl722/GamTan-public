"use client";

import { useEffect, useState } from "react";
import { Leaf } from "lucide-react";
import { getReductionTodo, type ReductionTodoItem } from "@/lib/api";

/** 홈 화면 "이번 달엔 이렇게 해보세요" 카드 — 감축 실천 ToDo(docs/reduction-todo-plan.md).
 *
 * RateProductCard·KTaxonomyCard·GovSupportCard와 같은 자기완결형 패턴 —
 * { companyId }만 받고 스스로 fetch한다.
 *
 * 2026-08-25 재설계 — 1차 버전은 숫자 카드("10월 수준으로 돌아가면 0.02tCO2e
 * 절감")를 그대로 메인으로 냈는데, 실사용 피드백이 "뭔가 이번주 할일이라는
 * 느낌이 아니잖아", "단순하게 뭐 하세요가 될거같아서"였다. 그래서 **동사형
 * 할 일 문장(todos)이 카드의 전부**다 — goals(3층 기준부하 숫자)는 배경
 * 정보로 잠깐 뒀었으나, "이렇게 하면 도움이 돼요 · 예상치예요 · 전기 10월
 * 수준으로 돌아가면 0.02tCO2e" 같은 문구가 "이 내용은 필요 없을거같아"라는
 * 피드백으로 완전히 제거됐다(2026-08-25) — goals는 이제 이 카드가 아니라
 * 목표 설정 시트(GoalSheet.tsx)에서 다른 형태로 쓰인다.
 *
 * 2026-08-26 — reorder_status === "pending"이면 실제 todos 텍스트를 아예
 * 감추고 스켈레톤(회색 바 3개)을 보여준다. LLM 순서 재배치가 BackgroundTasks로
 * 넘어가면서(Gemini 타임아웃이 응답 전체를 막던 문제 대응), 코드가 조립한
 * 기본 순서가 그 자리에 그대로 노출되고 있었다 — "AI 분석 중" 배지만 붙이고
 * 문장은 이미 완성된 결과처럼 보이게 뒀더니 "분석 중이면 [항목들]이 뜨면
 * 안되지"라는 피드백을 받았다: 배지 하나로는 부족하고, 아직 확정 안 된
 * 결과라면 그 문장 자체가 안 보여야 한다는 것. pending인 동안 2초마다
 * 재조회해 백그라운드 작업이 끝나면(ready) 자동으로 실제 문장으로 교체된다.
 * 재배치 대상이 아닌 경로(설비 신호 없음)엔 reorder_status 필드 자체가
 * 없어(api.ts 주석 참고) 스켈레톤도 안 뜬다 — 분석할 게 없으니 "분석 중"도
 * 아니다.
 *
 * 같은 날, 헤더 문구를 "이번주 할 일"에서 "이번 달엔 이렇게 해보세요"로
 * 바꿨다 — GoalSheet.tsx의 기존 섹션 제목과 톤을 통일하고, §14의 "이번주인데
 * 매주 안 바뀐다"는 어긋남도 함께 완화한다(todos 자체가 매주 갱신되는 로직은
 * 아니라서 "이번 달" 쪽이 실제 동작과 더 맞다). 나뭇잎·반짝임 아이콘은 헤더·
 * 배지에서 뺐다(사용자 지시 — "옆에 나뭇잎 모양은 지울게", "AI 분석 중에
 * 아이콘 삭제해줘") — 대신 각 todo 항목의 체크 표시(CircleCheckBig, 회색)를
 * 나뭇잎(Leaf)으로 바꿨다. 색상은 연두(lime) 원배경 → 연두 아이콘(배경 없음)
 * → 최종 브랜드 톤(text-brand-ink)으로 두 번 더 조정했다("체크 아이콘을
 * 나뭇잎 초록으로 바꿔줘"·"연두 원배경" → "배경은 지워주고 나뭇잎 색을
 * 연두로 바꿔줘" → "연두색 말고 브랜드 색으로 해줘") — 헤더에서 뺀 나뭇잎이
 * 자리를 옮겨 항목 하나하나의 완료 표시로 다시 쓰이되, 원배경 없이 아이콘만
 * 브랜드 민트색으로 남는다.
 *
 * 카드 셸에는 card-glow(globals.css)를 적용했다 — 5초 주기로 그림자가
 * 브랜드 민트 톤으로 은은하게 커졌다 작아지는 "숨쉬는" 효과(사용자 지시 —
 * "해당 컴포넌트 배경 이펙트를 움직이는 그림자 넣어봐"). shadow-card 정적
 * 클래스 대신 card-glow 하나로 대체한다 — keyframe의 0%/100%가 이미
 * var(--shadow-card)라 정지 상태와 시각적으로 이어진다.
 */
const POLL_INTERVAL_MS = 2000;

function TodoSkeleton() {
  return (
    <ul className="mt-3.5 space-y-2.5" aria-label="AI 분석 중">
      {[0, 1, 2].map((i) => (
        <li key={i} className="flex items-start gap-2">
          <div className="mt-0.5 h-[15px] w-[15px] shrink-0 animate-pulse rounded-full bg-bg" />
          <div className="min-w-0 flex-1 space-y-1.5 py-0.5">
            <div className="h-3 w-[85%] animate-pulse rounded-full bg-bg" />
            {i === 1 && <div className="h-3 w-[55%] animate-pulse rounded-full bg-bg" />}
          </div>
        </li>
      ))}
    </ul>
  );
}

// 2초 간격으로 최대 이만큼만 재조회한다(총 30초) — GEMINI_API_KEY 부재 등으로
// 캐시가 영원히 안 생기는 극단적 케이스에서 폴링이 무한히 계속되지 않도록.
// 그 이후엔 스켈레톤을 접고 마지막으로 받은 순서(원래 순서)를 그냥 보여준다
// — "언제까지고 로딩만 도는 카드"보다는 나은 결과.
const MAX_POLL_ATTEMPTS = 15;

export function ReductionTodoCard({ companyId }: { companyId: number | null }) {
  const [todos, setTodos] = useState<ReductionTodoItem[] | null>(null);
  const [reorderPending, setReorderPending] = useState(false);

  useEffect(() => {
    if (companyId === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;

    function fetchOnce() {
      getReductionTodo(companyId as number)
        .then((res) => {
          if (cancelled) return;
          setTodos(res.todos);
          attempts += 1;
          const stillPending = res.reorder_status === "pending" && attempts < MAX_POLL_ATTEMPTS;
          setReorderPending(stillPending);
          if (stillPending) timer = setTimeout(fetchOnce, POLL_INTERVAL_MS);
        })
        .catch((err) => console.error("감축 실천 ToDo 조회 실패:", err));
    }
    fetchOnce();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [companyId]);

  if (companyId === null || todos === null) return null;

  return (
    <div className="card-glow mt-5 rounded-3xl bg-surface p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[15px] font-extrabold text-ink">이번 달엔 이렇게 해보세요</span>
        {reorderPending && (
          <span className="rounded-full bg-bg px-2.5 py-1 text-[10.5px] font-bold text-faint">
            AI 분석 중
          </span>
        )}
      </div>

      {reorderPending ? (
        <TodoSkeleton />
      ) : (
        <ul className="mt-3.5 space-y-2.5">
          {todos.map((todo) => (
            <li key={todo.id} className="flex items-start gap-2">
              <Leaf size={15} strokeWidth={2} className="mt-0.5 shrink-0 text-brand-ink" />
              <div className="min-w-0">
                <p className="text-[13px] font-bold leading-snug text-ink">{todo.label}</p>
                {todo.note && <p className="mt-0.5 text-[11px] leading-relaxed text-faint">{todo.note}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
