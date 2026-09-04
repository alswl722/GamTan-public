"""탄소중립포인트 사업자 참여신청서 초안 PDF — **실물 서식 위에 값만 얹는다**.

이 파일이 `db/reports/`의 다른 3종(owner·audit·climate_risk)과 다른 이유: 저쪽은 우리가
만든 보고서라 reportlab으로 처음부터 그리지만, 이건 **정부 고시 양식**이다. 서식을 다시
그리면 실물과 다르게 생긴 서류를 사장님이 관공서에 내게 된다. 그래서 원본 hwp를 그대로
PDF로 뜬 템플릿(`data/forms/cnp_business_application.pdf`,
`scripts/build_cnp_form_template.py`가 만든다)을 열어 빈칸에만 글자를 찍는다.

pymupdf를 쓰고 reportlab을 쓰지 않는다 — 여기서 필요한 건 "기존 PDF 페이지에 찍기"이고,
pymupdf 내장 CJK 폰트(Droid Sans Fallback)가 한글 글리프를 갖고 있으면서 **PDF에 임베드**
된다. reportlab의 `UnicodeCIDFont("HYGothic-Medium")`는 폰트를 임베드하지 않고 뷰어가
갖고 있길 기대하는데, 관공서에 내는 서류가 여는 사람 환경에 따라 빈칸으로 보일 수 있는 건
피해야 한다(다른 3종은 화면에서 바로 확인하는 내부 리포트라 그 위험을 감수했다).

## 좌표를 파일에 박아두지 않는 이유

칸 위치를 상수로 커밋하면, 템플릿을 다시 뜰 때(서식 개정·폰트 배율 조정) 글자가 **엉뚱한
칸에 조용히 찍힌다** — 검증 없이는 아무도 모르는 실패다. 그래서 매번 템플릿 PDF에서
표 격자와 라벨 텍스트를 찾아 좌표를 **유도**한다(`_layout()`, 프로세스당 1회 캐시).
라벨을 못 찾으면 `FormLayoutError`로 즉시 터진다 — 빈 서식을 내려주는 대신 실패를
드러낸다(CLAUDE.md §6).

## 서식에 칸이 없어 인쇄하지 않는 값

- `account_holder`(예금주) — 서식 금융정보란은 은행 명칭·계좌번호 두 칸뿐이다. 우리가
  값을 갖고 있어도 인쇄할 자리가 없다. 없는 칸을 만들어 적지 않는다.
- 비밀번호 — 애초에 저장하지 않는다(`alembic/versions/0032_*.py` 참고).
- 거주 면적·세대원 수·전입일자 — `BLANK_BY_POLICY`. 상업시설 신청에 해당 없다.
- 신청 연월일·신청인 서명·관할 지자체("( ) 시장·군수·구청장 귀하") — 사장님이 인쇄한 뒤
  손으로 쓴다. 서명은 대신 할 수 없고, 날짜는 실제 제출일이어야 하며(초안 생성일이 아니다),
  관할 지자체는 주소에서 추론할 수 있어 보이지만 그건 우리 추측이다.
- 2~4쪽 개인정보 제공·활용 동의서 — 동의 여부는 본인이 표시해야 한다. 우리가 동의 칸을
  미리 체크해 두면 사장님이 하지 않은 의사표시를 대신 한 셈이 된다. 쪽은 그대로 붙여
  내려준다(4쪽 한 세트로 제출하는 서식이다).
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pymupdf

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "forms"
    / "cnp_business_application.pdf"
)

# 신청서는 1쪽. 2~4쪽은 개인정보 동의서라 손대지 않는다(모듈 주석 참고).
FORM_PAGE = 0

# 오버레이 글자 폰트 — pymupdf 내장 CJK 폰트(Droid Sans Fallback). 한글 글리프가 있고
# PDF에 서브셋으로 임베드된다.
#
# ⚠️ **폰트를 바꾸려면 반드시 렌더 이미지를 눈으로 확인할 것.** 서식 본문이 명조 계열이라
# 고딕인 이 폰트가 값만 다른 글씨체로 보이는 건 사실이고(2026-08-26 사용자 지적), 그래서
# 리포에 이미 있던 마루부리(`web/public/MaruBuri-Light.otf`)로 바꿔봤다 — **한글이 통째로
# 깨졌다**: "동성로카페" → "돎섬례칯펏", "김대표" → "긴닿꽉". 그 OTF의 글리프 매핑을
# pymupdf TextWriter가 잘못 집는다(라틴·숫자는 정상).
#
# 이 실패가 무서운 이유는 **자동 검사로 안 잡힌다**는 점이다. `Font.has_glyph()`는 전부
# True였고, PDF 텍스트 레이어도 "동성로카페"로 정상 추출됐다(즉 좌표 검사·문자열 검사
# 테스트가 다 통과한다). 화면에 보이는 글자만 틀렸다. 폰트 교체는 렌더를 눈으로 보는
# 절차 없이는 하지 말 것.
#
# 명조로 맞추려면 pymupdf에서 정상 동작하는 한글 명조 TTF를 리포에 들여와야 한다(나눔명조
# 등). 서식 자체의 글씨체 한계는 `scripts/build_cnp_form_template.py`의 FONT_MAP 주석 참고.
_FONT = "cjk"
_SIZE = 9.0            # 서식 본문과 비슷한 크기
_MIN_SIZE = 6.0        # 이보다 작아지면 읽기 어렵다 — 줄이는 대신 넘치게 둔다
_PAD = 4.0             # 칸 안쪽 좌우 여백
_EDGE_GAP = 1.0        # 칸 윗변·기준 텍스트와의 간격


class FormLayoutError(RuntimeError):
    """서식 템플릿에서 칸을 찾지 못했다 — 템플릿과 이 파일의 앵커가 어긋난 상태."""


@dataclass(frozen=True)
class TextSlot:
    """라벨 칸을 찾아 그 옆(또는 아래) 칸에 값을 쓰는 슬롯.

    `anchor`는 서식에 인쇄된 라벨이다. 공백을 지운 상태로 **칸 텍스트의 앞부분**과
    비교하며, 후보가 2개 이상이면 예외를 낸다 — 애매한 앵커를 조용히 첫 번째로 고르면
    서식이 개정될 때 엉뚱한 칸에 찍힌다.
    """

    key: str
    anchor: str
    direction: str = "right"     # right | below
    place: str = "center"        # center | top | below:<셀 안의 텍스트>
    clear_hint: bool = False     # 칸에 인쇄된 구분자 힌트("- - .")를 지우고 쓴다


@dataclass(frozen=True)
class ParenSlot:
    """`우편번호( )`처럼 **닫는 괄호 앞에** 값이 들어가는 칸.

    hwp에서 PDF로 오는 과정에서 괄호 사이 공백이 거의 0으로 붙어버려 사이에 글자를 넣을
    자리가 없다. 그래서 닫는 괄호를 덮고 `값 + )`를 다시 그린다 — 글리프를 지우는 게
    아니라 오른쪽으로 밀어 그리는 것이라 서식 내용은 그대로 남는다.
    """

    key: str
    open_text: str               # 여는 쪽 텍스트(예: "우편번호(")
    scope_anchor: str            # 이 라벨의 값 칸 안에서만 찾는다(칸 우변이 글자 폭 한계)


@dataclass(frozen=True)
class MarkSlot:
    """값에 따라 서식의 특정 글리프에 표시하는 슬롯."""

    key: str
    glyphs: dict[str, str]       # 저장값 -> 서식 글리프
    style: str                   # check(▢ 안에 체크) | circle(글자에 동그라미)
    scope_anchor: str | None = None
    scope_height: float | None = None   # 값 칸 상단에서 이 높이까지만 탐색


# 서식 1쪽의 칸 배치. 앵커 문구는 서식 원문 그대로다.
TEXT_SLOTS: tuple[TextSlot, ...] = (
    # 아이디는 라벨 칸 **아래**가 입력란이다(라벨 위, 입력 가운데, "변경불가" 안내 아래).
    TextSlot("portal_id", "아이디(ID)*", direction="below"),
    TextSlot("company_name", "상 호"),
    TextSlot("representative", "대표자 성명"),
    # 아래 3개는 칸에 "- - ." 같은 구분자 힌트가 인쇄돼 있다. hwp에서 변환될 때 자릿수
    # 칸이 무너져 힌트 사이에 숫자를 넣을 수 없으므로, 힌트를 덮고 완성된 값을 쓴다
    # (값 자체에 하이픈이 들어 있어 정보가 사라지지 않는다).
    TextSlot("business_registration_no", "사업자 등록번호", clear_hint=True),
    TextSlot("corporate_registration_no", "법인번호", clear_hint=True),
    TextSlot("applicant_phone", "신청인", clear_hint=True),
    # 주소 칸은 위에 "우편번호( )", 아래에 도로명주소 안내문구가 인쇄돼 있다. 둘 사이
    # 빈 띠에 주소를 쓴다 — 칸 가운데로 잡으면 안내문구와 겹칠 수 있다.
    TextSlot("address", "주 소", place="below:우편번호("),
    # 전자메일 칸도 아래쪽에 안내문구가 있어 위로 붙인다.
    TextSlot("applicant_email", "전자 메일", place="top"),
    TextSlot("bank_name", "은행 명칭"),
    TextSlot("account_number", "계좌번호"),
    TextSlot("electric_customer_number", "전 기"),
    TextSlot("water_customer_number", "수 도"),
    TextSlot("city_gas_customer_number", "도시가스"),
    TextSlot("district_heating_customer_number", "지역난방"),
    TextSlot("business_open_date", "영업개시일자"),
)

PAREN_SLOTS: tuple[ParenSlot, ...] = (
    ParenSlot("postal_code", "우편번호(", scope_anchor="주 소"),
    # ⑤기 타( ) 자유기재 — 인센티브 유형을 '기타'로 고른 경우에만 값이 있다.
    ParenSlot("incentive_type_other", "기 타", scope_anchor="인센티브 유형"),
)

MARK_SLOTS: tuple[MarkSlot, ...] = (
    # 서식 최상단 체크박스 2개(□가입신청 / □정보 변경신청) — 같은 글리프라 등장 순서로 가른다.
    MarkSlot("application_kind", {"new": "▢#0", "change": "▢#1"}, style="check"),
    # 서식 지시문이 "번호 위에 표시(∨ 또는 ○)"라 번호에 동그라미를 친다.
    # ④는 안내문구("④번 선택이 불가합니다")에도 나오므로 값 칸 상단 45pt로 탐색을 제한한다.
    MarkSlot(
        "incentive_type",
        {
            "gift_certificate": "①",
            "cash": "②",
            "cash_donation": "③",
            "green_card_point": "④",
            "other": "⑤",
        },
        style="circle",
        scope_anchor="인센티브 유형",
        scope_height=45.0,
    ),
)

# 슬롯이 소비하는 값 key 전체 — 호출부가 넘긴 dict에 오타가 있으면 조용히 빈칸이 되는
# 대신 드러내기 위해 쓴다.
SLOT_KEYS: frozenset[str] = frozenset(
    [s.key for s in TEXT_SLOTS] + [s.key for s in PAREN_SLOTS] + [s.key for s in MARK_SLOTS]
)


# --------------------------------------------------------------------- layout


def _norm(text: str) -> str:
    return "".join(text.split())


def _grid(page: pymupdf.Page) -> list[list[tuple[float, float, float, float] | None]]:
    # find_tables가 stdout으로 광고 문구를 찍는다("Consider using the pymupdf_layout
    # package…"). API 로그에 섞이면 곤란하니 이 호출 동안만 삼킨다.
    with contextlib.redirect_stdout(io.StringIO()):
        tables = page.find_tables().tables
    if not tables:
        raise FormLayoutError(f"{TEMPLATE_PATH.name} {FORM_PAGE + 1}쪽에서 표를 찾지 못했다")
    # 신청서 1쪽은 표 하나가 지면을 채운다 — 가장 넓은 것을 고른다.
    table = max(tables, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
    return [[tuple(c) if c is not None else None for c in row.cells] for row in table.rows]


def _anchor_cell(page: pymupdf.Page, grid, anchor: str) -> tuple[int, int]:
    want = _norm(anchor)
    hits = [
        (ri, ci)
        for ri, row in enumerate(grid)
        for ci, cell in enumerate(row)
        if cell is not None and _norm(page.get_textbox(pymupdf.Rect(cell))).startswith(want)
    ]
    if len(hits) != 1:
        raise FormLayoutError(
            f"서식 라벨 '{anchor}'이(가) {len(hits)}개 칸에 걸린다(1개여야 한다). "
            "템플릿을 다시 떴다면 앵커 문구를 서식 원문과 맞춰야 한다."
        )
    return hits[0]


def _value_cell(grid, ri: int, ci: int, direction: str) -> tuple[float, float, float, float]:
    if direction == "right":
        for c in range(ci + 1, len(grid[ri])):
            if grid[ri][c] is not None:
                return grid[ri][c]
    elif direction == "below":
        for r in range(ri + 1, len(grid)):
            if grid[r][ci] is not None:
                return grid[r][ci]
    else:
        raise ValueError(direction)
    raise FormLayoutError(f"라벨 칸 (r{ri},c{ci}) {direction} 방향에 값 칸이 없다")


def _search_one(page: pymupdf.Page, needle: str, clip=None) -> pymupdf.Rect:
    hits = page.search_for(needle, clip=clip)
    if len(hits) != 1:
        raise FormLayoutError(
            f"서식 글리프 '{needle}'을(를) {len(hits)}개 찾았다(1개여야 한다)"
        )
    return hits[0]


@lru_cache(maxsize=1)
def _layout() -> dict[str, tuple[float, float, float, float]]:
    """템플릿 PDF에서 모든 칸 좌표를 유도한다. 프로세스당 한 번만 돈다.

    반환 key 규약:
      `<slot key>`              TextSlot의 값 칸
      `band:<slot key>`         칸 안에서 값을 쓸 수 있는 빈 띠(안내문구가 인쇄된 칸)
      `<slot key>:paren`        ParenSlot이 덮어 쓸 닫는 괄호
      `<slot key>:cell`         ParenSlot이 속한 칸(글자 폭 한계)
      `<slot key>:<저장값>`     MarkSlot이 표시할 글리프
      `text:<앵커>`             `place="below:..."`가 기준으로 쓰는 셀 안 텍스트
    """
    if not TEMPLATE_PATH.exists():
        raise FormLayoutError(
            f"서식 템플릿이 없다: {TEMPLATE_PATH}\n"
            "scripts/build_cnp_form_template.py로 hwp 서식에서 만든 뒤 커밋해야 한다."
        )
    out: dict[str, tuple[float, float, float, float]] = {}
    with pymupdf.open(TEMPLATE_PATH) as doc:
        page = doc[FORM_PAGE]
        grid = _grid(page)

        for slot in TEXT_SLOTS:
            ri, ci = _anchor_cell(page, grid, slot.anchor)
            cell = _value_cell(grid, ri, ci, slot.direction)
            out[slot.key] = cell
            if slot.place == "center":
                continue
            # 칸에 안내문구가 인쇄돼 있는 슬롯 — 값을 쓸 수 있는 **빈 띠**를 계산해 둔다.
            # 칸 높이를 그대로 쓰면 안내문구 위에 겹쳐 찍혀 둘 다 못 읽는다(실측).
            top = cell[1]
            if slot.place.startswith("below:"):
                needle = slot.place.split(":", 1)[1]
                anchor_rect = _search_one(page, needle, clip=pymupdf.Rect(cell))
                out[f"text:{needle}"] = tuple(anchor_rect)
                top = anchor_rect.y1
            below = [w[1] for w in page.get_text("words", clip=pymupdf.Rect(cell))
                     if w[1] > top + 0.5]
            out[f"band:{slot.key}"] = (cell[0], top, cell[2], min(below) if below else cell[3])

        for slot in PAREN_SLOTS:
            ri, ci = _anchor_cell(page, grid, slot.scope_anchor)
            clip = pymupdf.Rect(_value_cell(grid, ri, ci, "right"))
            out[f"{slot.key}:cell"] = tuple(clip)
            opener = _search_one(page, slot.open_text, clip=clip)
            # 여는 텍스트 바로 오른쪽·같은 줄의 ')'.
            closers = [
                r for r in page.search_for(")", clip=clip)
                if r.x0 >= opener.x1 - 1 and abs(r.y0 - opener.y0) < 3 and r.x0 - opener.x1 < 12
            ]
            if len(closers) != 1:
                raise FormLayoutError(
                    f"'{slot.open_text}' 뒤의 닫는 괄호를 {len(closers)}개 찾았다(1개여야 한다)"
                )
            out[f"{slot.key}:paren"] = tuple(closers[0])

        for slot in MARK_SLOTS:
            clip = None
            if slot.scope_anchor:
                ri, ci = _anchor_cell(page, grid, slot.scope_anchor)
                cell = pymupdf.Rect(_value_cell(grid, ri, ci, "right"))
                if slot.scope_height is not None:
                    cell.y1 = cell.y0 + slot.scope_height
                clip = cell
            for value, glyph in slot.glyphs.items():
                if "#" in glyph:
                    needle, index = glyph.split("#")
                    hits = sorted(page.search_for(needle, clip=clip),
                                  key=lambda r: (round(r.y0, 1), r.x0))
                    if len(hits) <= int(index):
                        raise FormLayoutError(
                            f"글리프 '{needle}'을 {len(hits)}개만 찾았다 "
                            f"(#{index}가 필요하다)"
                        )
                    out[f"{slot.key}:{value}"] = tuple(hits[int(index)])
                else:
                    out[f"{slot.key}:{value}"] = tuple(_search_one(page, glyph, clip=clip))
    return out


def verify_layout() -> dict[str, tuple[float, float, float, float]]:
    """템플릿에서 모든 칸이 잡히는지 확인한다(테스트·수동 점검용). 실패 시 예외."""
    return dict(_layout())


# --------------------------------------------------------------------- drawing


def _fit_size(font: pymupdf.Font, text: str, width: float) -> float:
    size = _SIZE
    while size > _MIN_SIZE and font.text_length(text, size) > width:
        size -= 0.25
    return size


def _draw_text(page: pymupdf.Page, writer: pymupdf.TextWriter, font: pymupdf.Font,
               rect: pymupdf.Rect, text: str, slot: TextSlot, layout) -> None:
    if slot.clear_hint:
        # 이 칸에 인쇄된 힌트 글리프만 덮는다 — 칸 전체를 덮으면 테두리가 지워진다.
        for word in page.get_text("words", clip=rect):
            box = pymupdf.Rect(word[:4])
            page.draw_rect(box + (-1, -1, 1, 1), color=None, fill=(1, 1, 1))

    size = _fit_size(font, text, rect.width - 2 * _PAD)
    # 글자 높이는 폰트 실측값으로 잡는다. `size`를 어센더로 쓰면 안 된다 — Droid Sans
    # Fallback의 어센더가 1em을 넘어(1.04em) 글자 윗변이 칸 위로 삐져나간다(테스트가 잡음).
    line = font.ascender - font.descender

    if slot.place == "center":
        baseline = (rect.y0 + rect.y1) / 2 + (font.ascender + font.descender) * size / 2
    else:
        # 안내문구가 인쇄된 칸 — `_layout()`이 계산해 둔 빈 띠 안에 넣는다. 띠가 좁으면
        # 글자를 줄여서라도 겹치지 않게 한다(겹치면 값도 안내문구도 못 읽는다).
        band = pymupdf.Rect(layout[f"band:{slot.key}"])
        usable = band.height - 2 * _EDGE_GAP
        size = min(size, max(_MIN_SIZE, usable / line))
        baseline = band.y0 + (band.height - line * size) / 2 + font.ascender * size
    writer.append((rect.x0 + _PAD, baseline), text, font=font, fontsize=size)


def _draw_paren_value(page: pymupdf.Page, writer: pymupdf.TextWriter, font: pymupdf.Font,
                      paren: pymupdf.Rect, cell: pymupdf.Rect, text: str) -> None:
    """닫는 괄호를 덮고 `값 + )`을 그 자리에서 다시 그린다.

    `cell`은 이 괄호가 속한 칸이다 — 자유기재 항목(`incentive_type_other`, String(100))이
    길면 칸을 넘어 지면 밖까지 흘러가므로 칸 우변까지로 폭을 제한한다.
    """
    page.draw_rect(paren + (-0.5, -0.5, 0.5, 0.5), color=None, fill=(1, 1, 1))
    body = f"{text})"
    size = _fit_size(font, body, cell.x1 - paren.x0 - _PAD)
    writer.append((paren.x0, paren.y1 - 2), body, font=font, fontsize=size)


def _draw_check(page: pymupdf.Page, box: pymupdf.Rect) -> None:
    """□ 안에 체크. 글리프 대신 선으로 그린다 — 폰트에 ∨가 있는지에 의존하지 않는다."""
    inner = box + (box.width * 0.22, box.height * 0.3, -box.width * 0.22, -box.height * 0.28)
    mid = (inner.x0 + inner.x1) / 2
    page.draw_line((inner.x0, inner.y0 + inner.height * 0.45),
                   (mid, inner.y1), color=(0, 0, 0), width=1.1)
    page.draw_line((mid, inner.y1), (inner.x1, inner.y0), color=(0, 0, 0), width=1.1)


def _draw_circle(page: pymupdf.Page, glyph: pymupdf.Rect) -> None:
    """서식 지시대로 번호에 동그라미를 친다."""
    page.draw_oval(glyph + (-1.2, -1.0, 1.2, 1.0), color=(0, 0, 0), width=1.0)


def build_application_draft_pdf(values: dict[str, str | None]) -> bytes:
    """신청서 초안 PDF 바이트. `values`는 슬롯 key → 값(없으면 None).

    빈 값은 **빈칸으로 남긴다** — "미입력"이라고 적거나 그럴싸한 값을 채우지 않는다.
    필수 항목이 비어도 만들어 준다(사장님이 인쇄해서 손으로 채울 수 있어야 하고, 어떤
    칸이 비었는지는 화면이 `missing_required`로 이미 알려준다).
    """
    unknown = sorted(set(values) - SLOT_KEYS)
    if unknown:
        raise ValueError(f"서식에 없는 값 key: {', '.join(unknown)}")

    layout = _layout()
    font = pymupdf.Font(_FONT)
    with pymupdf.open(TEMPLATE_PATH) as doc:
        page = doc[FORM_PAGE]
        # TextWriter를 쓰는 이유: `page.insert_text`는 내장 CJK 별칭을 폰트 파일 없이
        # 받아주지 않는다. TextWriter는 Font 글리프를 **서브셋으로 임베드**해서, 여는 사람
        # 환경에 한글 폰트가 없어도 그대로 보인다(관공서에 내는 서류라 뷰어에 기대면 안 된다).
        writer = pymupdf.TextWriter(page.rect, color=(0, 0, 0))

        for slot in TEXT_SLOTS:
            text = (values.get(slot.key) or "").strip()
            if text:
                _draw_text(page, writer, font, pymupdf.Rect(layout[slot.key]),
                           text, slot, layout)

        for slot in PAREN_SLOTS:
            text = (values.get(slot.key) or "").strip()
            if text:
                _draw_paren_value(page, writer, font,
                                  pymupdf.Rect(layout[f"{slot.key}:paren"]),
                                  pymupdf.Rect(layout[f"{slot.key}:cell"]), text)

        for slot in MARK_SLOTS:
            value = (values.get(slot.key) or "").strip()
            if not value:
                continue
            rect = layout.get(f"{slot.key}:{value}")
            if rect is None:
                # 어휘 밖의 값 — DB CHECK가 막고 있으니 여기까지 오면 서식·어휘가 어긋난
                # 상태다. 조용히 표시를 빼먹지 않는다.
                raise ValueError(f"{slot.key}에 서식 대응이 없는 값: {value}")
            if slot.style == "check":
                _draw_check(page, pymupdf.Rect(rect))
            else:
                _draw_circle(page, pymupdf.Rect(rect))

        writer.write_text(page)
        buf = io.BytesIO()
        doc.save(buf, garbage=3, deflate=True)
    return buf.getvalue()
