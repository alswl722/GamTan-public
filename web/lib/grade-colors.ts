/**
 * PCAF 등급 색상 — 브랜드 민트 단일 색조의 순차 램프 (1등급=진함/실측 상위, 5등급=흐림/추정 하위).
 * 등급 분포(GradeDonut)·우대금리 후보(RateCandidates) 등 등급을 표시하는 모든 곳에서 공유한다.
 */
export const GRADE_COLORS: Record<string, string> = {
  "1": "#006b5b",
  "2": "#00967f",
  "3": "#00c7a9",
  "4": "#66ddc8",
  "5": "#a8ead8",
};

export const GRADE_LABELS: Record<string, string> = {
  "1": "1등급",
  "2": "2등급",
  "3": "3등급",
  "4": "4등급",
  "5": "5등급",
};

export function gradeColor(grade: number | string): string {
  return GRADE_COLORS[String(grade)] ?? "#e8eaed";
}
