"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Trash2, UploadCloud } from "lucide-react";
import {
  apiUpload,
  deleteDocument,
  getCompanyId,
  getDocumentGrid,
  getDocumentsForCell,
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

export default function OwnerUploadsPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [grid, setGrid] = useState<DocumentGridResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<{ docType: DocumentType; month: number } | null>(null);
  const [cellDocs, setCellDocs] = useState<Record<CellKey, UploadedDocument[]>>({});
  const [cellLoading, setCellLoading] = useState<CellKey | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function loadGrid() {
    setError(null);
    try {
      const cid = await getCompanyId();
      setCompanyId(cid);
      const res = await getDocumentGrid(cid);
      setGrid(res);
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
      await apiUpload(`/owner/${companyId}/documents/upload`, form);
      await loadCell(expanded.docType, expanded.month);
      await loadGrid();
    } catch (err) {
      console.error("업로드 실패:", err);
      setUploadError(err instanceof Error ? err.message : "업로드에 실패했습니다.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
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

      <h1 className="mt-4 text-[17px] font-bold leading-snug text-ink">데이터 업로드</h1>

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
                  <div className="mt-3 grid grid-cols-6 gap-1.5">
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
                          className={`rounded-xl py-2 text-[11.5px] font-semibold transition-colors ${
                            isOpen
                              ? "bg-brand text-white"
                              : filled
                                ? "bg-brand-soft text-brand-ink"
                                : "bg-bg text-faint"
                          }`}
                        >
                          {month}월
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
                        accept="image/*,.pdf"
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
    </div>
  );
}
