"""탄소중립포인트 참여신청서 hwp 서식 → 오버레이용 템플릿 PDF (1회성 오프라인 변환).

왜 이 스크립트가 있나 — 신청서 초안 다운로드는 **정부 고시 양식 위에 값만 얹는다**
(`db/reports/cnp_application_pdf.py`). reportlab으로 서식을 다시 그리면 실물과 다르게
생긴 서류를 사장님이 관공서에 내게 되므로, 원본 서식 자체를 PDF로 확보해야 한다.

런타임에는 절대 돌지 않는다. 결과물(`data/forms/*.pdf`)을 리포에 커밋하고 서버는 그
파일만 읽는다 — 그래서 아래 외부 도구(pyhwp·LibreOffice)는 `requirements.txt`에 넣지
않는다. 서식이 개정될 때만 사람이 다시 돌린다.

    python3 -m venv /tmp/hwpvenv
    /tmp/hwpvenv/bin/pip install pyhwp six
    PYHWP_BIN=/tmp/hwpvenv/bin .venv/bin/python scripts/build_cnp_form_template.py

원본 hwp도 산출물과 같이 `data/forms/`에 커밋한다 — 서식이 개정되면 무엇으로부터 뜬
PDF인지 대조할 수 있어야 하고, 그게 없으면 이 스크립트를 다시 돌릴 수도 없다.
`FONT_MAP`이 참조하는 폰트(Nanum Myeongjo·Nanum Gothic)가 변환하는 머신에 깔려 있어야 한다.

## LibreOffice 변환을 그대로 쓰지 못하는 이유 (2026-08-26 실측)

`hwp5odt`가 만든 ODT를 그냥 변환하면 1쪽짜리 신청서가 **2쪽으로 넘친다**. 원인 둘을
여기서 되돌린다.

1. **표 열 너비가 사라진다.** hwp5odt는 `<table:table-column
   number-columns-repeated="13"/>`만 남겨서 LibreOffice가 13열을 균등 분할한다. 그러면
   라벨 열이 원본보다 훨씬 좁아져 "상 호*(법인사업자는 법인명)"이 5줄로 접히고 행 높이가
   부풀어 오른다. 다행히 hwp 바이너리의 `TableCell`에 `col/colspan/width`가 그대로 있어
   열 너비를 **정확히 복원**할 수 있다(연립식을 풀면 합이 표 너비와 일치한다).
2. **본문 폰트가 하나도 안 깔려 있다.** 서식은 `문체부 바탕체`·`HY견고딕` 등을 쓰는데
   설치돼 있지 않아 LibreOffice가 임의 대체 폰트를 잡고, 그게 원본보다 넓고 두껍다.
   `FONT_MAP`으로 계열이 같은(명조→명조, 고딕→고딕) 설치 폰트로 명시 매핑한다.

3. **대체 폰트가 원본보다 크다.** 1·2를 고쳐도 신청서 마지막 서명란이 다음 쪽으로 밀렸다.
   `FONT_SCALE`로 본문 글자를 조금 줄여 해결한다. 원본이 쓰는 함초롬바탕이 Nanum
   Myeongjo보다 좁으니 축소는 원본 지면 밀도에 가까워지는 방향이기도 하다.

**행 높이는 강제하지 않는다.** 두 방법을 다 시도해 봤고 둘 다 더 나빴다.
`style:row-height`(고정)는 1쪽에 넣어주지만 글자를 **잘라낸다** — 실측에서
"(상업시설/공공기관**/학교)**", "상 호*(법인사업자는 **법인명)**", 주소·인센티브 안내문구가
사라졌다. 서류에서 글자가 조용히 사라지는 건 받아들일 수 없다.
`style:min-row-height`(최소)는 동의서 쪽을 망친다 — 동의서 3쪽은 각각 높이 257~267mm짜리
**외곽 테두리 표 한 칸**으로 돼 있어서, 그 값을 최소 높이로 박으면 제목 문단과 합쳐져
쪽을 넘고 3쪽이 6쪽이 된다(실측 7쪽). 열 너비만 정확하면 행 높이는 내용이 알아서 정한다.

`FONT_SCALE`을 바꿨으면 반드시 렌더 이미지를 눈으로 확인한다. 쪽수 검사(4쪽)는 넘침만
잡고 잘림은 못 잡는다.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "forms"

# HWPUNIT = 1/7200 inch.
HWPUNIT_MM = 25.4 / 7200

# 서식이 요구하는 한글 폰트 → 이 머신에 설치된 같은 계열 폰트. 계열을 지키는 게 중요하다
# (바탕/명조는 명조로, 고딕은 고딕으로) — 계열이 바뀌면 서식 인상이 달라진다.
FONT_MAP = {
    "문체부 바탕체": "Nanum Myeongjo",
    "한양신명조": "Nanum Myeongjo",
    "신명 신명조": "Nanum Myeongjo",
    "신명 세명조": "Nanum Myeongjo",
    "신명 태명조": "Nanum Myeongjo",
    "신명 견명조": "Nanum Myeongjo",
    "명조": "Nanum Myeongjo",
    "바탕": "Nanum Myeongjo",
    "HY견고딕": "Nanum Gothic",
    "한양중고딕": "Nanum Gothic",
    "08서울남산체 EB": "Nanum Gothic",
}

# 본문 글자 배율 — 위 3번 참고.
#
# 0.88에서 4쪽에 "겨우" 들어갔는데, 같은 입력으로 다시 돌리면 5쪽이 되기도 했다(실측) —
# LibreOffice 레이아웃이 폰트 캐시 상태에 따라 미세하게 달라지고, 서명란 한 줄이 그 차이로
# 다음 쪽에 떨어진다. 경계에 맞추지 않고 여유를 두려고 0.85로 내렸다. 페이지 여백도 함께
# 줄인다(아래) — 둘 다 같은 목적이고, 한쪽만으로는 여유가 한 줄 남짓이었다.
# 0.85로도 여유가 19.5pt뿐이었는데 마지막 행(선언문+서명란)이 **170pt짜리 한 덩이**라,
# 레이아웃이 20pt만 밀려도 그 덩이가 통째로 다음 쪽으로 넘어간다(4쪽/5쪽이 오락가락한 이유).
# 0.82로 내려 여유를 한 행 높이보다 크게 잡는다.
FONT_SCALE = 0.82

# 페이지 여백(cm). hwp5odt는 사방 1cm로 내보낸다 — 서식 표는 그대로 두고 여백만 줄여
# 세로 여유를 확보한다.
PAGE_MARGIN_CM = 0.7

# (입력 hwp 파일명, 출력 PDF 이름, 기대 쪽수)
#
# 가구용 서식(`1.…가구참여신청서서식.hwp`)은 **여기 없다.** application_type='household'
# 분기가 구현돼 있지 않아(data-plan §7.3) 쓰는 코드가 없고, 실제로 떠 보니 쪽수가 실행마다
# 흔들려서(3~4쪽) 검증되지 않은 PDF를 리포에 남기게 된다. 원본 hwp는 `data/forms/`에
# 커밋해 뒀으니, 가구용을 다루게 되면 여기 한 줄 추가하고 기대 쪽수를 확인하면 된다.
FORMS = (
    ("2.탄소중립포인트(에너지분야)사업자참여신청서서식.hwp", "cnp_business_application.pdf", 4),
)

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}


def q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


# ---------------------------------------------------------------- hwp geometry


def solve_spans(constraints: list[tuple[int, int, int]], n: int) -> list[int]:
    """`(시작 인덱스, 병합 개수, 합계)` 제약들에서 개별 크기 n개를 복원한다.

    표 셀은 병합(colspan/rowspan) 때문에 개별 열 너비를 직접 안 준다. 병합이 1인 셀에서
    확정값을 먼저 얻고, 미지수가 하나만 남은 제약을 반복 대입해 나머지를 채운다 —
    서식 표는 병합이 격자에 정렬돼 있어 이 방식으로 전부 풀린다(실측 14개 표 전부 성공).
    풀리지 않으면 None이 남고 호출부가 예외로 세운다(조용히 추정값을 넣지 않는다).
    """
    out: list[int | None] = [None] * n
    for start, span, size in constraints:
        if span == 1 and out[start] is None:
            out[start] = size
    for _ in range(n + 2):
        for start, span, size in constraints:
            idx = range(start, start + span)
            unknown = [i for i in idx if out[i] is None]
            if len(unknown) == 1:
                out[unknown[0]] = size - sum(out[i] for i in idx if out[i] is not None)
    return out  # type: ignore[return-value]


def read_hwp_geometry(hwp_xml: Path) -> list[dict]:
    """`hwp5proc xml` 출력에서 표별 열 너비·행 높이를 뽑는다(문서 순서).

    `findall("TableRow/TableCell")`로 **직계 셀만** 본다 — `iter()`를 쓰면 셀 안에 중첩된
    표의 셀까지 섞여 들어와 격자 인덱스가 깨진다(중첩 표는 별도 TableControl로 따로 잡힌다).
    """
    root = ET.parse(hwp_xml).getroot()
    tables = []
    for tc in root.iter("TableControl"):
        body = tc.find("TableBody")
        assert body is not None
        cols, rows = int(body.get("cols")), int(body.get("rows"))
        cells = [
            (
                int(c.get("col")), int(c.get("colspan")), int(c.get("width")),
                int(c.get("row")), int(c.get("rowspan")), int(c.get("height")),
            )
            for c in body.findall("TableRow/TableCell")
        ]
        col_w = solve_spans([(c, cs, w) for c, cs, w, _, _, _ in cells], cols)
        row_h = solve_spans([(r, rs, h) for _, _, _, r, rs, h in cells], rows)
        if None in col_w or None in row_h:
            raise SystemExit(
                f"표 기하 복원 실패: {cols}x{rows} — 열 {col_w}, 행 {row_h}\n"
                "병합 구조가 예상과 달라 열 너비를 추정할 수 없다. 서식이 개정됐다면 "
                "solve_spans를 손봐야 한다."
            )
        tables.append({"cols": cols, "rows": rows, "col_w": col_w, "row_h": row_h})
    return tables


# ------------------------------------------------------------------ odt patch


def patch_odt(odt_path: Path, geometry: list[dict], out_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        with zipfile.ZipFile(odt_path) as z:
            z.extractall(work)

        content = work / "content.xml"
        raw = content.read_text(encoding="utf-8")
        # ET는 등록되지 않은 접두사를 ns0, ns1…로 바꿔 쓴다. 원본 선언을 그대로
        # 등록해 접두사를 보존한다(LibreOffice가 읽는 데 문제는 없지만 diff가 읽히지 않는다).
        for prefix, uri in re.findall(r'xmlns:([\w-]+)="([^"]+)"', raw):
            ET.register_namespace(prefix, uri)

        tree = ET.parse(content)
        root = tree.getroot()
        auto = root.find(q("office", "automatic-styles"))
        assert auto is not None

        # 문서 순서(트리 순서)로 짝짓는다 — content.xml과 hwp XML은 같은 문서의 두 표현이라
        # 중첩 표까지 순서가 일치한다(실측: 14개 표, 너비도 mm 단위로 일치).
        odt_tables = list(root.iter(q("table", "table")))
        if len(odt_tables) != len(geometry):
            raise SystemExit(f"표 개수 불일치: odt {len(odt_tables)} vs hwp {len(geometry)}")

        for ti, (tbl, geo) in enumerate(zip(odt_tables, geometry), start=1):
            for old in tbl.findall(q("table", "table-column")):
                tbl.remove(old)
            # 열 선언은 표의 첫 자식이어야 한다(ODF 스키마).
            for ci, width in reversed(list(enumerate(geo["col_w"], start=1))):
                name = f"GTcol{ti}-{ci}"
                _add_style(auto, name, "table-column", "table-column-properties",
                           {q("style", "column-width"): f"{width * HWPUNIT_MM:.3f}mm"})
                col = ET.Element(q("table", "table-column"))
                col.set(q("table", "style-name"), name)
                tbl.insert(0, col)

            # 행 높이는 손대지 않는다 — 모듈 주석 3번. 개수만 맞춰보고 넘어간다(content.xml과
            # hwp XML의 표가 같은 순서로 짝지어졌는지 확인하는 값싼 검사).
            rows = tbl.findall(q("table", "table-row"))
            if len(rows) != geo["rows"]:
                raise SystemExit(f"표 {ti} 행 개수 불일치: odt {len(rows)} vs hwp {geo['rows']}")

        tree.write(content, encoding="utf-8", xml_declaration=True)

        for name in ("content.xml", "styles.xml"):
            path = work / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for src, dst in FONT_MAP.items():
                text = text.replace(f'"{src}"', f'"{dst}"')
            text = _scale_fonts(text)
            if path.name == "styles.xml":
                text = re.sub(r'fo:margin-(top|left|right|bottom)="[\d.]+cm"',
                              lambda m: f'fo:margin-{m.group(1)}="{PAGE_MARGIN_CM}cm"', text)
            path.write_text(text, encoding="utf-8")

        _rezip(work, out_path)


def _scale_fonts(text: str) -> str:
    """`fo:font-size="9pt"` 류를 FONT_SCALE배로 줄인다. %로 지정된 값은 건드리지 않는다."""
    if FONT_SCALE == 1.0:
        return text

    def repl(m: re.Match) -> str:
        return f'{m.group(1)}="{float(m.group(2)) * FONT_SCALE:.2f}pt"'

    return re.sub(r'(fo:font-size|style:font-size-asian|style:font-size-complex)'
                  r'="([\d.]+)pt"', repl, text)


def _add_style(auto: ET.Element, name: str, family: str, props_tag: str,
               props: dict[str, str]) -> None:
    style = ET.SubElement(auto, q("style", "style"))
    style.set(q("style", "name"), name)
    style.set(q("style", "family"), family)
    ET.SubElement(style, q("style", props_tag)).attrib.update(props)


def _rezip(work: Path, out_path: Path) -> None:
    """ODF는 mimetype이 첫 엔트리·무압축이어야 한다."""
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(work / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(work.rglob("*")):
            rel = path.relative_to(work).as_posix()
            if path.is_file() and rel != "mimetype":
                z.write(path, rel)


# ----------------------------------------------------------------- pipeline


def run(cmd: list[str], **kw) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        raise SystemExit(f"실패: {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")


def build(hwp: Path, out_pdf: Path, expected_pages: int | None,
          pyhwp_bin: Path, soffice: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        hwp_xml, odt, patched = work / "src.xml", work / "src.odt", work / "patched.odt"

        with hwp_xml.open("w", encoding="utf-8") as fh:
            proc = subprocess.run([str(pyhwp_bin / "hwp5proc"), "xml", str(hwp)],
                                  stdout=fh, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"hwp5proc 실패: {proc.stderr}")
        run([str(pyhwp_bin / "hwp5odt"), "--output", str(odt), str(hwp)])

        geometry = read_hwp_geometry(hwp_xml)
        patch_odt(odt, geometry, patched)
        # `-env:UserInstallation`으로 실행마다 새 프로필을 쓴다. 이게 없으면 이미 떠 있는
        # soffice 프로세스에 변환을 위임하게 되고, 그 프로세스의 폰트 캐시 상태에 따라
        # 같은 입력이 4쪽/5쪽으로 갈렸다(실측 — 연속 실행 시 재현). 서식을 두 개 연달아
        # 변환하는 이 스크립트에서는 특히 잘 걸린다.
        run([soffice, f"-env:UserInstallation=file://{work / 'loprofile'}",
             "--headless", "--convert-to", "pdf", "--outdir", str(work), str(patched)])

        produced = work / "patched.pdf"
        if not produced.exists():
            raise SystemExit("LibreOffice가 PDF를 만들지 못했다")

        dropped = _drop_blank_pages(produced)
        pages = _page_count(produced)
        # 쪽수가 어긋난 산출물은 **커밋 위치에 쓰지 않는다.** 신청서가 2쪽으로 넘치면
        # 오버레이 좌표를 잡는 1쪽에서 서명란이 사라지고, 그건 PDF만 봐서는 티가 안 난다.
        if expected_pages is not None and pages != expected_pages:
            raise SystemExit(
                f"  ✗ {pages}쪽이 나왔다(기대 {expected_pages}쪽) — 기존 파일을 유지한다.\n"
                f"  FONT_SCALE({FONT_SCALE})을 조금 낮추고 다시 돌린 뒤 렌더를 눈으로 확인할 것."
            )
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(produced, out_pdf)

    if dropped:
        print(f"  빈 쪽 {dropped}개 제거 (표 뒤에 남은 빈 문단)")
    tail = "" if expected_pages is None else f" (기대 {expected_pages})"
    print(f"  → {out_pdf.relative_to(REPO_ROOT)}  {pages}쪽{tail}  표 {len(geometry)}개")


def _page_count(pdf: Path) -> int:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return doc.page_count


def _drop_blank_pages(pdf: Path) -> int:
    """완전히 빈 쪽을 지운다.

    hwp 본문은 표 뒤에 빈 문단이 몇 개 남아 있고, 축소된 글자 크기와 맞물리면 그게 빈 5쪽을
    만든다. 서식은 4쪽이므로 서명란만 있는 빈 장을 사장님에게 인쇄시키지 않는다.
    글자·도형·이미지가 하나라도 있으면 지우지 않는다 — 내용이 있는 쪽을 지울 위험을 없앤다.
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:
        blank = [
            i for i, page in enumerate(doc)
            if not page.get_text().strip()
            and not page.get_drawings()
            and not page.get_images()
        ]
        if not blank:
            return 0
        doc.delete_pages(blank)
        # 열어둔 파일에 곧바로 덮어쓸 수 없다(pymupdf가 incremental 저장만 허용) —
        # 옆에 쓰고 교체한다.
        tmp = pdf.with_name(pdf.name + ".tmp")
        doc.save(str(tmp), garbage=3, deflate=True)
    os.replace(tmp, pdf)
    return len(blank)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src-dir", type=Path, default=OUT_DIR,
                    help="hwp 원본 서식이 있는 디렉토리 (기본: data/forms)")
    ap.add_argument("--pyhwp-bin", type=Path,
                    default=Path(os.environ.get("PYHWP_BIN", "/tmp/hwpvenv/bin")),
                    help="hwp5odt·hwp5proc이 있는 디렉토리")
    ap.add_argument("--soffice", default=os.environ.get("SOFFICE_BIN", "soffice"))
    args = ap.parse_args()

    if not (args.pyhwp_bin / "hwp5odt").exists():
        raise SystemExit(
            f"pyhwp를 찾지 못했다: {args.pyhwp_bin}\n"
            "python3 -m venv /tmp/hwpvenv && /tmp/hwpvenv/bin/pip install pyhwp six"
        )
    for hwp_name, pdf_name, pages in FORMS:
        hwp = args.src_dir / hwp_name
        if not hwp.exists():
            print(f"  건너뜀 (원본 없음): {hwp_name}", file=sys.stderr)
            continue
        print(f"{hwp_name}")
        build(hwp, OUT_DIR / pdf_name, pages, args.pyhwp_bin, args.soffice)


if __name__ == "__main__":
    main()
