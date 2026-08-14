/**
 * Classification.evidence 는 "AI 원본 판단 근거 | 담당자 조치1 | 담당자 조치2 …" 형태로
 * 누적된다(api/routers/admin.py::_append_evidence, 원본을 지우지 않는 감사 추적).
 * 화면에서는 원본과 담당자 조치를 구역을 나눠 보여주기 위해 마지막 " | " 뒤를
 * "가장 최근 담당자 조치"로, 그 앞 전체를 "원본 판단 근거"로 분리한다.
 */
export function splitEvidence(
  evidence: string | null | undefined,
): { original: string | null; action: string | null } {
  if (!evidence) return { original: null, action: null };
  const idx = evidence.lastIndexOf(" | ");
  if (idx === -1) return { original: null, action: evidence };
  return { original: evidence.slice(0, idx), action: evidence.slice(idx + 3) };
}
