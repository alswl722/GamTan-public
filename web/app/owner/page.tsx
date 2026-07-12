"use client";

import { useState } from "react";
import { SceneConsent } from "@/components/SceneConsent";
import { SceneTrace } from "@/components/SceneTrace";
import { SceneClassify } from "@/components/SceneClassify";
import { ScenePcaf } from "@/components/ScenePcaf";

const SCENES = [
  { key: "consent", label: "① 연동 동의", el: <SceneConsent /> },
  { key: "trace", label: "② 트레이스 뷰", el: <SceneTrace /> },
  { key: "classify", label: "③ AI 분류", el: <SceneClassify /> },
  { key: "pcaf", label: "④ PCAF 비교", el: <ScenePcaf /> },
] as const;

export default function OwnerPage() {
  const [active, setActive] = useState(0);

  return (
    <div>
      <div className="pt-4">
        <span className="inline-flex items-center gap-2 rounded-full bg-brand-soft px-2.5 py-1 text-[11.5px] font-semibold tracking-wide text-brand-ink">
          <span className="h-1.5 w-1.5 rounded-full bg-brand" />
          iM:POSSIBLE Challenger · v0.1 데모
        </span>
        <h1 className="mt-3 text-[23px] font-bold tracking-tight">사장님 화면</h1>
        <p className="mt-1 text-sm text-muted">
          구미 소재 반도체 장비 2차 벤더 ‘○○정밀’(금속가공 · 직원 12명)의 탄소
          측정 여정
        </p>
      </div>

      <div className="mt-5 flex gap-0.5 border-b border-line">
        {SCENES.map((s, i) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setActive(i)}
            className={`-mb-px border-b-2 px-[15px] py-[11px] text-sm font-semibold transition-colors ${
              active === i
                ? "border-brand text-brand-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="mt-[22px]">{SCENES[active].el}</div>
    </div>
  );
}
