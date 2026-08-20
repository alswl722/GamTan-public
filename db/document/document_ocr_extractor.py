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
import math
import statistics
import threading

import numpy as np
from PIL import Image

from db.document.document_text_extractor import DocumentParseError, OcrRow

_ocr_engine = None  # lazy singleton — 메인 1차 인식(전체 페이지, mobile 감지+인식)
_retry_ocr_engine = None  # lazy singleton — ocr_retry_region() 전용(server 감지+mobile 인식)
_skew_probe_engine = None  # lazy singleton — probe_skew_deg() 전용(unwarping 꺼짐)
_ocr_engine_lock = threading.Lock()  # 세 엔진 모두 이 락으로 직렬화(동시 predict() crash 이력)
_heif_registered = False

# 같은 행으로 묶을 y중심 거리 허용치 — 박스 높이 대비 비율. 실측 스파이크에서 같은
# 행 셀들도 y좌표가 완벽히 안 맞음을 확인했다(단순 반올림이 아니라 겹침 기준 필요).
_ROW_Y_OVERLAP_RATIO = 0.5

# 각도 추정에 쓸 상자의 최소 상단 변 길이(px) — 숫자 한 글자처럼 짧은 상자는 변
# 방향이 노이즈에 취약해 각도가 안 믿을 만하다. 단어·문구 단위 상자만 쓴다.
_MIN_ANGLE_BOX_EDGE_LEN = 20.0


def _box_angle_deg(poly) -> float | None:
    """poly(감지 상자의 4개 꼭짓점, [[x,y],...], 시계방향 좌상단부터)의 상단 변
    (점0→점1)이 수평에서 몇 도 기울었는지 반환한다 — 수평이면 0°에 가깝다.
    페이지 전체 기울기 추정(_run_ocr_on_image가 여러 상자의 각도를 모아 중앙값을
    냄)에 쓴다. 두 점이 같으면(퇴화 상자) None."""
    (x0, y0), (x1, y1) = poly[0], poly[1]
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(dy, dx))


class OcrEngineError(DocumentParseError):
    """PaddleOCR 엔진 자체가 실패했을 때(모델 로드 실패·인식 호출 예외 등) — "읽긴
    읽었지만 형식이 다르거나 저화질이라 못 알아봄"(DocumentParseError)과 구분해
    db/quality_issues.py에 다른 사유로 기록하기 위한 서브클래스."""


class OcrResult:
    __slots__ = ("text", "rows", "confidence", "boxes", "skew_deg")

    def __init__(
        self,
        text: str,
        rows: list[OcrRow],
        confidence: float,
        boxes: list[tuple[float, float, float, float, str]] = (),
        skew_deg: float | None = None,
    ):
        self.text = text
        self.rows = rows
        self.confidence = confidence
        # 클러스터링 전 원시 박스(x0,x1,y0,y1,text), 원본 이미지 픽셀 좌표계 — 행으로
        # 뭉개지면서 사라지는 y좌표가 필요한 2차 크롭 재인식(ocr_retry_region 호출부)
        # 전용. 첫 페이지 것만 담는다(멀티페이지 PDF는 크롭 재시도 대상 밖 — 실사용
        # 케이스인 사진 업로드는 항상 1장이라 충분).
        self.boxes = boxes
        # 감지 상자들의 각도 중앙값(도 단위) — 페이지 전체가 몇 도쯤 기울어져
        # 촬영됐는지 추정(_box_angle_deg 참고). 신뢰할 상자가 없으면 None.
        # document_extraction.py가 완만한 기울기(±수도~수십도)만 보정 재시도의
        # 신호로 쓴다 — PaddleOCR 자체 회전판별기(use_doc_orientation_classify)는
        # 0/90/180/270도 분류만 하고 오탐 이력이 있어 꺼져 있다(_get_ocr_engine
        # 주석 참고). 감지 상자 각도를 직접 읽는 건 PaddleOCR 커뮤니티가 실제로
        # 쓰는 방법이다(GitHub Discussion #13264).
        self.skew_deg = skew_deg


def _get_ocr_engine():
    global _ocr_engine
    # 업로드 라우터가 요청마다 asyncio.to_thread로 별도 스레드를 띄운다(api/routers/
    # owner.py) — 여러 장을 동시에 올리면 이 함수가 여러 스레드에서 거의 동시에
    # 불린다. 락 없이 "None이면 만든다"만 하면 전부 None을 보고 각자 무거운
    # PaddleOCR 인스턴스를 따로 만들어버려(실측 확인 — 로그에 "Creating model"이
    # 요청 수만큼 반복) 메모리를 짓눌러 컨테이너가 응답 불능(unhealthy)에 빠진다.
    # 더블체크락으로 실제 생성은 딱 한 번만 일어나게 한다.
    if _ocr_engine is not None:
        return _ocr_engine
    with _ocr_engine_lock:
        if _ocr_engine is None:
            try:
                from paddleocr import PaddleOCR
                # use_textline_orientation=False, use_doc_orientation_classify=False —
                # 실측으로 확인된 두 가지 별도 버그: ① 줄 단위 180도 회전 판별이 관리비
                # 고지서 사진을, ② 전체 페이지 회전 판별이 항목이 많은(청구내역 표가 긴)
                # 전기요금 청구서 사진을 각각 똑바로 찍힌 멀쩡한 문서인데도 뒤집힌/회전된
                # 걸로 오판해 글자를 깨뜨렸다(신뢰도 0.5대, 텍스트가 전부 뒤섞여 나옴).
                # 둘 다 "정보량이 많거나 서식이 조금만 복잡해도 오탐하는" 같은 패턴이라,
                # 이 프로젝트 실사용 케이스(사장님이 문서를 대체로 똑바로 찍어 올림)에서는
                # 두 판별 모두 이득보다 오탐 위험이 크다고 보고 끈다.
                #
                # use_doc_unwarping은 명시하지 않고 기본값(True)을 그대로 둔다 — 한때
                # False로 바꿔봤다가 되돌린 이력이 있다(2026-08-19→08-20). 켜져 있으면
                # PaddleOCR이 감지 *전에* 내부 원근보정을 먼저 하고 그 보정된 이미지
                # 기준 좌표를 돌려주는데, 이 모듈의 크롭 재시도(ocr_retry_region)·기울기
                # 보정(deskew_image_bytes)은 rasterize_to_images(file_bytes)로 얻은
                # "보정 안 된 원본" 픽셀에 그 좌표를 그대로 적용한다 — 이론상 좌표계가
                # 서로 다른 두 이미지를 섞어 쓰는 셈이라(실측: 14도 비스듬히 찍힌 사진
                # 기준 unwarping 켜짐일 땐 감지 상자 각도가 -1.1도로, 꺼짐일 땐 실제
                # 육안 기울기와 같은 -14.3도로 측정됨), 크롭이 어긋날 위험이 있다.
                # 그런데 실측으로 直접 꺼봤더니 오히려 이미 정상 처리되던 문서(칠곡주유소
                # 세금계산서 정면샷)가 실패로 바뀌었다 — 이 문서는 unwarping이 하는 미세
                # 원근보정 자체가 인식 품질에 필요했던 것으로 보인다. 좌표계 불일치는
                # 알려진 한계로 남겨두고(완만한 기울기 문서 일부는 크롭 재시도가 안
                # 맞을 수 있음), 껐을 때의 순손실이 더 커서 기본값을 유지한다.
                #
                # text_detection_model_name/text_recognition_model_name — 실측으로 확인된
                # 세 번째 버그: lang="korean" 기본 선택값은 문자 감지에 "server" 등급
                # 모델(PP-OCRv5_server_det)을 쓰는데, 표 테두리가 빽빽한 세금계산서
                # 사진(품목 표)에서 메모리 부족으로 프로세스가 죽었다(SIGKILL, "Failed to
                # fetch"/"signal timed out"으로 사용자에게 보임 — 겉으로는 그냥 멈춘 것
                # 처럼 보이지만 실제로는 OOM). 감지 모델을 "mobile" 등급으로 낮추면 같은
                # 파일이 30초 이내 정상 완료된다(신뢰도·인식 품질 저하 없음, 실측 확인).
                # 감지 모델을 직접 지정하면 lang= 자동 선택이 무시되므로 한국어 인식
                # 모델도 함께 명시해 한국어 정확도를 유지한다.
                _ocr_engine = PaddleOCR(
                    use_textline_orientation=False,
                    use_doc_orientation_classify=False,
                    text_detection_model_name="PP-OCRv5_mobile_det",
                    text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                )
            except Exception as e:  # noqa: BLE001 — 모델 로드·의존성 문제 등
                raise OcrEngineError(f"OCR 엔진을 불러오지 못했어요 — {e}") from e
    return _ocr_engine


def _get_retry_ocr_engine():
    """ocr_retry_region() 전용 2차 엔진 — 감지 모델만 "server" 등급으로 올린다.

    실측(2026-08-19, 별지 제11호 서식 세금계산서 실촬영 사진): "작성"(년월일) 칸이
    낱낱 칸에 숫자 하나씩 인쇄돼 있는데, 위 mobile 감지 모델은 이 촘촘한 격자에서
    글자 경계를 제대로 못 잡아 "20"/"X"/"*∗" 같은 쓰레기로 읽는다. 같은 크롭을
    server 감지 모델로 다시 돌리면 "25"(conf 0.999)/"5"(0.985)/"8"(0.99)을 정확히
    읽어낸다 — 병목이 인식 모델이 아니라 감지 모델이었다는 뜻(한국어 인식은 애초에
    "server" 등급 모델 자체가 이 PaddleOCR 버전에 없다 — 실측으로 UnknownModelError
    확인, 그래서 인식은 mobile 그대로 둔다).

    _get_ocr_engine()이 감지 모델을 mobile로 낮춘 이유(표 테두리 빽빽한 전체 페이지
    사진에서 server 감지 모델이 OOM으로 프로세스를 죽임)는 지금도 유효하다 — 그래서
    이 엔진은 메인 엔진을 대체하지 않고, ocr_retry_region()이 만드는 작게 상한된
    크롭(_RETRY_REGION_MAX_DIM)에만 쓴다. 전체 페이지 대비 픽셀 수가 훨씬 적어 같은
    OOM 위험이 없다.

    use_doc_unwarping도 _get_ocr_engine()과 같은 이유로 명시하지 않고 기본값(True)을
    둔다 — IMG_3874가 실제로 성공했을 때(2026-08-19)의 설정이자, 껐을 때 다른
    문서에서 회귀가 확인돼(_get_ocr_engine() 주석 참고) 되돌린 값과 맞춘다."""
    global _retry_ocr_engine
    if _retry_ocr_engine is not None:
        return _retry_ocr_engine
    with _ocr_engine_lock:
        if _retry_ocr_engine is None:
            try:
                from paddleocr import PaddleOCR
                _retry_ocr_engine = PaddleOCR(
                    use_textline_orientation=False,
                    use_doc_orientation_classify=False,
                    text_detection_model_name="PP-OCRv5_server_det",
                    text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                )
            except Exception as e:  # noqa: BLE001 — 모델 로드·의존성 문제 등
                raise OcrEngineError(f"OCR 엔진을 불러오지 못했어요 — {e}") from e
    return _retry_ocr_engine


def _get_skew_probe_engine():
    """probe_skew_deg() 전용 — use_doc_unwarping=False로 감지 *전* 원근보정을 끈다.

    실측(2026-08-19→08-20): 메인 엔진(_get_ocr_engine, unwarping 켜짐)이 돌려주는
    OcrResult.skew_deg는 감지 전에 이미 내부적으로 상당 부분 펴진 뒤의 잔차각이라
    실제 촬영 기울기보다 훨씬 작게 나온다(14도짜리 사진이 -1.1도로 측정됨) — 그래서
    완만한 기울기 보정이 필요한 사진에서도 "보정 불필요"로 잘못 판단해 버렸다.
    메인 엔진은 인식 품질 때문에 unwarping을 계속 켜둬야 하므로(꺼봤다가 다른
    문서에서 회귀 확인, _get_ocr_engine() 주석 참고), 기울기를 "제대로" 재려면
    별도 엔진이 필요하다 — 이 엔진은 텍스트 인식 결과는 버리고 감지 상자 각도만
    쓴다(document_extraction.py가 다른 경로를 다 실패한 뒤 마지막으로만 부름 —
    매 문서마다 추가 인식 패스를 태우는 비용을 실패 케이스로 한정)."""
    global _skew_probe_engine
    if _skew_probe_engine is not None:
        return _skew_probe_engine
    with _ocr_engine_lock:
        if _skew_probe_engine is None:
            try:
                from paddleocr import PaddleOCR
                _skew_probe_engine = PaddleOCR(
                    use_textline_orientation=False,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    text_detection_model_name="PP-OCRv5_mobile_det",
                    text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                )
            except Exception as e:  # noqa: BLE001 — 모델 로드·의존성 문제 등
                raise OcrEngineError(f"OCR 엔진을 불러오지 못했어요 — {e}") from e
    return _skew_probe_engine


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


def _run_ocr_on_image(
    image: Image.Image, engine=None
) -> tuple[list[OcrRow], list[float], list[tuple[float, float, float, float, str]], list[float]]:
    if engine is None:
        engine = _get_ocr_engine()
    # _get_ocr_engine()의 락은 "엔진을 한 번만 만드는 것"만 지켜줄 뿐, 만들어진 뒤엔
    # 모든 스레드가 같은 engine 인스턴스를 공유한다. PaddleOCR의 predict()는 내부
    # C++ 추론 엔진 상태를 건드리는데 동시 호출에 안전하지 않다 — 실측으로 여러 장을
    # 동시에 올렸을 때 "double free or corruption"/"corrupted size vs. prev_size in
    # fastbins"로 프로세스 자체가 죽는 걸 확인했다(엔진 재생성 문제와는 별개 버그).
    # predict() 호출 자체도 같은 락으로 감싸 전체 프로세스 안에서 OCR 인식이 한
    # 번에 하나씩만 돌게 강제한다 — 여러 장을 동시에 올려도 인식은 순차 처리된다.
    with _ocr_engine_lock:
        try:
            predictions = engine.predict(np.array(image))
        except Exception as e:  # noqa: BLE001
            raise OcrEngineError(f"OCR 인식에 실패했어요 — {e}") from e

    boxes: list[tuple[float, float, float, float, str]] = []
    scores: list[float] = []
    angles: list[float] = []
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
            edge_len = math.hypot(poly[1][0] - poly[0][0], poly[1][1] - poly[0][1])
            if edge_len >= _MIN_ANGLE_BOX_EDGE_LEN:
                angle = _box_angle_deg(poly)
                if angle is not None:
                    angles.append(angle)
    return _cluster_rows(boxes), scores, boxes, angles


def ocr_extract(file_bytes: bytes) -> OcrResult:
    """이미지·스캔 PDF에서 텍스트/좌표를 재구성한다. 아무 글자도 못 읽으면 값을
    지어내지 않고 DocumentParseError(실패 가시성 원칙, CLAUDE.md §6). 이 함수 자체는
    db/document_text_extractor.py의 정규식 파서를 부르지 않는다 — 구조화 책임 분리
    (파일 상단 docstring 참고), 호출부(db/document_extraction.py)가 이어서 부른다.
    """
    images = rasterize_to_images(file_bytes)

    all_rows: list[OcrRow] = []
    all_scores: list[float] = []
    first_page_boxes: list[tuple[float, float, float, float, str]] = []
    first_page_angles: list[float] = []
    for page_index, image in enumerate(images):
        rows, scores, boxes, angles = _run_ocr_on_image(image)
        all_rows.extend(rows)
        all_scores.extend(scores)
        if page_index == 0:
            first_page_boxes = boxes
            first_page_angles = angles

    if not all_rows:
        raise DocumentParseError("문서에서 글자를 인식하지 못했어요 — 더 선명하게 다시 올려 주세요")

    linear_text = "\n".join(" ".join(cell_text for _, _, cell_text in row) for row in all_rows)
    confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
    skew_deg = statistics.median(first_page_angles) if first_page_angles else None
    return OcrResult(
        text=linear_text, rows=all_rows, confidence=confidence, boxes=first_page_boxes, skew_deg=skew_deg
    )


_RETRY_REGION_MAX_DIM = 3000  # px, 확대 후 최대 변 길이 — 아래 docstring 참고


def ocr_retry_region(
    file_bytes: bytes, box: tuple[float, float, float, float], upscale: float = 3.0
) -> OcrResult:
    """지정 영역(첫 인식 pass가 돌려준 원본 픽셀 좌표계의 x0,y0,x1,y1)만 잘라 확대한
    뒤 재인식한다.

    실측(2026-08-19, 사장님 실촬영 별지 제11호 서식 세금계산서 사진): 전체 페이지를
    한 번에 인식하면 문서 전체가 PaddleOCR 내부 리사이즈 한도(수천 px)에 맞춰
    축소되는데, "작성"(년월일) 칸이 "공급가액·세액" 자릿수 칸(백·십·억·천...)과
    다닥다닥 붙어 있는 구간이라 이 축소 과정에서 낱낱의 숫자가 뭉개져 못 읽힌다.
    좁게 크롭·확대까지만 해서 메인(mobile 감지) 엔진에 다시 태워도 여전히 못 읽는
    경우가 있었다 — 병목이 해상도가 아니라 감지 모델 자체였다(실측 확인). 그래서
    이 크롭만 _get_retry_ocr_engine()(server 감지+mobile 인식)으로 재인식한다 —
    parse_tax_invoice_date_table()의 4자리/2자리 연도 매칭이 실패했을 때만 부르는
    2차 시도 전용(db/document_extraction.py).

    확대 후 크기를 _RETRY_REGION_MAX_DIM으로 상한(실측 2026-08-19: 호출부가 넓은
    영역을 넘기면 3배 확대가 1만6천px대 이미지를 만들어 처리시간만 크게 늘고,
    결국 PaddleOCR 내부에서 다시 다운스케일돼 애초 목적조차 무의미해지는 사고가
    실제로 발생함 — 이 함수 자신이 방어해야 재발하지 않는다). 상한에 걸리면 upscale
    배율 자체를 줄인다(크롭이 이미 크면 확대할 필요·여유가 적다는 뜻이기도 하다).

    영역 자체를 다시 못 읽으면(크롭 좌표가 이미지 밖이거나 글자가 아예 없음)
    DocumentParseError — 호출부가 그냥 실패로 처리하면 된다(이 함수가 마지막
    시도이므로 추가 폴백은 없음)."""
    images = rasterize_to_images(file_bytes)
    if not images:
        raise DocumentParseError("문서를 다시 읽지 못했어요")
    image = images[0]
    x0, y0, x1, y1 = box
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(image.width), x1), min(float(image.height), y1)
    if x1 <= x0 or y1 <= y0:
        raise DocumentParseError("영역을 다시 읽지 못했어요")
    cropped = image.crop((x0, y0, x1, y1))
    longest_side = max(cropped.width, cropped.height, 1)
    effective_upscale = min(upscale, _RETRY_REGION_MAX_DIM / longest_side)
    effective_upscale = max(effective_upscale, 1.0) if longest_side <= _RETRY_REGION_MAX_DIM else effective_upscale
    cropped = cropped.resize(
        (max(1, int(cropped.width * effective_upscale)), max(1, int(cropped.height * effective_upscale))),
        Image.LANCZOS,
    )
    rows, scores, _boxes, _angles = _run_ocr_on_image(cropped, engine=_get_retry_ocr_engine())
    if not rows:
        raise DocumentParseError("영역을 다시 읽었지만 글자를 인식하지 못했어요")
    linear_text = "\n".join(" ".join(cell_text for _, _, cell_text in row) for row in rows)
    confidence = sum(scores) / len(scores) if scores else 0.0
    return OcrResult(text=linear_text, rows=rows, confidence=confidence)


def probe_skew_deg(file_bytes: bytes) -> float | None:
    """원본(보정 안 된) 이미지의 실제 기울기를 재측정한다.

    ocr_extract()가 메인 엔진(unwarping 켜짐)으로 계산하는 OcrResult.skew_deg는
    감지 *전에* 이미 내부적으로 원근보정된 뒤의 잔차각이라 실제 촬영 기울기보다
    훨씬 작게 나온다(실측: 14도짜리 사진이 -1.1도로 측정됨 — _get_skew_probe_engine
    주석 참고) — 그 값으로는 "보정이 필요한 완만한 기울기"를 놓친다. 이 함수는
    unwarping이 꺼진 전용 엔진으로 다시 한번 원본을 감지해 진짜 기울기를 잰다.

    document_extraction.py가 텍스트 파싱·좌표 매칭·크롭 재시도까지 전부 실패한
    뒤, LLM 최후수단 직전에 마지막으로만 부른다 — 매 문서마다 추가 인식 패스를
    태우는 비용을 실패 케이스로 한정한다. 신뢰할 상자가 없으면 None."""
    try:
        images = rasterize_to_images(file_bytes)
    except DocumentParseError:
        return None
    if not images:
        return None
    _rows, _scores, _boxes, angles = _run_ocr_on_image(images[0], engine=_get_skew_probe_engine())
    if not angles:
        return None
    return statistics.median(angles)


def deskew_image_bytes(file_bytes: bytes, skew_deg: float) -> bytes | None:
    """probe_skew_deg()가 추정한 기울기만큼 이미지를 반대 방향으로 돌려 새 JPEG
    바이트로 반환한다.

    실측(2026-08-19, 같은 세금계산서를 비스듬히 찍은 사진): 완만하게 기울여 찍힌
    사진은 전체 페이지 감지 자체는 성공하지만(제목·헤더 등은 찾음), 좌표 기반 크롭
    (find_tax_invoice_date_crop_box)이 축에 정렬된 사각형이라 실제로 기울어진
    날짜 격자가 크롭 밖으로 밀려나거나 뒤틀린 채 들어가 크롭 재인식마저 실패했다.
    문서 전체를 먼저 똑바로 펴면 이후 모든 좌표 기반 로직(크롭 계산 포함)이
    그대로 재사용 가능해진다.

    PDF는 대상 밖(None) — 텍스트 레이어 경로는 애초에 좌표 기반 크롭을 안 쓰고,
    스캔 PDF도 이 함수 호출 시점(document_extraction.py)에서는 이미 사진 전용
    분기 안이라 실제로 PDF가 들어올 일이 없다. 방어적으로만 걸러낸다."""
    if file_bytes[:4] == b"%PDF":
        return None
    try:
        images = rasterize_to_images(file_bytes)
    except DocumentParseError:
        return None
    if not images:
        return None
    image = images[0]
    rotated = image.convert("RGB").rotate(-skew_deg, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
    buf = io.BytesIO()
    rotated.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# 문서(종이) 윤곽으로 인정할 최소 면적 비율 — 전체 이미지 대비. 이보다 작은 윤곽은
# 노이즈(그림자·배경 물체)일 가능성이 높아 문서로 보지 않는다.
_MIN_DOCUMENT_CONTOUR_AREA_RATIO = 0.15


def _order_corners(pts) -> "np.ndarray":
    """4개 점을 top-left, top-right, bottom-right, bottom-left 순서로 정렬한다 —
    문서 스캐너 구현의 표준 기법(좌표 합이 가장 작은/큰 점이 각각 좌상단/우하단,
    차이가 가장 작은/큰 점이 각각 우상단/좌하단)."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1).reshape(-1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


# 모서리가 이미지 가장자리에서 이 픽셀 이내면 "진짜 모서리"가 아니라 "종이가
# 프레임 밖으로 잘려 나간 지점"으로 본다.
_CORNER_CLIP_TOLERANCE_PX = 5


def _fix_clipped_corner(corners, image_size: tuple[int, int]):
    """검출된 4개 모서리 중 정확히 하나가 사진 프레임 가장자리에 걸쳐 있으면
    (종이가 그 방향으로 잘려 나가 진짜 모서리가 안 보이는 경우) 평행사변형
    가정(마주보는 두 변이 평행)으로 그 지점을 재추정한다.

    실측(2026-08-20, IMG_3875): 우측 하단 모서리가 정확히 이미지 폭 끝(x=5711,
    폭 5712)에서 검출됐다 — 종이의 진짜 모서리가 아니라 카메라 프레임이 거기서
    끝나 버린 지점이었다. 이 잘못된 좌표로 원근변환을 하면 전체 homography가
    미세하게 틀어져, 육안으로는 표가 안 나도 촘촘한 날짜 숫자 격자 감지에서만
    문제가 드러났다(실측 확인 — 잘린 좌표 그대로 쓰면 날짜 숫자가 아예 감지
    자체가 안 됐고, 평행사변형으로 재추정한 좌표를 쓰면 "24"(오독이지만 위치는
    찾음)·"5"가 함께 잡히기 시작했다).

    두 개 이상 잘려 있으면(마주보는 변까지 안 보일 수 있어) 평행사변형 가정을
    신뢰할 수 없어 원래 좌표 그대로 둔다."""
    width, height = image_size

    def _is_clipped(pt) -> bool:
        x, y = pt
        return (
            x <= _CORNER_CLIP_TOLERANCE_PX
            or x >= width - 1 - _CORNER_CLIP_TOLERANCE_PX
            or y <= _CORNER_CLIP_TOLERANCE_PX
            or y >= height - 1 - _CORNER_CLIP_TOLERANCE_PX
        )

    clipped = [_is_clipped(pt) for pt in corners]
    if sum(clipped) != 1:
        return corners

    fixed = corners.copy()
    idx = clipped.index(True)
    # 평행사변형: 잘린 점 = 대각선 반대쪽 점 기준으로 나머지 두 점의 벡터 합.
    # corners 순서는 [tl, tr, br, bl] — 대각선 반대는 (idx+2)%4, 인접한 두 점은
    # 그 사이 두 인덱스.
    opposite = corners[(idx + 2) % 4]
    neighbor_a = corners[(idx + 1) % 4]
    neighbor_b = corners[(idx + 3) % 4]
    fixed[idx] = neighbor_a + neighbor_b - opposite
    return fixed


def _find_document_corners(image: Image.Image):
    """사진에서 종이 문서의 4개 모서리를 찾는다 — 배경과 대비되는 가장 큰 사각형
    윤곽을 찾는 전형적인 문서 스캐너 기법(엣지 검출 → 윤곽 검출 → 4점 다각형 근사).

    실측(2026-08-19→08-20, IMG_3875 — 카메라 각도 때문에 원근 왜곡까지 낀 사진):
    단순 2D 회전 보정(deskew_image_bytes)은 메인 엔진이 재측정한 잔차 기울기가
    -14도→-8도로 절반만 없어지는 등 완전히 못 고쳤다 — 회전이 아니라 사다리꼴
    원근 왜곡이 원인이라 원근변환(homography)으로 종이의 실제 네 모서리를 펴야
    한다.

    신뢰할 만한 사각형을 못 찾으면(배경이 지저분하거나 종이가 이미지 가장자리에
    닿아 잘려 있는 등) None — 호출부(perspective_correct_image_bytes)가 기존
    단순 회전 보정으로 폴백할 수 있게.

    cv2는 requirements.txt에 직접 안 올려도 된다 — paddleocr/paddlex가 이미
    opencv-contrib-python을 끌어와 컨테이너에 항상 존재한다(실측 확인, 버전
    4.10.0.84). 직접 올리면 opencv 패키지 두 개가 같은 cv2 네이티브 파일을 서로
    덮어쓰는 흔한 pip 충돌 위험이 생긴다 — 로컬 개발 venv에서만 필요하면
    `pip install opencv-python-headless`로 따로 설치."""
    import cv2

    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    # 블러·팽창을 넉넉히 줘야 한다 — 실측(IMG_3875): 종이 오른쪽 가장자리가
    # 배경과 대비가 약한 구간에서, 좁은 커널로는 윤곽선이 진짜 종이 테두리 대신
    # 대비가 강한 안쪽 표 선(세액·공급가액 칸 경계)으로 "새어" 들어가 10개+
    # 꼭짓점의 울퉁불퉁한 다각형이 됐다. 팽창(15x15, 3회)으로 약한 경계를 이어
    # 붙인 뒤 침식(9x9, 2회)으로 다시 얇게 되돌리면 진짜 외곽선만 남는다.
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    edges = cv2.Canny(blurred, 30, 100)
    edges = cv2.dilate(edges, np.ones((15, 15), np.uint8), iterations=3)
    edges = cv2.erode(edges, np.ones((9, 9), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    image_area = arr.shape[0] * arr.shape[1]
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < image_area * _MIN_DOCUMENT_CONTOUR_AREA_RATIO:
        return None

    peri = cv2.arcLength(largest, True)
    # epsilon을 점점 키워가며 4점으로 수렴할 때까지 시도한다 — 실측(IMG_3875):
    # 0.02는 10점, 0.03에서야 정확히 4점(실제 종이 모서리와 일치, 시각 확인)으로
    # 떨어졌다. 문서마다 필요한 epsilon이 달라 고정값 하나로는 부족하다.
    approx = None
    for eps_ratio in (0.02, 0.03, 0.04, 0.05):
        candidate = cv2.approxPolyDP(largest, eps_ratio * peri, True)
        if len(candidate) == 4:
            approx = candidate
            break
    if approx is None:
        return None

    corners = _order_corners(approx.reshape(4, 2).astype("float32"))
    return _fix_clipped_corner(corners, image.size)


def perspective_correct_image_bytes(file_bytes: bytes) -> bytes | None:
    """사진에서 종이 문서의 네 모서리를 찾아 원근변환(homography)으로 평평하게
    편 뒤 새 JPEG 바이트로 반환한다.

    document_extraction.py의 최후수단 직전 보정 단계에서 deskew_image_bytes(단순
    회전)보다 먼저 시도한다 — 회전과 원근 왜곡을 동시에 교정할 수 있어 더 강력한
    보정이지만, 종이의 네 모서리를 못 찾으면(배경이 균일하지 않거나 종이가 잘려
    나감 등) None을 돌려주고 호출부가 단순 회전 보정으로 폴백한다."""
    if file_bytes[:4] == b"%PDF":
        return None
    try:
        images = rasterize_to_images(file_bytes)
    except DocumentParseError:
        return None
    if not images:
        return None
    image = images[0]
    corners = _find_document_corners(image)
    if corners is None:
        return None

    import cv2

    tl, tr, br, bl = corners
    max_width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    max_height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if max_width < 10 or max_height < 10:
        return None

    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(corners, dst)
    arr = np.array(image.convert("RGB"))
    warped = cv2.warpPerspective(arr, matrix, (max_width, max_height))

    result_image = Image.fromarray(warped)
    buf = io.BytesIO()
    result_image.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
