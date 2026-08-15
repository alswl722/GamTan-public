"""이미지·스캔 PDF → 텍스트/좌표 재구성 (PaddleOCR, 100% 로컬).

`db/document_vision_extractor.py`(Gemini 비전)를 대체한다. 이 모듈의 역할은 "픽셀→글자"
까지만이다 — 문서종류·날짜·금액이 뭔지 판단(구조화)은 `db/document_text_extractor.py`의
결정론적 정규식·좌표 매칭이 담당한다(CLAUDE.md 원칙1 "LLM 산수 금지"와 같은 결 — 이
파이프라인엔 애초에 LLM이 없다).

`db/document_text_extractor.py::extract_pdf_text()`(pdfplumber, 텍스트 레이어)가 텍스트를
못 찾았을 때만(사진·스캔본, 또는 텍스트 레이어는 있어도 알려진 서식이 아닌 실제 문서)
`db/document_extraction.py`가 이 모듈을 호출한다.

재구성은 두 형태를 함께 반환한다(OcrResult):
  - text: OCR 박스를 y좌표 행(row) 단위로 묶어 각 행 안은 공백으로 이어붙인 한 뭉치
    텍스트 — 전기·가스고지서처럼 "라벨: 값"이 선형으로 인쇄된 문서는 이걸 그대로
    `db/document_text_extractor.py`의 기존 정규식 파서에 흘려보낸다.
  - rows(OcrRow 리스트): 행 안의 셀을 문자열로 뭉개지 않고 좌표를 유지한 채 보존 —
    세금계산서 품목행처럼 표 형태 문서는 컬럼이 사진마다 살짝씩 어긋나 한 줄
    정규식이 실패하기 쉬워, `db/document_text_extractor.py::parse_tax_invoice_table_rows()`
    가 헤더 행 좌표를 기준으로 컬럼을 매칭한다(실측 스파이크로 이 어긋남을 확인함 —
    같은 행의 셀인데도 라벨/값이 별도 박스로 갈리거나 붙는 경우가 실제로 나왔다).

PaddleOCR 모델 로딩이 무겁다(수백MB, 초 단위) — 프로세스당 한 번만 초기화하는 lazy
singleton으로 유지한다.
"""
import io

import numpy as np
from PIL import Image

from db.document_text_extractor import DocumentParseError, OcrRow

_ocr_engine = None  # lazy singleton — PaddleOCR(lang="korean")
_heif_registered = False

# 같은 행으로 묶을 y중심 거리 허용치 — 박스 높이 대비 비율. 실측 스파이크에서 같은
# 행 셀들도 y좌표가 완벽히 안 맞음을 확인했다(단순 반올림이 아니라 겹침 기준 필요).
_ROW_Y_OVERLAP_RATIO = 0.5


class OcrEngineError(DocumentParseError):
    """PaddleOCR 엔진 자체가 실패했을 때(모델 로드 실패·인식 호출 예외 등) — "읽긴
    읽었지만 형식이 다르거나 저화질이라 못 알아봄"(DocumentParseError)과 구분해
    db/quality_issues.py에 다른 사유로 기록하기 위한 서브클래스."""


class OcrResult:
    __slots__ = ("text", "rows", "confidence")

    def __init__(self, text: str, rows: list[OcrRow], confidence: float):
        self.text = text
        self.rows = rows
        self.confidence = confidence


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
            # use_textline_orientation=False — 실측 확인: 이 줄 단위 180도 회전 판별
            # 모듈이 똑바로 찍힌 멀쩡한 문서도 뒤집힌 걸로 잘못 판단해 글자를 깨뜨리는
            # 경우가 나왔다(전기고지서·세금계산서 사진은 정상 인식되던 것과 달리, 같은
            # 조건의 관리비 고지서 사진에서 재현됨 — 원인이 이 모듈로 좁혀짐). 실사용
            # 케이스(사장님이 문서를 똑바로 찍어 올림)에서는 이득보다 오탐 위험이 커서
            # 끈다. 문서 방향 보정(use_doc_orientation_classify)·펴기(use_doc_unwarping)
            # 는 실측에서 문제를 일으키지 않아 유지한다(비스듬히 찍은 실사진 대응용).
            _ocr_engine = PaddleOCR(lang="korean", use_textline_orientation=False)
        except Exception as e:  # noqa: BLE001 — 모델 로드·의존성 문제 등
            raise OcrEngineError(f"OCR 엔진을 불러오지 못했어요 — {e}") from e
    return _ocr_engine


def _ensure_heif_registered() -> None:
    global _heif_registered
    if not _heif_registered:
        import pillow_heif
        pillow_heif.register_heif_opener()
        _heif_registered = True


def _is_heic(file_bytes: bytes) -> bool:
    # HEIC/HEIF는 ISO BMFF 컨테이너 — offset 4~8이 "ftyp", 8~12가 브랜드.
    if len(file_bytes) < 12 or file_bytes[4:8] != b"ftyp":
        return False
    return file_bytes[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heif")


def _is_webp(file_bytes: bytes) -> bool:
    return file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP"


def rasterize_to_images(file_bytes: bytes) -> list[Image.Image]:
    """이미지·스캔 PDF → RGB PIL 이미지 목록(PDF는 페이지별로 여러 장)."""
    if file_bytes[:4] == b"%PDF":
        try:
            import fitz  # PyMuPDF — poppler 등 외부 바이너리 없이 순수 wheel로 래스터화
        except ImportError as e:
            raise OcrEngineError("PDF 래스터화 라이브러리를 불러오지 못했어요") from e
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            images = [
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                for pix in (page.get_pixmap(dpi=250) for page in doc)
            ]
            doc.close()
        except Exception as e:  # noqa: BLE001
            raise DocumentParseError(f"PDF를 이미지로 변환하지 못했어요 — {e}") from e
        if not images:
            raise DocumentParseError("빈 PDF예요 — 다시 스캔해서 올려 주세요")
        return images

    if _is_heic(file_bytes):
        _ensure_heif_registered()
        try:
            return [Image.open(io.BytesIO(file_bytes)).convert("RGB")]
        except Exception as e:  # noqa: BLE001
            raise DocumentParseError(f"사진을 열지 못했어요 — {e}") from e

    if file_bytes[:3] == b"\xff\xd8\xff" or file_bytes[:8] == b"\x89PNG\r\n\x1a\n" or _is_webp(file_bytes):
        try:
            return [Image.open(io.BytesIO(file_bytes)).convert("RGB")]
        except Exception as e:  # noqa: BLE001
            raise DocumentParseError(f"사진을 열지 못했어요 — {e}") from e

    raise DocumentParseError(
        "문서에서 텍스트를 읽어내지 못했어요 — 사진(JPG/PNG/HEIC/WEBP) 또는 PDF 형식의 자료를 올려 주세요"
    )


def _cluster_rows(boxes: list[tuple[float, float, float, float, str]]) -> list[OcrRow]:
    """(x0, x1, y0, y1, text) 박스 목록 → y좌표 겹침 기준 행 클러스터링, 각 행 내부는
    x좌표 오름차순."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: (b[2] + b[3]) / 2)  # y중심 오름차순
    rows: list[list[tuple[float, float, float, float, str]]] = []
    for box in boxes:
        y_center = (box[2] + box[3]) / 2
        height = max(box[3] - box[2], 1.0)
        placed = False
        for row in rows:
            row_y_center = sum((b[2] + b[3]) / 2 for b in row) / len(row)
            row_height = sum(b[3] - b[2] for b in row) / len(row)
            if abs(y_center - row_y_center) <= _ROW_Y_OVERLAP_RATIO * max(height, row_height):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])
    return [
        [(b[0], b[1], b[4]) for b in sorted(row, key=lambda b: b[0])]
        for row in rows
    ]


def _run_ocr_on_image(image: Image.Image) -> tuple[list[OcrRow], list[float]]:
    engine = _get_ocr_engine()
    try:
        predictions = engine.predict(np.array(image))
    except Exception as e:  # noqa: BLE001
        raise OcrEngineError(f"OCR 인식에 실패했어요 — {e}") from e

    boxes: list[tuple[float, float, float, float, str]] = []
    scores: list[float] = []
    for pred in predictions:
        texts = pred.get("rec_texts") or []
        rec_scores = pred.get("rec_scores") or []
        polys = pred.get("rec_polys") or []
        for text, score, poly in zip(texts, rec_scores, polys):
            if not text.strip():
                continue
            xs = [pt[0] for pt in poly]
            ys = [pt[1] for pt in poly]
            boxes.append((float(min(xs)), float(max(xs)), float(min(ys)), float(max(ys)), text))
            scores.append(float(score))
    return _cluster_rows(boxes), scores


def ocr_extract(file_bytes: bytes) -> OcrResult:
    """이미지·스캔 PDF에서 텍스트/좌표를 재구성한다. 아무 글자도 못 읽으면 값을
    지어내지 않고 DocumentParseError(실패 가시성 원칙, CLAUDE.md §6). 이 함수 자체는
    db/document_text_extractor.py의 정규식 파서를 부르지 않는다 — 구조화 책임 분리
    (파일 상단 docstring 참고), 호출부(db/document_extraction.py)가 이어서 부른다.
    """
    images = rasterize_to_images(file_bytes)

    all_rows: list[OcrRow] = []
    all_scores: list[float] = []
    for image in images:
        rows, scores = _run_ocr_on_image(image)
        all_rows.extend(rows)
        all_scores.extend(scores)

    if not all_rows:
        raise DocumentParseError("문서에서 글자를 인식하지 못했어요 — 더 선명하게 다시 올려 주세요")

    linear_text = "\n".join(" ".join(cell_text for _, _, cell_text in row) for row in all_rows)
    confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
    return OcrResult(text=linear_text, rows=all_rows, confidence=confidence)
