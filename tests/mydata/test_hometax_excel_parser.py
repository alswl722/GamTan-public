"""db/hometax_excel_parser.py 골든케이스 — 컬럼 매핑은 잠정안이므로 회계 샘플
도착 시 이 테스트의 헤더 문자열만 갱신하면 된다."""
import io
from datetime import date, datetime

import openpyxl
import pytest

from db.hometax_excel_parser import HometaxExcelFormatError, parse_hometax_excel


def _make_xlsx(headers: list[str], rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parses_rows_with_date_object_and_string_date():
    xlsx = _make_xlsx(
        ["작성일자", "상호", "품목명", "공급가액"],
        [
            (date(2025, 3, 15), "구미석유", "경유", 600000),
            ("2025-04-10", "대성에너지", "도시가스", 480000),
        ],
    )
    rows, skipped = parse_hometax_excel(xlsx)
    assert len(rows) == 2
    assert skipped == 0
    assert rows[0] == {
        "supplier_name": "구미석유",
        "item_description": "경유",
        "supply_amount_krw": 600000.0,
        "year": 2025,
        "month": 3,
        "issue_date": datetime(2025, 3, 15).isoformat(),
    }
    assert rows[1]["year"] == 2025 and rows[1]["month"] == 4


def test_skips_rows_missing_required_values_and_reports_count():
    xlsx = _make_xlsx(
        ["작성일자", "상호", "품목명", "공급가액"],
        [
            (date(2025, 3, 15), "구미석유", "경유", None),  # 공급가액 없음 — 스킵
            (date(2025, 4, 10), "대성에너지", "도시가스", 480000),
        ],
    )
    rows, skipped = parse_hometax_excel(xlsx)
    assert len(rows) == 1
    assert skipped == 1
    assert rows[0]["supplier_name"] == "대성에너지"


def test_raises_on_unrecognized_format():
    xlsx = _make_xlsx(["컬럼A", "컬럼B"], [("x", "y")])
    with pytest.raises(HometaxExcelFormatError):
        parse_hometax_excel(xlsx)


def test_accepts_alias_headers():
    xlsx = _make_xlsx(
        ["발급일자", "거래처명", "품목", "공급가액(원)"],
        [(date(2025, 5, 1), "구미주유소", "휘발유", 300000)],
    )
    rows, skipped = parse_hometax_excel(xlsx)
    assert len(rows) == 1
    assert skipped == 0
    assert rows[0]["supplier_name"] == "구미주유소"


def test_raises_format_error_instead_of_500_on_corrupt_or_legacy_xls():
    """openpyxl이 열 수 없는 바이트(구버전 .xls·손상 파일)는 처리되지 않은 예외로
    새는 대신 HometaxExcelFormatError로 통일된다 — 라우터가 이미 이 예외만 잡아
    422로 안내하므로, 여기서 안 잡으면 그대로 500이 된다(실패 가시성 원칙)."""
    not_an_xlsx = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1this is not a real xls file"
    with pytest.raises(HometaxExcelFormatError):
        parse_hometax_excel(not_an_xlsx)
