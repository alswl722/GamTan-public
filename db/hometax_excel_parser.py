"""홈택스 세금계산서 다운로드 엑셀 파서 — 대량 전표 업로드용.

⚠️ 컬럼 매핑은 잠정안이다. 실제 홈택스 다운로드 포맷 샘플이 회계 담당에게서
도착하기 전까지는 아래 매핑을 그대로 쓰고, 샘플 도착 즉시 별칭 목록만 교체한다
(호출부·반환 스키마는 안 바뀜).
"""
import io
from datetime import datetime

import openpyxl

_COLUMN_ALIASES = {
    "issue_date": ("작성일자", "발급일자", "작성일"),
    "supplier_name": ("상호", "공급자상호", "거래처명"),
    "item_description": ("품목명", "품목", "규격"),
    "supply_amount_krw": ("공급가액", "공급가액(원)"),
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d")


class HometaxExcelFormatError(ValueError):
    """헤더에서 필수 컬럼을 찾지 못했을 때 — "이 파일 포맷이 아니에요" 안내용."""


def _find_column(header: list[str], aliases: tuple[str, ...]) -> int | None:
    for i, h in enumerate(header):
        if h in aliases:
            return i
    return None


def _coerce_date(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "year") and hasattr(value, "month"):  # datetime.date
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise HometaxExcelFormatError(f"날짜 형식을 인식할 수 없습니다: {value!r}")


def parse_hometax_excel(file_bytes: bytes) -> list[dict]:
    """엑셀 바이트 → 전표 행 리스트.

    각 행: supplier_name, item_description, supply_amount_krw, year, month, issue_date(ISO).
    필수 컬럼이 아예 없으면 HometaxExcelFormatError(포맷 자체가 다름), 필수값이
    빈 개별 행은 조용히 스킵한다(한 행의 결측이 전체 업로드를 막지 않게).
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col_idx = {key: _find_column(header, aliases) for key, aliases in _COLUMN_ALIASES.items()}
    missing = [key for key, idx in col_idx.items() if idx is None]
    if missing:
        raise HometaxExcelFormatError(f"필수 컬럼을 찾을 수 없습니다: {missing} (헤더: {header})")

    out = []
    for r in rows[1:]:
        if all(c is None for c in r):
            continue
        issue_date_raw = r[col_idx["issue_date"]]
        supply_amount = r[col_idx["supply_amount_krw"]]
        if issue_date_raw is None or supply_amount is None:
            continue

        issue_date = _coerce_date(issue_date_raw)
        out.append({
            "supplier_name": r[col_idx["supplier_name"]],
            "item_description": r[col_idx["item_description"]],
            "supply_amount_krw": float(supply_amount),
            "year": issue_date.year,
            "month": issue_date.month,
            "issue_date": issue_date.isoformat(),
        })
    return out
