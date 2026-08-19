"""db/document_text_extractor.py — PDF 텍스트에서 문서종류·날짜·금액·수량을
정규식으로 파싱하는 실 추출기 검증. 값을 지어내지 않는지가 핵심축."""
import csv
import glob
import io
import os
import unicodedata

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from api.document_ingestion import REPO_ROOT
from db.document.document_text_extractor import (
    USAGE_UNRECOGNIZED_QUALITY_FLAG,
    DocumentParseError,
    DocumentTypeMismatchError,
    detect_document_type,
    extract_pdf_text,
    parse_document_text,
    parse_tax_invoice_date_table,
    parse_tax_invoice_table_rows,
    parse_year_month_from_cell_text,
)

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    y = 700
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_extract_pdf_text_returns_none_for_non_pdf_bytes():
    assert extract_pdf_text(b"not a pdf") is None


def test_extract_pdf_text_reads_real_pdf():
    text = extract_pdf_text(_pdf(["안녕하세요"]))
    assert text is not None
    assert "안녕하세요" in text


def test_electric_bill_parses_date_amount_quantity():
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-01 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 4,477",
        "청구금액(원) 5,491,807",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result == {
        "supplier_name": "한국전력공사",
        "item_description": "전기요금 (산업용 을)",
        "supply_amount_krw": 5_491_807,
        "quantity": 4477,
        "quantity_unit": "kWh",
        "year": 2025,
        "month": 1,
        # 전기고지서는 "그 달 청구서"일 뿐 특정 일자가 없어 말일로 채운다
        # (db/document_text_extractor.py::month_end_issue_date_str).
        "issue_date": "2025-01-31",
        "document_type": "electric_bill",
    }


def test_electric_bill_rejects_forecast_labeled_amount():
    """실측(2026-08-17, 실제 한전 카카오 알림톡 캡처): "예상청구금액"처럼 실제
    라벨과 겉보기엔 비슷한 문구로 AI 예측치를 안내하는 경우가 있다 — 값을 지어내지
    않는다는 원칙상, 실제 청구금액이 아니라 예상치임을 알아채면 명확히 실패해야
    한다(더 선명한 사진으로는 해결 안 되는 문제이므로 그 사실을 메시지로 알려준다)."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-01 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 4,477",
        "예상청구금액(원) 5,491,807",
    ]))
    with pytest.raises(DocumentParseError, match="예상"):
        parse_document_text(text, "electric_bill")


def test_electric_bill_table_layout_usage_extracts_header_row_value():
    """실측: 한전 고지서 중엔 "사용량(kWh)" 인라인 라벨이 아니라 "당월 사용량 |
    전월 사용량 | 전월 대비 | 계약전력" 헤더 행과 "2,450 kWh | 2,400 kWh | +50 kWh |
    75 kW" 값 행이 따로 렌더링되는 표 서식이 있다(합성 전표 생성기가 만드는
    실제 서식). 헤더 뒤 첫 kWh 값(당월 사용량)을 잡아야지, 옆 칸의 계약전력
    (kW, kWh 아님)과 헷갈리면 안 된다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-01 계약종별: 산업용(을) 고압A",
        "당월 사용량 전월 사용량 전월 대비 계약전력",
        "2,450 kWh 2,400 kWh +50 kWh 75 kW",
        "청구금액(원) 5,491,807",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["quantity"] == 2450
    assert result["quantity_unit"] == "kWh"
    assert "quality_flag" not in result


def test_electric_bill_table_layout_usage_matches_without_space_in_label():
    """실측(2026-08-18, data/fixtures/electricity_bills 재업로드 검증): 같은 표
    서식이라도 PaddleOCR(JPG 경로)이 "당월 사용량"을 "당월사용량"처럼 띄어쓰기
    없이 재구성하는 경우가 있었다 — PDF/PNG 경로는 통과했는데 JPG만 review_required
    로 빠진 원인. 라벨 리터럴에 공백을 그대로 박아두면 그 자리만 공백이 필수가
    돼(_label_pattern은 문자 사이를 \\s*로 선택적으로 만들지만, 리터럴 공백 문자
    자체는 최소 1개를 요구) 붙어 나온 텍스트를 못 잡았다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-02 계약종별: 산업용(을) 저압",
        "당월사용량 전월사용량 전월 대비 계약전력",
        "검침 확인지연 2,450 kWh 75 kW",
        "청구금액(원) 590,000",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["quantity"] == 2450
    assert result["quantity_unit"] == "kWh"
    assert "quality_flag" not in result


def test_electric_bill_kwh_present_but_unrecognized_sets_quality_flag():
    """사용량 텍스트가 있는 것 같은데(kWh 흔적) 알려진 두 패턴(인라인 라벨·표
    헤더) 어느 쪽에도 안 걸리면, 원래 사용량이 없는 서식과 똑같이 quantity=None
    으로 조용히 넘기지 않고 quality_flag로 구분해 둔다 — 파서 결함과 진짜 데이터
    갭을 구분해야 HITL에 조용히 묻히지 않는다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-01 계약종별: 산업용(을) 고압A",
        "이번 달 검침 기준 사용전력량은 kWh 단위로 뒷면 그래프를 참고하세요",
        "청구금액(원) 5,491,807",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert "quantity" not in result
    assert result["quality_flag"] == USAGE_UNRECOGNIZED_QUALITY_FLAG
    assert "guidance_message" in result


def test_parse_document_text_without_expected_type_auto_detects():
    """expected_document_type 생략("그냥 업로드")하면 대조 없이 판별된 종류를
    그대로 신뢰하고 반환 dict의 document_type으로 알려준다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text)
    assert result["document_type"] == "electric_bill"
    assert result["year"] == 2025 and result["month"] == 6


def test_gas_bill_parses_date_amount_quantity():
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "사용월: 2025-03   용도: 산업용",
        "사용량(m³) 800",
        "청구금액(원) 900,000",
    ]))
    result = parse_document_text(text, "gas_bill")
    assert result["year"] == 2025 and result["month"] == 3
    assert result["quantity"] == 800
    assert result["supply_amount_krw"] == 900_000


def test_gas_bill_without_quantity_label_succeeds_without_quantity():
    """전기요금 고지서와 같은 이유(db/calc_engine.py::_QUANTITY_ONLY — 수량 없으면
    금액 역산 대신 사람검토) — 사용량 라벨을 못 찾아도 날짜·금액만으로 파싱은
    성공해야 한다. 도시가스 실물 샘플이 아직 없어(docs/document-ocr-taxonomy.md)
    전기요금에서 실측된 편차를 선제 적용한 것 — 이 테스트는 그 완화가 실제로
    동작하는지만 고정한다."""
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "사용월: 2025-03   용도: 산업용",
        "청구금액(원) 900,000",
    ]))
    result = parse_document_text(text, "gas_bill")
    assert "quantity" not in result
    assert result["supply_amount_krw"] == 900_000


def test_gas_bill_date_without_label_or_separator_parses():
    """전기요금과 같은 완화 — "사용월:" 라벨이나 -./ 구분자 없이 "2025년 3월분"
    형태만 있어도 인식해야 한다."""
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "2025년 3월분 도시가스 요금",
        "청구금액 900,000원",
    ]))
    result = parse_document_text(text, "gas_bill")
    assert result["year"] == 2025 and result["month"] == 3
    assert result["supply_amount_krw"] == 900_000


def test_tax_invoice_parses_item_amount_and_quantity_from_table_row():
    """수량+단위가 붙은 컬럼("301L")도 이제 캡처한다 — 세금계산서 경로로 들어오는
    유류비 전표도 PCAF 2a(energy_consumption) 판정에 도달할 수 있어야 한다."""
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미에너지주유소",
        "작성일자: 2025-02-11",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "경유 L 301L 1,400 420,833",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["supplier_name"] == "구미에너지주유소"
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 420_833
    assert result["year"] == 2025 and result["month"] == 2
    assert result["quantity"] == 301
    assert result["quantity_unit"] == "L"


def test_tax_invoice_without_printed_quantity_omits_quantity_fields():
    """세금계산서는 물량이 안 찍힌 경우("-" 등)가 더 흔하다 — 이때는 quantity를
    합성해 넣지 않고 기존 금액÷단가 환산 경로를 그대로 탄다."""
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미석유",
        "작성일자: 2025-01-18",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "유류대금 - - 1,400 420,000",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["item_description"] == "유류대금"
    assert "quantity" not in result
    assert result["supply_amount_krw"] == 420_000


def test_tax_invoice_item_row_with_space_in_item_name_fails_instead_of_truncating():
    """실측(2026-08-17, 위 테스트가 원래 쓰던 픽스처로 재현): 품목명이 "유류대금
    외1종"처럼 공백을 포함하면 한 줄 정규식은 공백 앞까지("유류대금")만 잡고
    나머지("외1종")를 규격 컬럼으로 흘려보내 조용히 틀린 값을 만들었다 — "동절기
    난방유"였다면 실제 연료 키워드가 사라지는 심각한 오분류로 이어질 수 있었다.
    정규식만으로는 공백이 품목명 내부 띄어쓰기인지 컬럼 구분인지 구별 못 하므로,
    틀리게 자르는 대신 명확히 실패시켜 OCR 좌표매칭·LLM 라우터(둘 다 셀 단위라
    이 모호함이 없음)로 넘어가게 한다."""
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미난방",
        "작성일자: 2025-01-18",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "동절기 난방유 - 1,400 200,000",
    ]))
    with pytest.raises(DocumentParseError, match="품목·공급가액|품목명"):
        parse_document_text(text, "tax_invoice")


def test_degraded_scan_amount_masked_raises_instead_of_faking_value():
    """저품질 스캔 시나리오 — 금액이 ▨로 가려져 있으면 0이나 추정치를 만들지 않고
    명확히 실패한다(실패 가시성 원칙)."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-02 계약종별: 산업용(을) 고압A",
        "사용량(kWh) ▨▨▨ (판독 불가)",
        "청구금액(원) ▨,▨▨▨,▨▨▨ (판독 불가)",
    ]))
    with pytest.raises(DocumentParseError):
        parse_document_text(text, "electric_bill")


def test_wrong_document_type_slot_is_rejected_not_silently_relabeled():
    """도시가스고지서 파일을 전기요금고지서 칸에 올리면, 도시가스 데이터를 전기요금인
    척 반환하지 않고 명확히 실패시킨다."""
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "사용월: 2025-01   용도: 산업용",
        "사용량(m³) 800",
        "청구금액(원) 900,000",
    ]))
    with pytest.raises(DocumentParseError, match="전기요금고지서"):
        parse_document_text(text, "electric_bill")


def test_unrecognized_document_raises():
    text = extract_pdf_text(_pdf(["아무 문서", "관련 없는 내용"]))
    with pytest.raises(DocumentParseError):
        parse_document_text(text, "electric_bill")


# ── 실측 스파이크로 확인된 OCR 편차 강건화 ─────────────────────────────────────

def test_extract_pdf_text_reads_all_pages():
    """1페이지만 읽던 것을 전체 페이지로 확장 — 필드가 2페이지에 있어도 놓치지 않는다."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    c.drawString(50, 700, "전기요금 고지서")
    c.drawString(50, 680, "청구월: 2025-06 계약종별: 산업용(을) 고압A")
    c.showPage()
    c.setFont("HYGothic-Medium", 11)
    c.drawString(50, 700, "사용량(kWh) 1,234")
    c.drawString(50, 680, "청구금액(원) 987,654")
    c.save()

    text = extract_pdf_text(buf.getvalue())
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654


def test_detect_document_type_tolerates_title_not_on_first_line():
    """실제 문서는 로고·페이지번호 등이 제목보다 앞에 올 수 있다 — 첫 줄 정확히
    일치가 아니라 앞 5줄 안에서 찾는다."""
    text = extract_pdf_text(_pdf([
        "(주)테스트유틸리티",
        "전기요금 고지서",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_electric_bill_tolerates_space_before_colon():
    """실측 스파이크: OCR이 "청구월 : 2025-06"처럼 라벨과 콜론 사이에 공백을 넣는
    경우가 확인됐다 — 기존 정규식(청구월:\\s*)은 이 경우 매칭 실패였다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월 : 2025-06 계약종별 : 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_electric_bill_tolerates_label_glued_to_value():
    """실측 스파이크: OCR이 "사용량(kWh)1,234"처럼 라벨과 값 사이 공백 없이 인식하는
    경우가 확인됐다 — 기존 \\s+ 는 매칭 실패, \\s*로 완화."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-06",
        "사용량(kWh)1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["quantity"] == 1234


def test_electric_bill_tolerates_dot_date_separator():
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025.06",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_detect_document_type_tolerates_letter_spaced_title():
    """실측(2026-08-17, 실제 국세청 표준 세금계산서): 제목이 "전 자 세 금 계 산 서"
    처럼 글자 사이가 벌어져 렌더링된다(디자인상 자간 강조) — PDF 텍스트 레이어·
    OCR 재구성 텍스트 둘 다 이 간격을 그대로 보존한다."""
    assert detect_document_type("전 자 세 금 계 산 서\n공급자: 테스트") == "tax_invoice"


def test_electric_bill_tolerates_letter_spaced_label():
    """같은 자간 문제가 본문 라벨에도 적용될 수 있다 — "청 구 월"."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청 구 월: 2025-06",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_gas_bill_tolerates_letter_spaced_label():
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "사 용 월: 2025-06",
        "사용량(m³) 120",
        "청구금액(원) 55,000",
    ]))
    result = parse_document_text(text, "gas_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_tax_invoice_tolerates_letter_spaced_date_label():
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "작 성 일 자: 2025-02-11",
        "공급자: 구미에너지주유소",
        "경유 L 301L 1,400 420,833",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 2
    assert result["issue_date"] == "2025-02-11"


def test_date_sep_tolerates_space_after_separator():
    """실측(2026-08-17): 표 형식 요약행의 날짜 셀이 OCR에서 "2025- 02-11"처럼
    구분자 뒤에 공백이 섞여 재구성됐다(등록번호·금액 셀도 동일 패턴)."""
    rows = [
        [(0.0, 80.0, "작성일자"), (150.0, 220.0, "공급가액")],
        [(0.0, 90.0, "2025- 02-11"), (150.0, 220.0, "420, 833")],
    ]
    assert parse_tax_invoice_date_table(rows) == (2025, 2, 11)


def test_parse_tax_invoice_date_table_tolerates_letter_spaced_header_cell():
    """헤더 셀 자체가 "작 성 일 자"처럼 자간이 벌어져도 좌표 기반 매칭이 통해야 한다."""
    rows = [
        [(0.0, 80.0, "작 성 일 자"), (150.0, 220.0, "공급가액")],
        [(0.0, 90.0, "2025-03-05"), (150.0, 220.0, "300,000")],
    ]
    assert parse_tax_invoice_date_table(rows) == (2025, 3, 5)


def test_parse_tax_invoice_table_rows_tolerates_letter_spaced_header_cell():
    rows = [
        [(0.0, 82.0, "품 목 명"), (267.0, 336.0, "수량"), (581.0, 748.0, "공급가액(원)")],
        [(0.0, 55.0, "경유"), (266.0, 344.0, "301L"), (580.0, 704.0, "420,833")],
    ]
    result = parse_tax_invoice_table_rows(rows)
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 420_833


def test_slotted_upload_does_not_require_exact_title_phrase():
    """슬롯이 이미 정해졌으면(예: electric_bill 칸에 업로드) 제목이 이 프로젝트가 아는
    정확한 3개 문구("전기요금 고지서" 등)와 달라도(실제 문서는 "전기요금청구서" 같은
    다른 표현일 수 있다) 필드(청구월·사용량·청구금액)만 있으면 파싱된다 — 제목
    일치는 슬롯 미지정("그냥 업로드") 경로에서만 필요하다."""
    text = extract_pdf_text(_pdf([
        "한국전력공사 전기요금청구서",  # 이 프로젝트가 아는 정확한 문구가 아님
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["document_type"] == "electric_bill"


def test_slotted_upload_without_title_or_fields_still_fails_clearly():
    """슬롯을 알아도 필드 자체가 없으면(정말 다른 문서) 값을 지어내지 않고 명확히
    실패한다 — 제목 게이트를 뺀 게 아무 문서나 통과시킨다는 뜻은 아니다."""
    text = extract_pdf_text(_pdf(["아무 문서", "관련 없는 내용"]))
    with pytest.raises(DocumentParseError):
        parse_document_text(text, "electric_bill")


def test_real_kepco_bill_structure_parses_via_slotted_upload():
    """실제 한전 전기요금 청구서 사진(사용자 제공, 2021-12/2022-01분) 실측 확인:
    "청구월:" 라벨 자체가 없고 제목에 "2021년 12월분"으로 찍힘, "청구금액(원)"이
    아니라 "청구금액"(단위 없이), "사용량(kWh)" 라벨은 아예 안 보임(사용전력량이
    비교그래프·계량기지침 표 등 다른 형태), 청구내역이 기본요금·전력량요금·
    기후환경요금·복지할인 등 여러 항목으로 나뉜 표. 이 모든 실측 특징을 한 번에
    재현해 슬롯 지정 업로드가 성공하는지 확인한다."""
    text = extract_pdf_text(_pdf([
        "한국전력공사",
        "2021년 12월분 전기요금 청구서",
        "전기사용장소 ○○정밀 (경북 구미)",
        "청구금액 9,240 원",
        "고객번호 000000000  납기일 2022년 01월 17일",
        "사용기간 2021년 10월 22일 ~ 2021년 12월 21일",
        "기본요금 910",
        "전력량요금 12,362",
        "기후환경요금 742",
        "복지할인 -12,000",
        "부가가치세 201",
        "당월청구요금 2,280",
        "미납요금 4,460",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["document_type"] == "electric_bill"
    assert result["year"] == 2021 and result["month"] == 12
    assert result["supply_amount_krw"] == 9_240
    assert "quantity" not in result  # 사용량 라벨을 못 찾아도 금액만으로 파싱 성공


def test_real_kepco_bill_date_without_bun_suffix_parses():
    """실측(2026-08-17, 사용자 제공 "전기요금청구 및 영수증" 캡처): 이 서식은
    "2021년 1월"처럼 "분" 없이 청구월이 찍힌다 — "12월분"만 인식하던 기존 정규식
    으로는 청구월을 못 찾아 문서 전체가 실패했다(4단계 LLM 최후수단까지도, 그
    재파싱 함수가 같은 -./ 구분자 전제를 썼기 때문). "분" 없는 표기도 통과해야
    한다."""
    text = extract_pdf_text(_pdf([
        "홍길동 고객님의 2021년 1월",
        "전기요금청구 및 영수증(고객용)",
        "청구 금액 26,270 원",
        "납기일 2021년 02월 15일",
        "사용 기간 2021년 01월 06일 ~ 2021년 01월 23일",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2021 and result["month"] == 1
    assert result["supply_amount_krw"] == 26_270


def test_parse_year_month_from_cell_text_accepts_korean_year_month():
    """db/document_llm_router.py가 LLM이 가리킨 셀 원문을 재파싱할 때 쓰는 공개
    진입점 — -./ 구분자 없이 "년/월"만 쓴 셀 텍스트도 인식해야 한다(위 테스트와
    같은 실측 근거). 3번째 값(day)은 셀에 일자가 있으면 채워지고, 없으면 None —
    호출부가 issue_date 폴백(세금계산서는 실패, 전기·가스는 말일) 여부를 가른다."""
    assert parse_year_month_from_cell_text("2021년 1월") == (2021, 1, None)
    assert parse_year_month_from_cell_text("2021년 01월 06일") == (2021, 1, 6)
    assert parse_year_month_from_cell_text("2025-02-11") == (2025, 2, 11)  # 기존 경로 회귀 방지


def test_real_kepco_bill_title_recognized_without_slot():
    """"그냥 업로드"(슬롯 미지정)에서도 실측 제목("OO월분 전기요금 청구서")으로
    문서종류를 판별한다 — "전기요금 고지서"라는 정확한 문구가 없어도 통과해야 한다."""
    text = extract_pdf_text(_pdf([
        "한국전력공사",
        "2022년 01월분 전기요금 청구 및 영수증(고지서)",
        "청구금액 15,000 원",
    ]))
    assert detect_document_type(text) == "electric_bill"


def test_electric_bill_amount_label_without_won_unit_suffix():
    """실측: "청구금액(원)"이 아니라 "청구금액"(단위 없이) 바로 뒤에 "9,240원"처럼
    값 자체에 "원"이 붙어 온다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-06",
        "청구금액 987,654원",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["supply_amount_krw"] == 987_654


def test_tax_invoice_accepts_issue_date_label_synonym():
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미에너지주유소",
        "발급일자: 2025-02-11",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "경유 L 301L 1,400 420,833",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 2


# ── 관리비 고지서 ────────────────────────────────────────────────────────────

def test_management_fee_bill_extracts_electric_item_with_quality_flag():
    text = extract_pdf_text(_pdf([
        "○○빌딩 관리비 고지서",
        "부과월: 2025-06",
        "일반관리비 320,000",
        "전기료 187,000원",
        "청소비 90,000",
    ]))
    result = parse_document_text(text)  # "그냥 업로드" — 슬롯 지정 없음
    assert result["document_type"] == "electric_bill"
    assert result["supply_amount_krw"] == 187_000
    assert result["year"] == 2025 and result["month"] == 6
    assert result["quality_flag"] == "mgmt_fee_estimate"
    assert "재발행" in result["guidance_message"]


def test_management_fee_bill_in_wrong_slot_is_rejected():
    """관리비 고지서를 세금계산서 칸에 올리면 전기고지서 칸으로 안내하며 명확히 실패."""
    text = extract_pdf_text(_pdf([
        "○○빌딩 관리비 고지서",
        "부과월: 2025-06",
        "전기료 187,000원",
    ]))
    with pytest.raises(DocumentTypeMismatchError, match="전기요금고지서"):
        parse_document_text(text, "tax_invoice")


def test_management_fee_bill_without_electric_line_item_raises():
    text = extract_pdf_text(_pdf([
        "○○빌딩 관리비 고지서",
        "부과월: 2025-06",
        "일반관리비 320,000",
    ]))
    with pytest.raises(DocumentParseError, match="관리비 고지서"):
        parse_document_text(text)


# ── OCR 좌표 기반 표 재구성 (parse_tax_invoice_table_rows) ──────────────────────

def test_parse_tax_invoice_table_rows_matches_columns_by_x_position():
    """실측 스파이크에서 확인된 실제 좌표(품목명·규격·수량·단가(원)·공급가액(원)
    헤더 아래 경유/L/301L/1,400/420,833 데이터 행)를 그대로 재현."""
    rows = [
        [(0.0, 82.0, "품목명"), (129.0, 195.0, "규격"), (267.0, 336.0, "수량"),
         (404.0, 516.0, "단가(원)"), (581.0, 748.0, "공급가액(원)")],
        [(0.0, 55.0, "경유"), (125.0, 154.0, "L"), (266.0, 344.0, "301L"),
         (401.0, 490.0, "1,400"), (580.0, 704.0, "420,833")],
    ]
    result = parse_tax_invoice_table_rows(rows)
    assert result == {
        "item_description": "경유",
        "supply_amount_krw": 420_833,
        "quantity": 301,
        "quantity_unit": "L",
    }


def test_parse_tax_invoice_table_rows_without_header_returns_none():
    """헤더 행을 못 찾으면 예외 대신 None — 호출부가 다른 경로를 계속 시도할 수 있게."""
    rows = [[(0.0, 55.0, "경유"), (580.0, 704.0, "420,833")]]
    assert parse_tax_invoice_table_rows(rows) is None


# ── parse_tax_invoice_date_table (실측: 콜론 없는 헤더행/데이터행 서식) ─────────

def test_parse_tax_invoice_date_table_matches_real_kepco_style_layout():
    """실측(2026-08-16, 사용자 제공 합성 세금계산서 사진) — 국세청 표준 세금계산서는
    "작성일자:" 콜론이 아니라 헤더행("작성일자"/"공급가액"/"세액"/"비고") 아래
    데이터행이 오는 표 구조였다. 같은 문서에 공급가액 컬럼을 가진 표가 두 개
    (이 요약행, 품목행) 있어도 "작성일자" 키워드로 올바른 헤더행을 구분해야 한다."""
    rows = [
        [(0.0, 80.0, "작성일자"), (150.0, 220.0, "공급가액"), (280.0, 320.0, "세액"), (360.0, 400.0, "비고")],
        [(0.0, 90.0, "2025-01-11"), (150.0, 220.0, "460, 617"), (280.0, 320.0, "46, 062"), (500.0, 520.0, "월")],
        [(0.0, 60.0, "품목"), (150.0, 220.0, "공급가액")],  # 품목행 헤더 — 여기 걸리면 안 됨
        [(0.0, 55.0, "경유"), (150.0, 220.0, "420,833")],
    ]
    assert parse_tax_invoice_date_table(rows) == (2025, 1, 11)


def test_parse_tax_invoice_date_table_accepts_issue_date_label_synonym():
    rows = [
        [(0.0, 80.0, "발급일자"), (150.0, 220.0, "공급가액")],
        [(0.0, 90.0, "2025.07.10"), (150.0, 220.0, "420,000")],
    ]
    assert parse_tax_invoice_date_table(rows) == (2025, 7, 10)


def test_parse_tax_invoice_date_table_without_header_returns_none():
    rows = [[(0.0, 55.0, "경유"), (580.0, 704.0, "420,833")]]
    assert parse_tax_invoice_date_table(rows) is None


def test_parse_tax_invoice_date_table_header_without_value_returns_none():
    """헤더는 찾았는데 그 아래 행에 날짜 형식 값이 없으면 예외 대신 None."""
    rows = [
        [(0.0, 80.0, "작성일자"), (150.0, 220.0, "공급가액")],
        [(0.0, 90.0, "판독불가"), (150.0, 220.0, "460,617")],
    ]
    assert parse_tax_invoice_date_table(rows) is None


# ── 별지 제11호 국세청 표준 수기 세금계산서(실측 2026-08-18, data/fixtures/
#    tax_invoices) — "작성일자:" 콜론도 "작성일자" 헤더 셀도 아니라 "작성" 2글자
#    라벨 + 2자리 연도, 품목행은 월/일/세액/비고까지 포함한 9칼럼이다. ──────────

def test_detect_document_type_recognizes_title_without_jeonja_prefix():
    assert detect_document_type("세 금 계 산 서 책 번 호") == "tax_invoice"


def test_parse_tax_invoice_header_reads_official_form_date_row():
    """"작성일자:" 콜론이 없고 "작성" 헤더 다음 줄에 연(2자리)·월·일이 공백으로만
    구분돼 있다. 뒤따르는 자릿값 라벨("백"·"십"...)은 금액 자릿수에 따라 위치가
    달라지므로(실측 확인) 앵커로 쓰지 않고 다음 줄 맨 앞 숫자 3개만 읽는다."""
    text = extract_pdf_text(_pdf([
        "세 금 계 산 서 책 번 호",
        "작 성 공 급 가 액 세 액 비 고",
        "25 1 8 백 십 억 천 백 1 4 2 1 0 0 십 억 천 백 십 1 4 2 1 0",
        "월 일 품 목 규격 수량 단가 공급가액 세액 비고",
        "1 8 경유 지게차용 100 1,421 142,100 14,210 지게차 연료",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 1
    assert result["issue_date"] == "2025-01-08"


def test_parse_tax_invoice_item_row_reads_official_form_row_with_memo():
    """규격 칼럼에 "지게차용"처럼 정상적인 한글 단어가 들어가도(구형 포맷 전용
    _HANGUL_SYLLABLE 방어 로직 미적용) 실패하지 않아야 하고, 비고(메모)에 공백이
    섞여도(예: "지게차 연료") 끝까지 흡수해 공급가액을 오염시키지 않아야 한다.
    수량에 단위가 안 찍혀 있으므로 quantity_unit은 채우지 않는다(db/calc_engine.py
    가 배출계수 단위로 자동 보완 — CLAUDE.md 원칙1, LLM/파서가 값을 지어내지 않음)."""
    text = extract_pdf_text(_pdf([
        "세 금 계 산 서 책 번 호",
        "작 성 공 급 가 액 세 액 비 고",
        "25 1 8 백 십 억 천 백 1 4 2 1 0 0 십 억 천 백 십 1 4 2 1 0",
        "월 일 품 목 규격 수량 단가 공급가액 세액 비고",
        "1 8 경유 지게차용 100 1,421 142,100 14,210 지게차 연료",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 142_100
    assert result["quantity"] == 100
    assert "quantity_unit" not in result


def test_parse_tax_invoice_item_row_official_form_tolerates_missing_quantity():
    """수량이 "-"(미기재)면 quantity 필드 자체를 안 넣어 금액÷단가 환산 경로로
    넘어가게 한다 — 구형 포맷과 같은 원칙."""
    text = extract_pdf_text(_pdf([
        "세 금 계 산 서 책 번 호",
        "작 성 공 급 가 액 세 액 비 고",
        "25 3 5 백 십 억 천 백 1 4 2 1 0 0 십 억 천 백 십 1 4 2 1 0",
        "월 일 품 목 규격 수량 단가 공급가액 세액 비고",
        "3 5 경유 - - - 142,100 14,210",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["supply_amount_krw"] == 142_100
    assert "quantity" not in result


# ── data/fixtures/tax_invoices 실 fixture 회귀 테스트 ────────────────────────

_TAX_INVOICE_FIXTURES_DIR = os.path.join(REPO_ROOT, "data", "fixtures", "tax_invoices")
# C006에는 스키마가 다른(카페영수증 반려 시나리오용) 별도 manifest가 섞여 있어
# 정답 대조 대상에서 제외 — 파싱 자체가 성공하는지는 아래 별도 테스트로 확인한다.
_MANIFEST_COMPANIES = ["MAIN", "C001", "C002", "C004", "C005"]


def _load_manifest(company: str) -> dict[str, dict]:
    path = os.path.join(_TAX_INVOICE_FIXTURES_DIR, company, "_manifest.csv")
    with open(path, encoding="utf-8-sig") as f:
        return {unicodedata.normalize("NFC", r["file_name"]): r for r in csv.DictReader(f)}


def _fixture_pdfs(company: str) -> list[str]:
    return sorted(glob.glob(os.path.join(_TAX_INVOICE_FIXTURES_DIR, company, "*.pdf")))


@pytest.mark.parametrize("company", _MANIFEST_COMPANIES)
def test_official_form_fixtures_match_manifest_ground_truth(company):
    """data/fixtures/tax_invoices/{company}의 모든 PDF가 텍스트 레이어 경로만으로
    (OCR 없이) 파싱되고, 결과가 같은 폴더 _manifest.csv의 정답과 일치하는지 확인 —
    이 fixture가 지금부터 파싱 로직의 기준 데이터다."""
    manifest = _load_manifest(company)
    pdfs = _fixture_pdfs(company)
    assert pdfs, f"{company}에 PDF fixture가 없음"
    for pdf_path in pdfs:
        fname = unicodedata.normalize("NFC", os.path.basename(pdf_path))
        expected = manifest[fname]
        with open(pdf_path, "rb") as f:
            text = extract_pdf_text(f.read())
        result = parse_document_text(text, "tax_invoice")
        exp_year, exp_month = expected["issue_date"].split("-")[:2]
        assert result["year"] == int(exp_year), pdf_path
        assert result["month"] == int(exp_month), pdf_path
        assert result["item_description"] == expected["item_name"], pdf_path
        assert result["supply_amount_krw"] == int(expected["supply_amount_krw"]), pdf_path


def test_official_form_fixtures_c006_all_parse_without_manifest_check():
    """C006는 manifest 스키마가 달라(카페영수증 반려 케이스 포함) 값 대조는
    못 하지만, 세금계산서 PDF는 여전히 전부 파싱 성공해야 한다."""
    pdfs = [p for p in _fixture_pdfs("C006") if "세금계산서" in os.path.basename(p)]
    assert pdfs
    for pdf_path in pdfs:
        with open(pdf_path, "rb") as f:
            text = extract_pdf_text(f.read())
        result = parse_document_text(text, "tax_invoice")
        assert result["item_description"] == "경유", pdf_path
        assert result["supply_amount_krw"] > 0, pdf_path
