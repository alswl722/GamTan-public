"""신청서 초안 PDF — 값이 **올바른 칸에** 찍히는지 잠근다.

이 파일의 존재 이유: 오버레이 방식의 고유한 실패는 "PDF는 멀쩡히 만들어졌는데 글자가
엉뚱한 칸에 있다"이고, 그건 예외를 던지지 않아 아무도 모른 채 관공서까지 간다. 서식
템플릿을 다시 뜨면(`scripts/build_cnp_form_template.py`, 폰트 배율·서식 개정) 좌표가
움직이므로, 여기서 **찍힌 글자의 위치가 그 칸 안에 있는지**를 검사한다.

`db/reports/cnp_application_pdf.py`는 좌표를 상수로 들고 있지 않고 템플릿에서 유도하므로,
템플릿이 바뀌면 이 테스트가 (a) 앵커를 못 찾아 FormLayoutError로 터지거나 (b) 위치 검사에서
떨어진다. 둘 다 조용한 실패보다 낫다.
"""
import pymupdf
import pytest

from db.reports.cnp_application_pdf import (
    FORM_PAGE,
    MARK_SLOTS,
    SLOT_KEYS,
    TEMPLATE_PATH,
    TEXT_SLOTS,
    build_application_draft_pdf,
    verify_layout,
)

# 사장님 한 명이 다 채운 상태 — 서식의 모든 텍스트 칸을 덮는다.
FULL_VALUES = {
    "application_kind": "new",
    "portal_id": "dongsungro01",
    "company_name": "동성로카페",
    "representative": "김대표",
    "business_registration_no": "211-81-10011",
    "corporate_registration_no": "110111-1234567",
    "applicant_phone": "010-1234-5678",
    "postal_code": "41911",
    "address": "대구광역시 중구 동성로 11 2층",
    "applicant_email": "owner@dongsungro.test",
    "incentive_type": "cash",
    "incentive_type_other": None,
    "bank_name": "iM뱅크",
    "account_number": "1234567890",
    "electric_customer_number": "0355771290",
    "water_customer_number": "W12345678",
    "city_gas_customer_number": "G87654321",
    "district_heating_customer_number": "H11223344",
    "business_open_date": "2019-03-15",
}


def _word_rect(page: pymupdf.Page, needle: str) -> pymupdf.Rect:
    hits = [w for w in page.get_text("words") if needle in w[4]]
    assert len(hits) == 1, f"'{needle}'을 {len(hits)}개 찾았다(1개여야 한다)"
    return pymupdf.Rect(hits[0][:4])


def test_template_is_committed():
    """템플릿 PDF는 리포에 커밋돼 있어야 한다 — 런타임에 hwp를 변환하지 않는다."""
    assert TEMPLATE_PATH.exists(), TEMPLATE_PATH
    with pymupdf.open(TEMPLATE_PATH) as doc:
        assert doc.page_count == 4


def test_layout_resolves_every_slot():
    """모든 칸이 템플릿에서 잡힌다 — 앵커 문구가 서식과 어긋나면 여기서 터진다."""
    layout = verify_layout()
    for slot in TEXT_SLOTS:
        assert slot.key in layout, slot.key
    for slot in MARK_SLOTS:
        for value in slot.glyphs:
            assert f"{slot.key}:{value}" in layout, f"{slot.key}:{value}"


def test_values_land_in_their_own_cell():
    """찍힌 값이 그 칸 사각형 안에 있다 — 오버레이의 유일한 조용한 실패를 잡는 검사."""
    layout = verify_layout()
    pdf = build_application_draft_pdf(FULL_VALUES)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[FORM_PAGE]
        for slot in TEXT_SLOTS:
            value = FULL_VALUES[slot.key]
            if not value:
                continue
            # 값의 첫 토큰으로 찾는다(주소처럼 공백이 있는 값은 여러 단어로 쪼개진다).
            rect = _word_rect(page, value.split()[0])
            cell = pymupdf.Rect(layout[slot.key])
            assert cell.contains(rect), (
                f"{slot.key}: 값이 칸 밖에 찍혔다 — 글자 {rect}, 칸 {cell}"
            )


def test_values_do_not_collide_with_printed_form_text():
    """찍은 값이 서식에 인쇄된 글자와 겹치지 않는다.

    칸 안에 들어갔더라도 그 칸에 이미 안내문구가 인쇄돼 있으면 글자가 서로 겹쳐 둘 다
    못 읽게 된다(실제로 전자메일 칸에서 한 번 그랬다). `clear_hint` 칸은 예외다 —
    거기 인쇄된 건 "- - ." 같은 구분자 힌트고, 우리가 덮고 완성된 값을 다시 쓴다.
    """
    layout = verify_layout()
    cleared = [pymupdf.Rect(layout[s.key]) for s in TEXT_SLOTS if s.clear_hint]
    with pymupdf.open(TEMPLATE_PATH) as blank:
        printed = [pymupdf.Rect(w[:4]) for w in blank[FORM_PAGE].get_text("words")]
    printed = [r for r in printed if not any(c.contains(r) for c in cleared)]

    pdf = build_application_draft_pdf(FULL_VALUES)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[FORM_PAGE]
        for slot in TEXT_SLOTS:
            value = FULL_VALUES[slot.key]
            if not value:
                continue
            rect = _word_rect(page, value.split()[0])
            clashes = [r for r in printed if (r & rect).get_area() > 0.5]
            assert not clashes, f"{slot.key}: 인쇄된 글자와 겹친다 — {clashes[:2]}"


def test_page_count_and_consent_pages_untouched():
    """동의서 2~4쪽은 손대지 않는다 — 동의 여부는 본인이 표시해야 한다."""
    with pymupdf.open(TEMPLATE_PATH) as blank:
        before = [blank[i].get_text() for i in range(1, 4)]
    with pymupdf.open(stream=build_application_draft_pdf(FULL_VALUES), filetype="pdf") as doc:
        assert doc.page_count == 4
        assert [doc[i].get_text() for i in range(1, 4)] == before


def test_blank_values_stay_blank():
    """빈 값은 빈 칸으로 남긴다 — "미입력" 같은 말을 대신 적지 않는다."""
    pdf = build_application_draft_pdf({"company_name": "동성로카페"})
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = doc[FORM_PAGE].get_text()
    assert "동성로카페" in text
    for word in ("미입력", "없음", "해당없음", "None"):
        assert word not in text


def test_empty_values_produce_pristine_form():
    """아무 값도 없으면 빈 서식 그대로다(자격만 되고 3단계를 안 채운 사장님)."""
    with pymupdf.open(TEMPLATE_PATH) as blank:
        before = blank[FORM_PAGE].get_text()
    with pymupdf.open(stream=build_application_draft_pdf({}), filetype="pdf") as doc:
        assert doc[FORM_PAGE].get_text() == before


def test_application_kind_marks_the_right_checkbox():
    """□가입신청 / □정보 변경신청은 같은 글리프라 등장 순서로 갈린다 — 바꿔 찍으면 안 된다."""
    layout = verify_layout()
    new_box = pymupdf.Rect(layout["application_kind:new"])
    change_box = pymupdf.Rect(layout["application_kind:change"])
    assert new_box.x1 < change_box.x0, "가입신청 체크박스가 정보변경신청보다 왼쪽이어야 한다"

    with pymupdf.open(stream=build_application_draft_pdf({"application_kind": "new"}),
                      filetype="pdf") as doc:
        drawn = [pymupdf.Rect(d["rect"]) for d in doc[FORM_PAGE].get_drawings()
                 if new_box.contains(pymupdf.Rect(d["rect"]))
                 or change_box.contains(pymupdf.Rect(d["rect"]))]
    assert drawn, "체크 표시가 그려지지 않았다"
    assert all(new_box.intersects(r) for r in drawn)


def test_incentive_circle_lands_on_the_chosen_number():
    """서식 지시대로 선택한 번호에 동그라미를 친다. ④는 안내문구에도 나오는데 그쪽이
    아니라 선택란의 ④여야 한다."""
    layout = verify_layout()
    target = pymupdf.Rect(layout["incentive_type:green_card_point"])
    pdf = build_application_draft_pdf({"incentive_type": "green_card_point"})
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[FORM_PAGE]
        ovals = [pymupdf.Rect(d["rect"]) for d in page.get_drawings()
                 if any(item[0] == "c" for item in d["items"])]
        # 안내문구의 ④(선택란보다 아래)에는 동그라미가 없어야 한다.
        guidance = [r for r in ovals if r.y0 > target.y1 + 20]
    assert any(r.intersects(target) for r in ovals), "선택란 ④에 동그라미가 없다"
    assert not guidance, f"안내문구 쪽에 동그라미가 그려졌다: {guidance}"


def test_unknown_value_key_raises():
    """호출부 오타를 조용한 빈칸으로 흘리지 않는다."""
    with pytest.raises(ValueError, match="서식에 없는 값 key"):
        build_application_draft_pdf({"applicant_phne": "01011112222"})


def test_value_outside_form_vocabulary_raises():
    """DB CHECK 어휘와 서식 대응이 어긋나면 표시를 빼먹지 않고 터진다."""
    with pytest.raises(ValueError, match="서식 대응이 없는 값"):
        build_application_draft_pdf({"incentive_type": "local_currency"})


def test_full_values_cover_every_slot():
    """이 파일의 FULL_VALUES가 서식 슬롯 전체를 덮는다 — 슬롯이 늘면 위치 검사도 따라온다."""
    assert set(FULL_VALUES) == SLOT_KEYS


def test_fields_without_a_form_box_have_no_slot():
    """서식에 칸이 없어 일부러 인쇄하지 않는 항목 — 근거는 cnp_application_pdf 모듈 주석."""
    from db.carbon_neutral_point import APPLICANT_FIELD_KEYS

    # 예금주는 우리가 값을 갖고 있는데도 인쇄하지 않는다(금융정보란이 은행명·계좌번호 2칸뿐).
    assert "account_holder" in APPLICANT_FIELD_KEYS
    assert "account_holder" not in SLOT_KEYS
    # 비밀번호는 애초에 저장하지 않고, BLANK_BY_POLICY 3종은 상업시설에 해당 없다.
    for key in ("password", "residence_area", "household_size", "move_in_date"):
        assert key not in SLOT_KEYS
