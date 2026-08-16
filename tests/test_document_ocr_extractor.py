"""db/document_ocr_extractor.py — PaddleOCR 로컬 텍스트/좌표 재구성 검증.

무거운 모델 로딩·실제 인식은 쓰지 않는다 — 엔진 호출(_run_ocr_on_image)을 스텁으로
대체(tests/test_document_vision_extractor.py가 쓰던 _call_gemini_vision 스텁 패턴과
동일한 자리를 대신한다)."""
import io

import pytest
from PIL import Image

import db.document_ocr_extractor as ocr_mod
from db.document_text_extractor import DocumentParseError
from db.document_ocr_extractor import (
    OcrEngineError,
    _cluster_rows,
    _is_heic,
    _is_webp,
    ocr_extract,
    rasterize_to_images,
)


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


# ── ocr_extract (엔진 스텁) ───────────────────────────────────────────────────

def test_ocr_extract_reconstructs_linear_text_and_rows(monkeypatch):
    def _fake_run(image):
        rows = [[(0.0, 80.0, "청구월: 2025-06")], [(0.0, 120.0, "청구금액(원) 987,654")]]
        return rows, [0.95, 0.9]

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object()])

    result = ocr_extract(b"irrelevant since rasterize is stubbed")
    assert "청구월: 2025-06" in result.text
    assert "청구금액(원) 987,654" in result.text
    assert result.confidence == pytest.approx(0.925)
    assert len(result.rows) == 2


def test_ocr_extract_multi_page_concatenates_rows(monkeypatch):
    calls = {"n": 0}

    def _fake_run(image):
        calls["n"] += 1
        return [[(0.0, 10.0, f"page{calls['n']}")]], [0.8]

    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", _fake_run)
    monkeypatch.setattr(ocr_mod, "rasterize_to_images", lambda b: [object(), object()])

    result = ocr_extract(b"irrelevant")
    assert calls["n"] == 2
    assert "page1" in result.text and "page2" in result.text


def test_ocr_extract_no_text_found_raises(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_run_ocr_on_image", lambda image: ([], []))
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
    assert captured.get("lang") == "korean"
    assert captured.get("use_textline_orientation") is False
    assert captured.get("use_doc_orientation_classify") is False
    ocr_mod._ocr_engine = None  # 다른 테스트에 영향 안 주게 정리
