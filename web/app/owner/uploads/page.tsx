"use client";

import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Trash2, UploadCloud, X } from "lucide-react";
import {
  DOCUMENT_UPLOAD_TIMEOUT_MS,
  apiPost,
  apiUpload,
  deleteDocument,
  getCompanyId,
  getDocumentGrid,
  getDocumentReviewStatus,
  getDocumentsForCell,
  getReportingYears,
  getUnclassifiedCount,
  getUploadStreak,
  type DocumentGridResponse,
  type DocumentType,
  type UploadedDocument,
} from "@/lib/api";

/** 하단바 "데이터 업로드" 탭 — 문서종류(세금계산서·전기요금고지서·도시가스고지서) ×
 * 1~12월 그리드로 결손월을 한눈에 보여준다. 칸을 누르면 그 달 업로드 파일 목록을
 * 보고 삭제·추가 업로드할 수 있다(db/document_coverage.py). */

const DOC_LABEL: Record<DocumentType, string> = {
  tax_invoice: "세금계산서",
  electric_bill: "전기요금고지서",
  gas_bill: "도시가스고지서",
};

const STATUS_LABEL: Record<string, string> = {
  required: "필수",
  optional: "선택",
  not_applicable: "해당없음",
};

type CellKey = `${DocumentType}-${number}`;

// POST /classify/{company_id} 응답 요약 — api/agent/tools.py::classify_vouchers.
type ClassifySummary = { processed: number; auto: number; review_required: number };

/** 추가 업로드(초기 온보딩 위저드 제외) 완료 시 뜨는 축하 모달.
 *
 * reviewNotice가 있으면(방금 올린 문서에서 담당자 검토 대기 건이 나온 경우) 같은
 * 모달 안에 한 줄 더 보여준다 — 별도 모달을 새로 만들지 않는다. 어떤 항목이 왜
 * 검토 대상인지(판단 근거 등)는 노출하지 않는다(api/queries.py::get_classifications
 * 와 같은 원칙 — 건수만 안내). */
function UploadCompleteModal({
  message,
  reviewNotice,
  onClose,
}: {
  message: string;
  reviewNotice?: string | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-6">
      <div className="relative w-full max-w-sm rounded-3xl bg-white p-6 shadow-xl">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 text-faint transition-colors hover:text-ink"
          aria-label="닫기"
        >
          <X size={20} />
        </button>

        <h2 className="mt-1 text-[20px] font-extrabold leading-snug text-ink">
          도장 꾹!
          <br />
          업로드가 완료됐어요!
        </h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{message}</p>
        {reviewNotice && (
          <p className="mt-2 rounded-xl bg-hitl/20 px-3 py-2 text-[12.5px] leading-relaxed text-hitl-ink">
            {reviewNotice}
          </p>
        )}

        <div className="mt-1 flex justify-center">
          <Image src="/dandi_17.png" alt="" width={267} height={267} className="h-52 w-auto" />
        </div>

        <button
          type="button"
          onClick={onClose}
          className="btn-cta w-full rounded-2xl bg-brand py-3.5 text-[14.5px] font-bold text-white"
        >
          확인
        </button>
      </div>
    </div>
  );
}

/** useSearchParams()를 쓰는 화면이라 next build(정적 프리렌더)가 Suspense 경계를
 * 요구한다 — 기본 export는 그 경계만 씌우는 얇은 래퍼로 두고 실제 화면은
 * OwnerUploadsPageContent에 그대로 둔다(로직 변경 없음). */
export default function OwnerUploadsPage() {
  return (
    <Suspense fallback={null}>
      <OwnerUploadsPageContent />
    </Suspense>
  );
}

function OwnerUploadsPageContent() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [grid, setGrid] = useState<DocumentGridResponse | null>(null);
  const [years, setYears] = useState<number[] | null>(null);
  const [streakMonths, setStreakMonths] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<{ docType: DocumentType; month: number } | null>(null);
  const [cellDocs, setCellDocs] = useState<Record<CellKey, UploadedDocument[]>>({});
  const [cellLoading, setCellLoading] = useState<CellKey | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [autoUploading, setAutoUploading] = useState(false);
  const [autoUploadError, setAutoUploadError] = useState<string | null>(null);
  const autoFileInputRef = useRef<HTMLInputElement | null>(null);

  const [uploadCompleteMessage, setUploadCompleteMessage] = useState<string | null>(null);
  const [uploadReviewNotice, setUploadReviewNotice] = useState<string | null>(null);

  const [classifying, setClassifying] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  const [classifySuccessMessage, setClassifySuccessMessage] = useState<string | null>(null);
  const [unclassifiedCount, setUnclassifiedCount] = useState<number | null>(null);

  /** "분류 다시 실행" 버튼을 실제로 미분류 건이 남아있을 때만 보여주기 위한 조회 —
   * 부가 정보라 실패해도 조용히 넘어간다(버튼을 못 띄울 뿐, 화면은 계속 진행). */
  async function refreshUnclassifiedCount(cid: number) {
    try {
      const res = await getUnclassifiedCount(cid);
      setUnclassifiedCount(res.unclassified_count);
    } catch (err) {
      console.error("미분류 건수 조회 실패(부가 정보라 화면은 계속 진행):", err);
    }
  }

  /** 방금 올린 문서들(sourceDocumentIds)에서 담당자 검토 대기 건이 나왔는지 확인해
   * 모달 안내 문구를 만든다 — classifyNewVouchers()가 끝난 뒤에만 의미 있다
   * (분류가 안 돌았으면 review_required 자체가 아직 없음). 여러 장을 한 번에 올린
   * 경우 건별 대기 건수를 합산한다. 실패해도(네트워크 등) 업로드 자체는 이미
   * 성공이라 조용히 넘어간다 — 부가 정보라 화면을 막지 않음. */
  async function reviewNoticeFor(cid: number, sourceDocumentIds: number[]): Promise<string | null> {
    try {
      const counts = await Promise.all(
        sourceDocumentIds.map((id) => getDocumentReviewStatus(cid, id)),
      );
      const total = counts.reduce((sum, c) => sum + c.pending_review_count, 0);
      if (total > 0) {
        return `이 중 ${total}건은 담당자가 검토할 예정이에요.`;
      }
      return null;
    } catch (err) {
      console.error("검토 대기 여부 조회 실패(부가 정보라 화면은 계속 진행):", err);
      return null;
    }
  }

  /** 위저드 밖(이 탭)에서 올린 전표는 "AI 분류" 단계를 거칠 기회가 없어 미분류로
   * 남는다 — 그대로 두면 홈 진행바·리포트가 "미완료"로 보인다(api/queries.py::
   * get_owner_progress). 이미 분류된 전표는 건너뛰므로 매 업로드마다 불러도 안전.
   *
   * 실패 가시성 원칙 — 이 호출이 실패하면(네트워크 순단 등) 예전엔 console.error로만
   * 삼켜서 "전표는 있는데 분류만 안 된" 상태가 화면에 전혀 안 보였다(실제로 팀원이
   * 겪음 — 재업로드해도 파일이 이미 있어 매번 409라 이 함수가 재호출될 기회조차
   * 없었음). 이제 실패 여부를 반환하고, 실패하면 배너로 보여준다. 성공/실패와
   * 무관하게 아래 "분류 다시 실행" 버튼으로 언제든 재시도할 수 있다(classify_vouchers
   * 는 미분류 건만 처리하는 멱등 구조라 몇 번을 다시 불러도 안전). 반환값은
   * 처리 건수 요약(api/agent/tools.py::classify_vouchers의 summary) — 실패하면
   * null(호출부가 "성공했는지"만 판단하려면 결과값을 truthy 체크하면 된다). */
  async function classifyNewVouchers(cid: number): Promise<ClassifySummary | null> {
    try {
      const summary = await apiPost<ClassifySummary>(`/classify/${cid}`);
      setClassifyError(null);
      await refreshUnclassifiedCount(cid);
      return summary;
    } catch (err) {
      console.error("업로드 후 자동 분류 실패:", err);
      setClassifyError(
        "방금 올린 자료의 AI 분류에 실패했어요 — 아래 \"분류 다시 실행\"을 눌러 주세요.",
      );
      await refreshUnclassifiedCount(cid);
      return null;
    }
  }

  /** "이미 업로드된 파일입니다"(409)로 전량 실패하면 handleAutoUpload/handleUpload가
   * classifyNewVouchers를 아예 안 부른다(성공 0건이라 재분류 트리거 조건을 못 만족) —
   * 그런데 그 파일들이 과거에 업로드만 되고 분류는 안 된 채 남아있을 수 있다. 이
   * 버튼은 그 업로드 성공/실패 경로와 무관하게 눌러서 미분류 잔여 건을 정리할 수
   * 있게 한다(노출 여부는 unclassifiedCount로 조건부 — 아래 버튼 렌더링 참고). */
  async function handleRetryClassification() {
    if (companyId === null) return;
    setClassifying(true);
    setClassifySuccessMessage(null);
    const summary = await classifyNewVouchers(companyId);
    if (summary) {
      await loadGrid();
      // 버튼을 누르자마자 처리 대상이 0건이면(unclassifiedCount가 이미 stale하거나,
      // 다른 탭·기기에서 먼저 처리된 경우) 버튼이 조건부 렌더링 때문에 바로 사라져
      // "눌렀는데 아무 반응도 없었다"로 보인다(실측 확인, 2026-08-17) — 무슨 일이
      // 있었는지 최소 한 줄은 남긴다. 몇 초 뒤 자동으로 사라진다(토스트처럼).
      setClassifySuccessMessage(
        summary.processed > 0
          ? `${summary.processed}건 분류를 완료했어요${
              summary.review_required > 0 ? ` (이 중 ${summary.review_required}건은 담당자 검토 대기예요)` : ""
            }.`
          : "새로 분류할 자료가 없었어요.",
      );
      setTimeout(() => setClassifySuccessMessage(null), 5000);
    }
    setClassifying(false);
  }

  /** year 생략 시 백엔드가 그 기업의 최신 전표 연도를 기본값으로 쓴다 — 리포트
   * 화면(ScenePcaf.tsx)과 같은 기준(db/pcaf_quality.py::default_reporting_year).
   * 연도 선택기에서 다른 연도를 고르면 이 함수를 다시 불러 그 해로 갈아끼운다. */
  async function loadGrid(year?: number) {
    setError(null);
    try {
      const cid = await getCompanyId();
      setCompanyId(cid);
      const res = await getDocumentGrid(cid, year);
      setGrid(res);
      setExpanded(null);
      setCellDocs({});
      void refreshUnclassifiedCount(cid);
      // 연도 목록은 매번 다시 조회한다 — 캐시해서 최초 1회만 부르면, 그 해의
      // 마지막 문서를 삭제(handleDelete → loadGrid)해도 이미 사라진 연도가
      // 선택기에 그대로 남는다(실측 확인, 2026-08-17). 삭제·업로드 둘 다 이
      // 함수를 거치므로 여기서만 고치면 항상 실제 서버 상태와 맞는다.
      getReportingYears(cid)
        .then((r) => setYears(r.years))
        .catch((err) => console.error("연도 목록 조회 실패(부가 정보라 화면은 계속 진행):", err));
      if (streakMonths === null) {
        // 스트릭은 "이번 달 직전까지"만 세므로 방금 올린 업로드로는 안 바뀐다 —
        // 연도 선택기와 달리 최초 1회만 조회하면 충분하다.
        getUploadStreak(cid)
          .then((r) => setStreakMonths(r.streak_months))
          .catch((err) => console.error("업로드 스트릭 조회 실패(부가 정보라 화면은 계속 진행):", err));
      }
    } catch (err) {
      console.error("업로드 현황 조회 실패:", err);
      setError("불러오지 못했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
    }
  }

  useEffect(() => {
    void loadGrid();
  }, []);

  async function loadCell(docType: DocumentType, month: number) {
    if (companyId === null || !grid) return;
    const key: CellKey = `${docType}-${month}`;
    setCellLoading(key);
    try {
      const res = await getDocumentsForCell(companyId, docType, grid.reporting_year, month);
      setCellDocs((prev) => ({ ...prev, [key]: res.documents }));
    } catch (err) {
      console.error("파일 목록 조회 실패:", err);
    } finally {
      setCellLoading(null);
    }
  }

  function toggleCell(docType: DocumentType, month: number) {
    setUploadError(null);
    if (expanded && expanded.docType === docType && expanded.month === month) {
      setExpanded(null);
      return;
    }
    setExpanded({ docType, month });
    void loadCell(docType, month);
  }

  const searchParams = useSearchParams();
  const deepLinkAppliedRef = useRef(false);

  /** /owner/benefits의 결손월 안내 칩(?type=gas_bill&month=4)에서 넘어왔을 때, 그
   * 칸을 자동으로 펼치고 해당 문서종류 구간으로 스크롤한다 — 안내가 텍스트로 끝나지
   * 않고 실제 업로드 화면까지 데려다준다. 그리드가 로드되기 전엔 어느 문서종류가
   * 유효한지 알 수 없어 grid를 기다린다. 한 번 적용한 뒤엔 사용자가 셀을 직접
   * 여닫아도 다시 강제로 펼치지 않도록 1회만 실행한다. */
  useEffect(() => {
    if (!grid || deepLinkAppliedRef.current) return;
    const type = searchParams.get("type");
    const monthParam = searchParams.get("month");
    if (!type || !monthParam || !(type in DOC_LABEL)) return;
    const month = Number(monthParam);
    if (!Number.isInteger(month) || month < 1 || month > 12) return;

    deepLinkAppliedRef.current = true;
    const docType = type as DocumentType;
    setExpanded({ docType, month });
    void loadCell(docType, month);
    document.getElementById(`doc-row-${docType}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [grid, searchParams]);

  async function handleDelete(documentId: number) {
    if (!confirm("이 파일을 삭제할까요? 여기서 만들어진 전표·분류도 함께 지워지고 되돌릴 수 없어요.")) {
      return;
    }
    setBusyId(documentId);
    try {
      await deleteDocument(companyId!, documentId);
      if (expanded) await loadCell(expanded.docType, expanded.month);
      await loadGrid();
    } catch (err) {
      console.error("삭제 실패:", err);
      alert("삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleUpload(file: File) {
    if (companyId === null || !expanded) return;
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", expanded.docType);
      form.append("mode", "ocr");
      const res = await apiUpload<{ source_document_id: number }>(
        `/owner/${companyId}/documents/upload`,
        form,
        DOCUMENT_UPLOAD_TIMEOUT_MS,
      );
      await classifyNewVouchers(companyId);
      await loadCell(expanded.docType, expanded.month);
      await loadGrid();
      // 검토 대기 여부를 먼저 확인한 뒤에 모달을 연다 — 메시지부터 먼저 세팅해 모달이
      // 바로 뜨고 안내 줄만 몇 초 뒤에 따라붙으면, 사용자가 뜨자마자 닫아버릴 경우
      // 안내를 놓친다(실측으로 확인된 버그). 완성된 상태로 한 번에 띄운다.
      const notice = await reviewNoticeFor(companyId, [res.source_document_id]);
      setUploadReviewNotice(notice);
      setUploadCompleteMessage(`${DOC_LABEL[expanded.docType]} ${expanded.month}월 자료가 등록됐어요.`);
    } catch (err) {
      console.error("업로드 실패:", err);
      setUploadError(err instanceof Error ? err.message : "업로드에 실패했습니다.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  /** 여러 장을 한 번에 골라도 되도록 한 장씩 순차 업로드한다(문서마다 document_type을
   * 스스로 판별해야 해서 uploadOcr류의 병렬 실행과 달리 완료 모달·그리드 새로고침을
   * 마지막에 한 번만 띄우는 편이 자연스럽다). 일부만 실패해도 나머지는 계속 올리고,
   * 성공한 장이 하나라도 있으면 그 결과로 모달을 띄운다. */
  async function handleAutoUpload(files: File[]) {
    if (companyId === null || files.length === 0) return;
    setAutoUploading(true);
    setAutoUploadError(null);
    const successes: { document_type: DocumentType; month: number; source_document_id: number }[] = [];
    const errors: string[] = [];
    for (const file of files) {
      try {
        const form = new FormData();
        form.append("file", file);
        form.append("mode", "ocr");
        // document_type을 안 보낸다 — OCR/비전이 스스로 문서종류를 판별한다("그냥 업로드").
        const res = await apiUpload<{ document_type: DocumentType; month: number; source_document_id: number }>(
          `/owner/${companyId}/documents/upload`,
          form,
          DOCUMENT_UPLOAD_TIMEOUT_MS,
        );
        successes.push(res);
      } catch (err) {
        console.error("자동 업로드 실패:", err);
        errors.push(`${file.name}: ${err instanceof Error ? err.message : "업로드에 실패했습니다."}`);
      }
    }
    if (successes.length > 0) {
      await classifyNewVouchers(companyId);
      await loadGrid();
      // 검토 대기 여부를 먼저 확인한 뒤에 모달을 연다 — 메시지부터 먼저 세팅해 모달이
      // 바로 뜨고 안내 줄만 몇 초 뒤에 따라붙으면(여러 장일수록 review-status 병렬
      // 호출이 늘어 더 오래 걸림), 사용자가 뜨자마자 닫아버릴 경우 안내를 놓친다
      // (실측으로 확인된 버그 — "도장 꾹" 모달은 떴는데 검토 대기 줄만 없었음).
      // 완성된 상태로 한 번에 띄운다.
      const notice = await reviewNoticeFor(companyId, successes.map((s) => s.source_document_id));
      setUploadReviewNotice(notice);
      setUploadCompleteMessage(
        successes.length === 1
          ? `${DOC_LABEL[successes[0].document_type]} ${successes[0].month}월로 인식해 등록했어요.`
          : `${successes.length}건을 인식해 등록했어요.`,
      );
    }
    setAutoUploadError(errors.length > 0 ? errors.join(" / ") : null);
    setAutoUploading(false);
    if (autoFileInputRef.current) autoFileInputRef.current.value = "";
  }

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

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <h1 className="text-[17px] font-bold leading-snug text-ink">데이터 업로드</h1>
        {streakMonths !== null && streakMonths > 0 && (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            {streakMonths}개월 연속 업로드 중
          </span>
        )}
        {/* 업로드는 됐는데 분류만 안 된 채 남는 경우를 위한 탈출구 — 업로드 실패
         * (중복 등)와 무관하게 눌러서 밀린 분류를 정리할 수 있다. classify_vouchers가
         * 미분류 건만 처리하는 멱등 구조라 반복 호출해도 안전. 실제로 미분류 건이
         * 남아있을 때만 노출한다(unclassifiedCount > 0) — 그전엔 항상 떠 있어서
         * 평소 99%는 눌러도 할 일이 없는 버튼이었다(2026-08-17 조건부로 전환). */}
        {((unclassifiedCount ?? 0) > 0 || classifying) && (
          <button
            type="button"
            onClick={() => void handleRetryClassification()}
            disabled={classifying || companyId === null}
            className="ml-auto text-[11.5px] font-semibold text-muted underline decoration-dotted underline-offset-2 hover:text-ink disabled:opacity-50"
          >
            {classifying ? "분류 실행 중…" : "분류 다시 실행"}
          </button>
        )}
      </div>

      {years !== null && years.length > 1 && grid && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {years.map((y) => (
            <button
              key={y}
              type="button"
              onClick={() => y !== grid.reporting_year && void loadGrid(y)}
              className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold transition-colors ${
                y === grid.reporting_year
                  ? "bg-brand text-white"
                  : "bg-line text-muted hover:bg-brand-soft hover:text-brand-ink"
              }`}
            >
              {y}년
            </button>
          ))}
        </div>
      )}

      {classifySuccessMessage && (
        <div className="mt-4 rounded-2xl bg-brand-soft px-4 py-3 text-[12.5px] leading-relaxed text-brand-ink">
          {classifySuccessMessage}
        </div>
      )}

      {classifyError && (
        <div className="mt-4 rounded-2xl bg-hitl/20 px-4 py-3 text-[12.5px] leading-relaxed text-hitl-ink">
          <p>{classifyError}</p>
          <button
            type="button"
            onClick={() => void handleRetryClassification()}
            disabled={classifying}
            className="btn-cta mt-2 rounded-xl bg-brand px-4 py-2 text-[12.5px] font-bold text-white disabled:opacity-60"
          >
            {classifying ? "분류 실행 중…" : "분류 다시 실행"}
          </button>
        </div>
      )}

      <div className="mt-4 rounded-3xl bg-surface p-5 shadow-card">
        <div className="text-[13.5px] font-bold text-ink">어떤 문서인지 모르겠다면</div>
        <p className="mt-1 text-[12px] leading-relaxed text-muted">
          사진이나 PDF를 올리면 AI가 문서종류와 월을 알아서 인식해요.
        </p>
        <label className="btn-cta mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-2xl bg-brand py-3 text-[13px] font-bold text-white disabled:opacity-60">
          <UploadCloud size={16} />
          {autoUploading ? "인식하는 중…" : "여러 장 한 번에 그냥 업로드하기"}
          <input
            ref={autoFileInputRef}
            type="file"
            accept="image/*,.pdf,.html,.htm,.mhtml"
            multiple
            className="hidden"
            disabled={autoUploading}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length > 0) void handleAutoUpload(files);
            }}
          />
        </label>
        {autoUploadError && (
          <p className="mt-2 text-[11.5px] text-red-600">{autoUploadError}</p>
        )}
      </div>

      <div className="mt-4 flex-1 space-y-4">
        {error ? (
          <>
            <div className="rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
              {error}
            </div>
            <button
              type="button"
              onClick={() => void loadGrid()}
              className="btn-cta w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
            >
              다시 시도
            </button>
          </>
        ) : !grid ? (
          <p className="text-[13px] text-faint">불러오는 중…</p>
        ) : (
          grid.document_types.map((row) => {
            const notApplicable = row.status === "not_applicable";
            return (
              <div
                key={row.document_type}
                id={`doc-row-${row.document_type}`}
                className={`rounded-3xl bg-surface p-5 shadow-card ${notApplicable ? "opacity-50" : ""}`}
              >
                <div className="flex items-center gap-1.5">
                  <div className="text-[13.5px] font-bold text-ink">{DOC_LABEL[row.document_type]}</div>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${
                      row.status === "required"
                        ? "bg-brand-soft text-brand-ink"
                        : "bg-line text-muted"
                    }`}
                  >
                    {STATUS_LABEL[row.status]}
                  </span>
                </div>

                {!notApplicable && (
                  <div className="mt-3 grid grid-cols-6 gap-x-1.5 gap-y-2.5">
                    {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => {
                      const count = row.months[String(month)] ?? 0;
                      const filled = count > 0;
                      const isOpen =
                        expanded?.docType === row.document_type && expanded.month === month;
                      return (
                        <button
                          key={month}
                          type="button"
                          onClick={() => toggleCell(row.document_type, month)}
                          className="flex flex-col items-center gap-1"
                        >
                          <span
                            className={`flex aspect-square w-full items-center justify-center rounded-full border-2 transition-colors ${
                              isOpen
                                ? "border-brand bg-brand-soft"
                                : filled
                                  ? "border-brand-soft bg-white"
                                  : "border-dashed border-line bg-bg"
                            }`}
                          >
                            {filled ? (
                              <Image
                                src="/carbon_stamp.png"
                                alt="업로드 완료 도장"
                                width={56}
                                height={56}
                                className="h-12 w-12 -rotate-6 object-contain"
                              />
                            ) : (
                              <span className="h-1.5 w-1.5 rounded-full bg-line" />
                            )}
                          </span>
                          <span
                            className={`text-[10.5px] font-semibold ${
                              isOpen ? "text-brand-ink" : filled ? "text-ink" : "text-faint"
                            }`}
                          >
                            {month}월
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {expanded && expanded.docType === row.document_type && (
                  <div className="mt-3 rounded-2xl bg-bg p-4">
                    <div className="text-[12.5px] font-semibold text-ink">
                      {expanded.month}월 업로드 파일
                    </div>

                    {cellLoading === `${expanded.docType}-${expanded.month}` ? (
                      <p className="mt-2 text-[12px] text-faint">불러오는 중…</p>
                    ) : (
                      <div className="mt-2 space-y-1.5">
                        {(cellDocs[`${expanded.docType}-${expanded.month}`] ?? []).length === 0 ? (
                          <p className="text-[12px] text-faint">아직 업로드된 파일이 없어요.</p>
                        ) : (
                          cellDocs[`${expanded.docType}-${expanded.month}`].map((doc) => (
                            <div
                              key={doc.id}
                              className="flex items-center justify-between gap-2 rounded-xl bg-surface px-3 py-2.5"
                            >
                              <span className="truncate text-[12px] text-ink">
                                {doc.original_filename ?? `문서 #${doc.id}`}
                              </span>
                              <button
                                type="button"
                                onClick={() => void handleDelete(doc.id)}
                                disabled={busyId === doc.id}
                                className="shrink-0 rounded-lg p-1.5 text-red-500 transition-colors hover:bg-red-50 disabled:opacity-50"
                                aria-label="삭제"
                              >
                                <Trash2 size={15} />
                              </button>
                            </div>
                          ))
                        )}
                      </div>
                    )}

                    <label className="btn-cta mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-2xl bg-brand py-3 text-[13px] font-bold text-white disabled:opacity-60">
                      <UploadCloud size={16} />
                      {uploading ? "업로드하는 중…" : "추가 업로드"}
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*,.pdf,.html,.htm,.mhtml"
                        className="hidden"
                        disabled={uploading}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) void handleUpload(file);
                        }}
                      />
                    </label>
                    {uploadError && (
                      <p className="mt-2 text-[11.5px] text-red-600">{uploadError}</p>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {uploadCompleteMessage && (
        <UploadCompleteModal
          message={uploadCompleteMessage}
          reviewNotice={uploadReviewNotice}
          onClose={() => {
            setUploadCompleteMessage(null);
            setUploadReviewNotice(null);
          }}
        />
      )}
    </div>
  );
}
