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
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">사장님 화면</h1>
        <p className="mt-1 text-sm text-muted">
          구미 소재 반도체 장비 2차 벤더 &lsquo;○○정밀&rsquo;의 탄소 측정 여정
          (데모 4장면)
        </p>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-line">
        {SCENES.map((s, i) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setActive(i)}
            className={`-mb-px rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              active === i
                ? "border-brand text-brand"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="mt-6">{SCENES[active].el}</div>
    </div>
  );
}
