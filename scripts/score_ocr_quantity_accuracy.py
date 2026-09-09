"""물량(수량) 추출 정확도 — 실물 합성 문서(PDF)에 인쇄된 수량 vs 감탄 OCR/파서가
읽어낸 수량 대조.

트랙 B(실물 파일럿 대조)와는 다른 층위다 — 트랙 B는 "실제 기업의 진짜 사용량"과
비교하는 것이라 파일럿 기업 섭외가 전제인 반면, 이건 "PDF에 이미 인쇄된 숫자를
감탄이 올바르게 읽어내는가"만 검증한다. 정답은 `scripts/generate_upload_docs.py`가
PDF를 그릴 때 함께 반환하는 값이라(결정론적 seed, 같은 파일명 → 같은 값) 순환논리가
없다 — "PDF에 뭐라고 쓰여 있는지"와 "감탄이 그 PDF에서 뭘 읽었는지"는 독립적인
두 값이고, 이 스크립트는 그 둘을 대조할 뿐 어느 쪽도 만들어내지 않는다.

측정 대상: db/document/document_extraction.py::extract_document()의
extraction_method가 실제로 어느 경로(text_layer/ocr/ocr_llm)로 이 문서들을
읽는지도 함께 보고한다 — CLAUDE.md §7이 "회계 담당 업로드 서류는 스캔 이미지가
아니라 reportlab 텍스트 PDF라 대부분 text_layer에서 끝난다"고 명시한 주장을
이 스크립트가 실측으로 확인한다.

degraded=True 문서(의도적 저품질 스캔, 정답 quantity=None)는 "읽으면 안 되는
케이스"라 정확도 분모에서 제외하고 별도로 "정상적으로 실패했는가"만 확인한다.

사용: python -m scripts.score_ocr_quantity_accuracy
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.document.document_extraction import extract_document
from db.document.document_text_extractor import DocumentParseError, DocumentTypeMismatchError
from scripts.generate_upload_docs import build_upload_docs

_DOC_TYPE_MAP = {
    "세금계산서_경유": "tax_invoice",
    "세금계산서_휘발유": "tax_invoice",
    "세금계산서_LPG": "tax_invoice",
    "전기고지서": "electric_bill",
    "도시가스고지서": "gas_bill",
}


def _document_type_for(rec: dict) -> str:
    doc_type = rec["doc_type"]
    if doc_type in _DOC_TYPE_MAP:
        return _DOC_TYPE_MAP[doc_type]
    if doc_type.startswith("세금계산서_"):
        return "tax_invoice"
    raise ValueError(f"알 수 없는 doc_type: {doc_type}")


def main() -> None:
    # 인메모리 세션 — LLM 최후 수단 경로(document_llm_router)만 llm_cache를
    # 조회하는데, text_layer/ocr 경로가 우세할 거라는 게 이 스크립트의 가설이라
    # 실제 DB 연결 없이도 대부분 끝난다. 필요해지면 이 세션이 조용히 빈 캐시로
    # 동작해 LLM을 매번 새로 부를 뿐, 에러는 나지 않는다.
    engine = create_engine("sqlite://")
    from db.models import Base

    Base.metadata.create_all(engine)
    session = Session(engine)

    # 결정론적 재생성 — 같은 파일명에 항상 같은 정답 quantity가 나온다
    # (generate_upload_docs.py docstring: "항상 같은 파일을 재생성한다").
    manifest = build_upload_docs()

    method_counter: Counter[str] = Counter()
    errors = []
    correct = 0
    total_scorable = 0
    degraded_handled_correctly = 0
    degraded_total = 0

    for rec in manifest:
        path = rec["file"]
        co_dir_name = f"{rec['company_id']}_{rec['company']}"
        full_path = f"data/업로드서류/{co_dir_name}/{path}"

        with open(full_path, "rb") as f:
            file_bytes = f.read()

        doc_type = _document_type_for(rec)

        if rec.get("degraded"):
            degraded_total += 1
            try:
                extract_document(session, file_bytes, doc_type)
                # 저품질 스캔인데 값을 뽑아냈다면 — 실패해야 정상인 케이스가
                # 성공해버린 것. 조용히 넘어가지 않고 기록한다.
                errors.append((path, "저품질 스캔인데 파싱 성공(원래 실패해야 함)"))
            except (DocumentParseError, DocumentTypeMismatchError):
                degraded_handled_correctly += 1
            continue

        expected_qty = rec["quantity"]
        try:
            result = extract_document(session, file_bytes, doc_type)
        except (DocumentParseError, DocumentTypeMismatchError) as e:
            errors.append((path, f"추출 자체 실패: {e}"))
            continue

        method_counter[result.get("extraction_method", "?")] += 1
        got_qty = result.get("quantity")

        total_scorable += 1
        if got_qty is not None and abs(got_qty - expected_qty) < 0.5:
            correct += 1
        else:
            errors.append((path, f"기대={expected_qty} 실제={got_qty}"))

    session.close()

    print(f"실물 문서(PDF) 물량 추출 정확도 — 정답지: {len(manifest)}건\n")

    print("=" * 60)
    print("1. 물량(수량) 추출 정확도")
    print("=" * 60)
    if total_scorable:
        print(f"  정상 문서 대상: {correct}/{total_scorable} ({correct/total_scorable:.1%})")
    if errors:
        print(f"\n  불일치/실패 {len(errors)}건:")
        for path, msg in errors:
            print(f"    [{path}] {msg}")

    print()
    print("=" * 60)
    print("2. 추출 경로 분포 (text_layer/ocr/ocr_llm)")
    print("=" * 60)
    for method, cnt in method_counter.most_common():
        print(f"  {method}: {cnt}건 ({cnt/total_scorable:.1%})" if total_scorable else f"  {method}: {cnt}건")

    print()
    print("=" * 60)
    print("3. 저품질 스캔(degraded) 문서 — 정상적으로 실패하는지")
    print("=" * 60)
    if degraded_total:
        print(f"  올바르게 실패 처리됨: {degraded_handled_correctly}/{degraded_total}")
    else:
        print("  대상 없음")


if __name__ == "__main__":
    main()
