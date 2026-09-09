"""홈택스 세금계산서 다운로드 엑셀 파서 — 대량 전표 업로드용.

⚠️ 컬럼 매핑은 잠정안이다. 실제 홈택스 다운로드 포맷 샘플이 회계 담당에게서
도착하기 전까지는 아래 매핑을 그대로 쓰고, 샘플 도착 즉시 별칭 목록만 교체한다
(호출부·반환 스키마는 안 바뀜).
"""
import io
import zipfile
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


def parse_hometax_excel(file_bytes: bytes) -> tuple[list[dict], int]:
    """엑셀 바이트 → (전표 행 리스트, 스킵된 행 수).

    각 행: supplier_name, item_description, supply_amount_krw, year, month, issue_date(ISO).
    필수 컬럼이 아예 없으면 HometaxExcelFormatError(포맷 자체가 다름). 필수값이 빈
    개별 행은 스킵하되(한 행의 결측이 전체 업로드를 막지 않게), 몇 건이 스킵됐는지는
    반환해 호출부가 사용자에게 그대로 보여줄 수 있게 한다(CLAUDE.md 실패 가시성 원칙 —
    "vouchers_created: 18"만 보여주고 2건이 조용히 사라졌다는 사실을 숨기지 않는다).

    구버전 .xls(OLE2 바이너리)나 손상된 파일처럼 openpyxl이 아예 열지 못하는 경우도
    HometaxExcelFormatError로 통일해 던진다 — 처리 안 된 예외가 그대로 500으로 새지 않게.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise HometaxExcelFormatError(
            "엑셀 파일을 열 수 없습니다 — .xlsx 형식인지, 파일이 손상되지 않았는지 확인해 주세요 "
            "(구버전 .xls는 지원하지 않습니다)."
        ) from e

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], 0

    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col_idx = {key: _find_column(header, aliases) for key, aliases in _COLUMN_ALIASES.items()}
    missing = [key for key, idx in col_idx.items() if idx is None]
    if missing:
        raise HometaxExcelFormatError(f"필수 컬럼을 찾을 수 없습니다: {missing} (헤더: {header})")

    out = []
    skipped = 0
    for r in rows[1:]:
        if all(c is None for c in r):
            continue
        issue_date_raw = r[col_idx["issue_date"]]
        supply_amount = r[col_idx["supply_amount_krw"]]
        if issue_date_raw is None or supply_amount is None:
            skipped += 1
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
    return out, skipped
