"""db/document_ocr_extractor.py — PaddleOCR 로컬 텍스트/좌표 재구성 검증.

무거운 모델 로딩·실제 인식은 쓰지 않는다 — 엔진 호출(_run_ocr_on_image)을 스텁으로
대체(tests/test_document_vision_extractor.py가 쓰던 _call_gemini_vision 스텁 패턴과
동일한 자리를 대신한다)."""
import io
import math

import pytest
from PIL import Image, ImageDraw

import db.document.document_ocr_extractor as ocr_mod
from db.document.document_text_extractor import DocumentParseError
import numpy as np

from db.document.document_ocr_extractor import (
    OcrEngineError,
    _box_angle_deg,
    _cluster_rows,
    _find_document_corners,
    _fix_clipped_corner,
    _is_heic,
    _is_webp,
    deskew_image_bytes,
    ocr_extract,
    perspective_correct_image_bytes,
    probe_skew_deg,
    rasterize_to_images,
)


def _trapezoid_document_jpeg_bytes(pts) -> bytes:
    """어두운 배경에 흰 사각형(4점 다각형)을 그린 합성 "문서 사진" — 원근/회전
    왜곡을 흉내낸다(실제 사진처럼 종이가 배경과 대비되는 전형적인 촬영 구도)."""
    img = Image.new("RGB", (800, 600), (60, 50, 90))
    draw = ImageDraw.Draw(img)
    draw.polygon(pts, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _png_bytes(size=(20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(size=(20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="JPEG")
    return buf.getvalue()


def _webp_bytes(size=(20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="WEBP")
    return buf.getvalue()


# ── 포맷 판별 ────────────────────────────────────────────────────────────────

def test_rasterize_unknown_bytes_raises():
    with pytest.raises(DocumentParseError):
        rasterize_to_images(b"not an image or pdf")


def test_rasterize_jpeg_returns_one_image():
    images = rasterize_to_images(_jpeg_bytes())
    assert len(images) == 1
    assert images[0].mode == "RGB"


def test_rasterize_png_returns_one_image():
    images = rasterize_to_images(_png_bytes())
    assert len(images) == 1


def test_rasterize_webp_returns_one_image():
    images = rasterize_to_images(_webp_bytes())
    assert len(images) == 1


def test_is_heic_detects_iso_bmff_heic_brand():
    # ISO BMFF 컨테이너: offset 4~8 "ftyp", 8~12 브랜드("heic")
    heic_header = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8
    assert _is_heic(heic_header) is True


def test_is_heic_rejects_non_heic():
    assert _is_heic(b"not heic at all, too short") is False
    assert _is_heic(_png_bytes()) is False


def test_is_webp_detects_riff_webp_container():
    assert _is_webp(_webp_bytes()) is True
    assert _is_webp(_png_bytes()) is False


# ── 행 클러스터링 ────────────────────────────────────────────────────────────

def test_cluster_rows_groups_same_row_by_y_overlap_and_orders_by_x():
    """실측 스파이크 좌표 재현 — 헤더 행(품목명/규격/수량/단가/공급가액)이 y가 완벽히
    안 맞아도 한 행으로 묶이고, x좌표 순서로 정렬된다."""
    boxes = [
        (581.0, 748.0, 198.0, 233.0, "공급가액(원)"),  # x로는 마지막, 입력 순서는 뒤섞임
        (0.0, 82.0, 196.0, 233.0, "품목명"),
        (404.0, 516.0, 195.0, 235.0, "단가(원)"),
        (267.0, 336.0, 195.0, 234.0, "수량"),
        (129.0, 195.0, 195.0, 234.0, "규격"),
        # 다른 행(y가 확실히 떨어져 있음)
        (0.0, 55.0, 250.0, 292.0, "경유"),
    ]
    rows = _cluster_rows(boxes)
    assert len(rows) == 2
    header_row = rows[0]
    assert [text for _, _, text in header_row] == ["품목명", "규격", "수량", "단가(원)", "공급가액(원)"]
    assert rows[1] == [(0.0, 55.0, "경유")]


def test_cluster_rows_empty_input():
    assert _cluster_rows([]) == []


# ── 기울기 각도 추정(_box_angle_deg) ──────────────────────────────────────────

def test_box_angle_deg_horizontal_is_near_zero():
    poly = [[0.0, 0.0], [100.0, 2.0], [100.0, 20.0], [0.0, 18.0]]
    assert _box_angle_deg(poly) == pytest.approx(math.degrees(math.atan2(2.0, 100.0)))


def test_box_angle_deg_tilted_box():
    """8도쯤 기울여 찍은 사진의 감지 상자를 재현 — 상단 변(점0→점1)의 기울기가
    그대로 반영돼야 한다."""
    tilt = math.radians(8.0)
    x1, y1 = 100.0 * math.cos(tilt), 100.0 * math.sin(tilt)
    poly = [[0.0, 0.0], [x1, y1], [x1, y1 + 20.0], [0.0, 20.0]]
    assert _box_angle_deg(poly) == pytest.approx(8.0, abs=0.01)


def test_box_angle_deg_degenerate_box_returns_none():
    poly = [[5.0, 5.0], [5.0, 5.0], [5.0, 25.0], [5.0, 25.0]]
    assert _box_angle_deg(poly) is None


# ── ocr_extract (엔진 스텁) ───────────────────────────────────────────────────

def test_ocr_extract_reconstructs_linear_text_and_rows(monkeypatch):
    def _fake_run(image):
        rows = [[(0.0, 80.0, "청구월: 2025-06")], [(0.0, 120.0, "청구금액(원) 987,654")]]
        return rows, [0.95, 0.9], [], []

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    result = ocr_extract(b"irrelevant since rasterize is stubbed")
    assert "청구월: 2025-06" in result.text
    assert "청구금액(원) 987,654" in result.text
    assert result.confidence == pytest.approx(0.925)
    assert len(result.rows) == 2


def test_ocr_extract_computes_skew_deg_as_median_of_box_angles(monkeypatch):
    """_run_ocr_on_image가 돌려주는 각도 목록의 중앙값을 OcrResult.skew_deg로
    노출해야 한다 — document_extraction.py가 완만한 기울기 보정 재시도 여부를
    판단하는 유일한 신호."""
    def _fake_run(image):
        return [[(0.0, 10.0, "x")]], [0.9], [], [7.0, 9.0, 8.0]

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    result = ocr_extract(b"irrelevant")
    assert result.skew_deg == pytest.approx(8.0)


def test_ocr_extract_skew_deg_none_when_no_reliable_angles(monkeypatch):
    def _fake_run(image):
        return [[(0.0, 10.0, "x")]], [0.9], [], []

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    result = ocr_extract(b"irrelevant")
    assert result.skew_deg is None


def test_ocr_extract_multi_page_concatenates_rows(monkeypatch):
    calls = {"n": 0}

    def _fake_run(image):
        calls["n"] += 1
        return [[(0.0, 10.0, f"page{calls['n']}")]], [0.8], [], []

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object(), object()])

    result = ocr_extract(b"irrelevant")
    assert calls["n"] == 2
    assert "page1" in result.text and "page2" in result.text


def test_ocr_extract_no_text_found_raises(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", lambda image: ([], [], [], []))
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    with pytest.raises(DocumentParseError):
        ocr_extract(b"irrelevant")


def test_run_ocr_on_image_engine_failure_raises_ocr_engine_error(monkeypatch):
    class _BoomEngine:
        def predict(self, arr):
            raise RuntimeError("모델 추론 실패")

    monkeypatch.setattr(ocr_mod, "_get_ocr_engine", lambda: _BoomEngine())
    with pytest.raises(OcrEngineError):
        ocr_mod._run_ocr_on_image(Image.new("RGB", (10, 10)))


def test_ocr_engine_error_is_a_document_parse_error():
    """기존 except DocumentParseError 블록(api/routers/owner.py)이 그대로 잡을 수 있어야 한다."""
    assert issubclass(OcrEngineError, DocumentParseError)


def test_get_ocr_engine_disables_textline_orientation(monkeypatch):
    """실측(Docker e2e) 확인: 줄 단위 180도 회전 판별(use_textline_orientation)이
    똑바로 찍힌 멀쩡한 문서(관리비 고지서 사진)도 뒤집힌 걸로 오판해 글자를 깨뜨리는
    사례가 나왔다 — 전기고지서·세금계산서 사진은 정상이었는데 같은 조건의 다른
    사진에서만 재현돼 이 모듈로 원인이 좁혀졌다. 이어서 실제 한전 고지서 구조(청구
    내역이 긴 표)를 흉내낸 사진에서는 use_doc_orientation_classify(전체 페이지 회전
    판별)가 같은 종류로 또 오탐했다 — 정보량이 많거나 서식이 복잡하면 두 판별 모두
    오탐 위험이 커지는 패턴. 사장님이 문서를 대체로 똑바로 찍어 올리는 실사용
    케이스에서 둘 다 이득보다 오탐 위험이 커서 꺼둔다 — 누군가 나중에 무심코
    지우지 않도록 회귀 테스트로 고정."""
    ocr_mod._ocr_engine = None  # 이전 테스트의 singleton 캐시 초기화
    captured = {}

    class _FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys
    import types

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = _FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    ocr_mod._get_ocr_engine()
    assert captured.get("use_textline_orientation") is False
    assert captured.get("use_doc_orientation_classify") is False
    ocr_mod._ocr_engine = None  # 다른 테스트에 영향 안 주게 정리


def test_get_ocr_engine_uses_mobile_detection_model(monkeypatch):
    """실측(Docker e2e) 확인: lang="korean" 기본 선택값(PP-OCRv5_server_det, "server"
    등급 문자 감지 모델)이 표 테두리가 빽빽한 세금계산서 사진에서 메모리 부족으로
    프로세스를 죽였다(SIGKILL) — 사용자에게는 그냥 업로드가 멈춘 것처럼 보였다.
    "mobile" 등급 감지 모델로 낮추면 같은 파일이 정상 완료된다(인식 품질 저하
    없음, 실측 확인). 감지 모델을 직접 지정하면 lang= 자동 선택이 무시되므로
    한국어 인식 모델도 함께 명시해야 한다 — 둘 다 회귀 테스트로 고정."""
    ocr_mod._ocr_engine = None
    captured = {}

    class _FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys
    import types

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = _FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    ocr_mod._get_ocr_engine()
    assert captured.get("text_detection_model_name") == "PP-OCRv5_mobile_det"
    assert captured.get("text_recognition_model_name") == "korean_PP-OCRv5_mobile_rec"
    ocr_mod._ocr_engine = None  # 다른 테스트에 영향 안 주게 정리


def test_get_ocr_engine_does_not_override_doc_unwarping(monkeypatch):
    """실측(2026-08-19→08-20): use_doc_unwarping을 False로 꺼봤다가 되돌린 이력이
    있다 — 이론상으론 이 모듈의 크롭 재시도·기울기 보정이 "보정 안 된 원본" 좌표계로
    동작하는데 unwarping이 켜져 있으면 좌표계가 어긋날 수 있어 껐지만, 실측으로
    직접 꺼보니 이미 정상 처리되던 문서(칠곡주유소 세금계산서 정면샷)가 오히려
    실패로 바뀌었다 — 이 설정이 하는 미세 원근보정 자체가 인식 품질에 필요했다.
    좌표계 불일치는 알려진 한계로 남기고 기본값(True)을 유지한다 — 누군가 나중에
    무심코 다시 끄지 않도록 회귀 테스트로 고정."""
    ocr_mod._ocr_engine = None
    captured = {}

    class _FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys
    import types

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = _FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    ocr_mod._get_ocr_engine()
    assert "use_doc_unwarping" not in captured
    ocr_mod._ocr_engine = None  # 다른 테스트에 영향 안 주게 정리


def test_get_retry_ocr_engine_config(monkeypatch):
    """ocr_retry_region() 전용 2차 엔진 — server 감지 모델, mobile 인식 모델(한국어
    server 인식 모델은 이 PaddleOCR 버전에 없음, 실측 UnknownModelError로 확인).
    doc_unwarping은 메인 엔진과 같은 이유로 기본값(True)을 유지한다 — 명시적으로
    안 건드림."""
    ocr_mod._retry_ocr_engine = None
    captured = {}

    class _FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys
    import types

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = _FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    ocr_mod._get_retry_ocr_engine()
    assert captured.get("text_detection_model_name") == "PP-OCRv5_server_det"
    assert captured.get("text_recognition_model_name") == "korean_PP-OCRv5_mobile_rec"
    assert "use_doc_unwarping" not in captured
    ocr_mod._retry_ocr_engine = None  # 다른 테스트에 영향 안 주게 정리


# ── deskew_image_bytes ────────────────────────────────────────────────────────

def test_deskew_image_bytes_rotates_and_reencodes_as_jpeg():
    img = Image.new("RGB", (100, 40), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    original_bytes = buf.getvalue()

    result = deskew_image_bytes(original_bytes, 8.0)
    assert result is not None
    rotated = Image.open(io.BytesIO(result))
    assert rotated.format == "JPEG"
    # expand=True라 회전 후 캔버스가 커진다(원본 100x40 그대로면 회전이 안 먹었다는 뜻).
    assert rotated.size != (100, 40)


def test_deskew_image_bytes_rejects_pdf():
    assert deskew_image_bytes(b"%PDF-1.4 fake", 5.0) is None


# ── probe_skew_deg ────────────────────────────────────────────────────────────

def test_get_skew_probe_engine_disables_doc_unwarping(monkeypatch):
    """probe_skew_deg() 전용 엔진은 unwarping을 꺼서 원본 그대로의 진짜 기울기를
    재야 한다 — 메인 엔진(unwarping 켜짐)의 skew_deg는 내부 원근보정으로 오염돼
    실제 기울기보다 훨씬 작게 나온다(실측: 14도 사진이 -1.1도로 측정됨)."""
    ocr_mod._skew_probe_engine = None
    captured = {}

    class _FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys
    import types

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = _FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    ocr_mod._get_skew_probe_engine()
    assert captured.get("use_doc_unwarping") is False
    ocr_mod._skew_probe_engine = None  # 다른 테스트에 영향 안 주게 정리


def test_probe_skew_deg_returns_median_of_raw_angles(monkeypatch):
    def _fake_run(image, engine=None):
        return [], [], [], [7.0, 9.0, 8.0]

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "_get_skew_probe_engine", lambda: object())
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    assert probe_skew_deg(b"irrelevant") == pytest.approx(8.0)


def test_probe_skew_deg_none_when_no_angles(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", lambda image, engine=None: ([], [], [], []))
    monkeypatch.setattr(ocr_mod, "_get_skew_probe_engine", lambda: object())
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    assert probe_skew_deg(b"irrelevant") is None


def test_probe_skew_deg_none_when_unreadable(monkeypatch):
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: (_ for _ in ()).throw(DocumentParseError("x")))
    assert probe_skew_deg(b"irrelevant") is None


# ── perspective_correct_image_bytes (원근변환) ─────────────────────────────────
# 실측(2026-08-19→08-20, IMG_3875): 카메라 각도로 인한 원근 왜곡(사다리꼴)은 단순
# 회전(deskew_image_bytes)으로 못 고친다 — 종이의 네 모서리를 찾아 homography로
# 펴야 한다. 여기서는 cv2 없이도 도는 가벼운 합성 이미지로 이 로직을 검증한다
# (paddleocr와 달리 opencv-python-headless는 로컬 dev venv에도 설치돼 있음).

def test_fix_clipped_corner_estimates_via_parallelogram():
    """실측(2026-08-20, IMG_3875) 좌표 재현 — 우측 하단(br) 모서리가 이미지 폭
    끝(x=width-1)에 걸려 있으면(종이가 프레임 밖으로 잘려 진짜 모서리가 안 보임)
    평행사변형 가정(bl + tr - tl)으로 재추정해야 한다."""
    corners = np.array(
        [[212.0, 1435.0], [5138.0, 140.0], [5711.0, 2559.0], [645.0, 3995.0]], dtype="float32"
    )
    fixed = _fix_clipped_corner(corners, (5712, 4284))
    assert fixed[2] == pytest.approx([5571.0, 2700.0])
    # 잘리지 않은 나머지 세 모서리는 그대로 유지돼야 한다.
    assert fixed[0] == pytest.approx(corners[0])
    assert fixed[1] == pytest.approx(corners[1])
    assert fixed[3] == pytest.approx(corners[3])


def test_fix_clipped_corner_no_change_when_nothing_clipped():
    corners = np.array(
        [[100.0, 100.0], [700.0, 120.0], [680.0, 550.0], [90.0, 520.0]], dtype="float32"
    )
    fixed = _fix_clipped_corner(corners, (800, 600))
    assert fixed == pytest.approx(corners)


def test_fix_clipped_corner_no_change_when_two_clipped():
    """두 개 이상 잘려 있으면(마주보는 변까지 안 보일 수 있어) 평행사변형 가정을
    못 믿으므로 원래 좌표를 그대로 둔다."""
    corners = np.array(
        [[0.0, 100.0], [700.0, 50.0], [750.0, 550.0], [2.0, 520.0]], dtype="float32"
    )
    fixed = _fix_clipped_corner(corners, (800, 600))
    assert fixed == pytest.approx(corners)


def test_find_document_corners_detects_trapezoid():
    """사다리꼴(원근 왜곡 흉내) 문서의 네 모서리를 정확한 순서(tl,tr,br,bl)로
    찾아야 한다."""
    pts = [(150, 100), (650, 150), (600, 500), (100, 450)]
    corners = _find_document_corners(Image.open(io.BytesIO(_trapezoid_document_jpeg_bytes(pts))))
    assert corners is not None
    for detected, expected in zip(corners, pts):
        assert abs(detected[0] - expected[0]) < 15
        assert abs(detected[1] - expected[1]) < 15


def test_find_document_corners_none_when_document_too_small():
    """배경 대비 문서 면적이 너무 작으면(노이즈일 가능성) None — 억지로 아무
    윤곽이나 문서로 오인하지 않는다."""
    pts = [(10, 10), (60, 15), (55, 60), (12, 55)]  # 800x600 대비 아주 작은 사각형
    corners = _find_document_corners(Image.open(io.BytesIO(_trapezoid_document_jpeg_bytes(pts))))
    assert corners is None


def test_perspective_correct_image_bytes_straightens_trapezoid():
    """원근변환 후 결과 이미지는 원본 사다리꼴의 기울어진 변이 아니라 곧은
    직사각형이어야 한다 — 변환 자체가 제대로 먹었는지 크기로 간접 확인."""
    pts = [(150, 100), (650, 150), (600, 500), (100, 450)]
    result = perspective_correct_image_bytes(_trapezoid_document_jpeg_bytes(pts))
    assert result is not None
    out = Image.open(io.BytesIO(result))
    assert out.format == "JPEG"
    # 원본 사다리꼴의 대략적 가로/세로 크기(약 500x400)와 비슷한 스케일이어야
    # 한다 — 완전히 엉뚱한 크기(0에 가깝거나 원본 800x600 그대로)면 변환 실패.
    assert 400 < out.size[0] < 600
    assert 300 < out.size[1] < 500


def test_perspective_correct_image_bytes_rejects_pdf():
    assert perspective_correct_image_bytes(b"%PDF-1.4 fake") is None


def test_perspective_correct_image_bytes_none_when_no_corners_found(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_find_document_corners", lambda image: None)
    plain = Image.new("RGB", (100, 100), "white")
    buf = io.BytesIO()
    plain.save(buf, format="JPEG")
    assert perspective_correct_image_bytes(buf.getvalue()) is None
