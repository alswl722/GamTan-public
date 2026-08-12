"""사장님 업로드 서류(PDF) + 마이데이터 연동자료 + 결측 시나리오 생성기.

감탄의 데이터 입력 경로 2가지를 분리해서 만든다 (docs/borrower-pcaf-data-plan.md
§ 하이브리드 입력 개념과 동일한 결):

1. 마이데이터 연동 (자동, 전체 기업 한 번에) — 사업자등록증명·부가세과표증명·
   표준재무제표증명·중소기업확인서·전기요금납부내역 5종. API로 자동 확인되는
   신원·재무 자료라 개별 서류가 아니라 표 하나(csv)로 낸다.
2. 사장 직접 업로드 (기업별·서류종류별 개별 PDF) — 세금계산서(연료 구매)·
   전기요금고지서·도시가스요금고지서. 실제 서비스에서 사장님이 한 장씩
   스캔·촬영해서 올리는 서류이므로 여기서도 회사×서류종류×월 단위로
   개별 PDF 파일을 만든다.

6개 기업(C001~C006, db/excel_loader가 읽는 전표_샘플·company_master 시트와
동일한 회사)에 대해 2025년 1~3월 서류를 만들되, 기업마다 다른 결측 패턴을
의도적으로 심는다 — "누가 뭘 안 냈는지" 한눈에 보려는 목적. db/seed_mock.py의
○○정밀(결손·이상치 데모 전용 기업)과는 별개 회사군이다.

python -m scripts.generate_upload_docs 로 실행. 항상 같은 파일을 재생성한다
(랜덤은 seed 고정).
"""
import csv
import os
import random

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
FONT = "HYGothic-Medium"
FONT_SERIF = "HYSMyeongJo-Medium"

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
DOCS_DIR = os.path.join(DATA_DIR, "uploaded_docs")
DOCS_MD = os.path.join(ROOT, "docs", "upload-scenarios.md")
MYDATA_CSV = os.path.join(DATA_DIR, "mydata_연동자료_전체기업.csv")

MONTHS = ["2025-01", "2025-02", "2025-03"]
DAYS_IN_MONTH = {"2025-01": 31, "2025-02": 28, "2025-03": 31}
GAS_SEASON = {"2025-01": 1.5, "2025-02": 1.4, "2025-03": 1.1}  # 동절기 가중

COMPANIES = {
    "C001": dict(name="구미정밀", region="경북 구미", industry="금속가공",
                 employees=18, fuels=["전기", "경유"], biznum="123-45-67890"),
    "C002": dict(name="대경부품", region="경북 경산", industry="전자부품",
                 employees=12, fuels=["전기", "LPG", "경유"], biznum="111-22-33333"),
    "C003": dict(name="성서테크", region="대구 달서", industry="표면처리",
                 employees=25, fuels=["전기", "경유", "도시가스"], biznum="444-55-66666"),
    "C004": dict(name="칠곡소재", region="경북 칠곡", industry="플라스틱 부품",
                 employees=9, fuels=["전기", "경유", "도시가스"], biznum="222-33-44444"),
    "C005": dict(name="포항이엔지", region="경북 포항", industry="표면처리",
                 employees=15, fuels=["전기", "경유", "휘발유"], biznum="555-66-77777"),
    "C006": dict(name="대구정공", region="대구 북구", industry="금속가공",
                 employees=11, fuels=["전기", "LPG", "도시가스", "경유"], biznum="666-77-88888"),
}

FUEL_SUPPLIER = {
    "경유": "구미에너지주유소", "휘발유": "대경오일", "LPG": "경북LPG",
}
FUEL_UNIT = {"경유": "L", "휘발유": "L", "LPG": "kg"}
FUEL_UNITPRICE = {"경유": 1400, "휘발유": 1580, "LPG": 1440}
FUEL_BASE_AMOUNT = {"경유": 600_000, "휘발유": 120_000, "LPG": 180_000}
ELEC_BASE_AMOUNT = 3_400_000
ELEC_BASE_KWH = 3000
GAS_BASE_AMOUNT = 900_000
GAS_BASE_M3 = 700
GAS_SUPPLIER = "구미도시가스"

# ── 회사별 결측 시나리오 (핵심) ─────────────────────────────────────────
# doc: "전기" | "도시가스" | 연료명("경유"·"휘발유"·"LPG")
# months: 실제로 "제출됨"으로 만들 월 목록. 회사의 fuels 목록에 있어도
#         여기서 뺀 월은 "미제출"(gap)로 남는다.
# note: 시나리오 한 줄 설명(문서용)
PRESENCE = {
    "C001": {
        "전기": (["2025-01", "2025-03"], "2월 전기고지서 업로드 깜빡함(단순 누락)"),
        "경유": (MONTHS, "정상 — 매달 빠짐없이 제출"),
    },
    "C002": {
        "전기": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "경유": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "LPG": (["2025-03"], "1~2월에도 LPG를 썼지만 연료 유형 체크를 안 해서 시스템이 결손으로도 못 잡음 — 3월에야 서류 등록 시작"),
    },
    "C003": {
        "전기": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "경유": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "도시가스": (["2025-01"], "2~3월 도시가스 고지서 결손 — 결손 감지 시나리오"),
    },
    "C004": {
        "전기": (MONTHS, "전기고지서만 제출, 나머지는 아예 낸 적 없음"),
        "경유": ([], "세금계산서 자체를 한 번도 업로드 안 함(전면 미제출)"),
        "도시가스": ([], "도시가스 고지서도 한 번도 업로드 안 함(전면 미제출)"),
    },
    "C005": {
        "전기": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "경유": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "휘발유": (MONTHS, "정상 — 매달 빠짐없이 제출(완비 벤치마크 기업)"),
    },
    "C006": {
        "전기": (MONTHS, "2월분은 업로드했으나 스캔 화질 불량으로 금액 인식 실패(파싱 실패 케이스)"),
        "LPG": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "도시가스": (MONTHS, "정상 — 매달 빠짐없이 제출"),
        "경유": (["2025-02"], "비정기 구매 — 2월만 발생(정상, 결측 아님)"),
    },
}
DEGRADED = {("C006", "전기", "2025-02")}  # 업로드는 됐으나 파싱 실패로 표시할 문서


def _rnd(co, doc, month):
    return random.Random(f"{co}-{doc}-{month}")


def _amount(base, size, r, season=1.0):
    return int(base * size * season * r.uniform(0.9, 1.1))


# ── PDF 드로잉 유틸 ──────────────────────────────────────────────────
def _draw_table(c, x, y, rows, col_widths, row_h=22, header=True):
    for i, row in enumerate(rows):
        yy = y - i * row_h
        c.setFont(FONT, 10 if not (header and i == 0) else 10)
        if header and i == 0:
            c.setFillGray(0.9)
            c.rect(x, yy - row_h + 6, sum(col_widths), row_h, fill=1, stroke=0)
            c.setFillGray(0)
        cx = x
        for val, w in zip(row, col_widths):
            c.drawString(cx + 4, yy - row_h + 12, str(val))
            cx += w
    c.setLineWidth(0.5)
    total_h = row_h * len(rows)
    cx = x
    for w in col_widths:
        c.line(cx, y + 6, cx, y - total_h + 6)
        cx += w
    c.line(cx, y + 6, cx, y - total_h + 6)
    for i in range(len(rows) + 1):
        yy = y + 6 - i * row_h
        c.line(x, yy, x + sum(col_widths), yy)


def _header(c, title, subtitle=""):
    c.setFont(FONT, 18)
    c.drawCentredString(A4[0] / 2, 780, title)
    if subtitle:
        c.setFont(FONT, 10)
        c.drawCentredString(A4[0] / 2, 762, subtitle)
    c.setLineWidth(1)
    c.line(50, 750, A4[0] - 50, 750)


def _footer_note(c):
    c.setFont(FONT, 8)
    c.setFillGray(0.5)
    c.drawString(50, 40, "본 문서는 감탄(GamTan) MVP 검증용 합성 데이터입니다. 실제 거래·기업 정보가 아닙니다.")
    c.setFillGray(0)


def make_electric_bill(path, co_id, co, month, degraded=False):
    r = _rnd(co_id, "전기", month)
    size = co["employees"] / 12
    kwh = round(ELEC_BASE_KWH * size * r.uniform(0.9, 1.1))
    amount = _amount(ELEC_BASE_AMOUNT, size, r)
    c = canvas.Canvas(path, pagesize=A4)
    _header(c, "전기요금 고지서", "한국전력공사")
    y = 700
    c.setFont(FONT, 11)
    c.drawString(50, y, f"고객명(사업장): {co['name']}  ({co['region']})")
    c.drawString(50, y - 20, f"사업자등록번호: {co['biznum']}")
    c.drawString(50, y - 40, f"청구월: {month}   계약종별: 산업용(을) 고압A")
    if degraded:
        c.setFont(FONT, 13)
        c.setFillGray(0.6)
        c.drawString(50, y - 90, "※ 스캔 화질 불량 — 사용량·금액 자동 인식 불가")
        c.setFillGray(0)
        rows = [
            ["항목", "값"],
            ["사용기간", f"{month}-01 ~ {month}-{DAYS_IN_MONTH[month]}"],
            ["사용량(kWh)", "▨▨▨ (판독 불가)"],
            ["청구금액(원)", "▨,▨▨▨,▨▨▨ (판독 불가)"],
        ]
    else:
        rows = [
            ["항목", "값"],
            ["사용기간", f"{month}-01 ~ {month}-{DAYS_IN_MONTH[month]}"],
            ["사용량(kWh)", f"{kwh:,}"],
            ["청구금액(원)", f"{amount:,}"],
        ]
    _draw_table(c, 50, y - 110, rows, [200, 260])
    _footer_note(c)
    c.save()
    return dict(company_id=co_id, company=co["name"], doc_type="전기고지서", month=month,
                amount_krw=None if degraded else amount, quantity=None if degraded else kwh,
                unit="kWh", degraded=degraded, file=os.path.basename(path))


def _split_amount(total, n, r):
    """월 총액을 n건으로 불균등 분할 (매번 똑같이 나눈 것처럼 보이지 않게)."""
    weights = [r.uniform(0.6, 1.4) for _ in range(n)]
    s = sum(weights)
    return [max(1, round(total * w / s)) for w in weights]


def _purchase_days(month, n, r):
    """한 달 안에서 n개의 서로 다른 구매일을 고르게 흩어 고른다."""
    dim = DAYS_IN_MONTH[month]
    days = set()
    tries = 0
    while len(days) < n and tries < 50:
        base = int((len(days) + 1) * dim / (n + 1))
        days.add(min(max(base + r.randint(-2, 2), 1), dim))
        tries += 1
    d = 1
    while len(days) < n:
        days.add(d)
        d += 1
    return sorted(days)


def make_fuel_invoice(path, co_id, co, fuel, month, day, amount):
    unit_price = FUEL_UNITPRICE[fuel]
    qty = round(amount / unit_price)
    vat = round(amount * 0.1)
    total = amount + vat
    supplier = FUEL_SUPPLIER[fuel]
    c = canvas.Canvas(path, pagesize=A4)
    _header(c, "전자세금계산서", f"공급자: {supplier}")
    y = 700
    c.setFont(FONT, 11)
    c.drawString(50, y, f"공급받는자: {co['name']}  ({co['biznum']})")
    c.drawString(50, y - 20, f"작성일자: {month}-{day:02d}")
    rows = [
        ["품목명", "규격", "수량", "단가(원)", "공급가액(원)"],
        [fuel, FUEL_UNIT[fuel], f"{qty:,}{FUEL_UNIT[fuel]}", f"{unit_price:,}", f"{amount:,}"],
    ]
    _draw_table(c, 50, y - 60, rows, [90, 60, 90, 90, 110])
    c.setFont(FONT, 11)
    c.drawString(50, y - 130, f"부가세: {vat:,}원   합계금액: {total:,}원")
    _footer_note(c)
    c.save()
    return dict(company_id=co_id, company=co["name"], doc_type=f"세금계산서_{fuel}", month=month,
                day=day, amount_krw=amount, quantity=qty, unit=FUEL_UNIT[fuel], degraded=False,
                file=os.path.basename(path))


def make_gas_bill(path, co_id, co, month):
    r = _rnd(co_id, "도시가스", month)
    size = co["employees"] / 12
    season = GAS_SEASON[month]
    amount = _amount(GAS_BASE_AMOUNT, size, r, season)
    m3 = round(GAS_BASE_M3 * size * season * r.uniform(0.9, 1.1))
    c = canvas.Canvas(path, pagesize=A4)
    _header(c, "도시가스 요금고지서", GAS_SUPPLIER)
    y = 700
    c.setFont(FONT, 11)
    c.drawString(50, y, f"고객명(사업장): {co['name']}  ({co['region']})")
    c.drawString(50, y - 20, f"사업자등록번호: {co['biznum']}")
    c.drawString(50, y - 40, f"사용월: {month}   용도: 산업용")
    rows = [
        ["항목", "값"],
        ["사용량(m³)", f"{m3:,}"],
        ["청구금액(원)", f"{amount:,}"],
    ]
    _draw_table(c, 50, y - 80, rows, [200, 260])
    _footer_note(c)
    c.save()
    return dict(company_id=co_id, company=co["name"], doc_type="도시가스고지서", month=month,
                amount_krw=amount, quantity=m3, unit="m3", degraded=False, file=os.path.basename(path))


# ── 마이데이터(자동 연동, 전체 기업 한 번에) ────────────────────────────
MYDATA_TEMPLATE = [
    ("국세청", "사업자등록증명", "기업 식별", "탄소 사용량 정보 없음"),
    ("국세청", "부가가치세과세표준증명", "매출 규모 확인", "품목별 에너지 사용량 없음"),
    ("국세청", "표준재무제표증명", "재무정보 확인", "은행 내부 여신 데이터와 별도 연동 필요"),
    ("중소벤처기업부", "중소기업확인서", "중소기업 여부 확인", "배출량 정보 없음"),
    ("한국전력공사", "전기요금 납부내역", "전기 자료 보조", "kWh 포함 여부 확인 필요 — 탄소 계산 핵심값 아님"),
]


def build_mydata_csv():
    rows = []
    doc_n = 1
    for co_id, co in COMPANIES.items():
        for provider, doc, use, limitation in MYDATA_TEMPLATE:
            rows.append(dict(doc_id=f"MD{doc_n:03d}", company_id=co_id, company_name=co["name"],
                              provider=provider, document_name=doc, collected_by="마이데이터",
                              collected_status="확인완료", used_for=use, limitation=limitation))
            doc_n += 1
    with open(MYDATA_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


# ── 사장 직접 업로드 PDF 일괄 생성 ──────────────────────────────────────
# 연료(경유·휘발유·LPG)는 실제로 한 달에 한 번만 사지 않는다 — 지게차·차량
# 주유는 주기적으로 여러 번 일어나므로 월 2~4건으로 쪼갠다. 전기·도시가스는
# 실제로 월 1회 청구되는 고지서라 그대로 월 1건 유지.
FUEL_PURCHASES_RANGE = (2, 4)


def build_upload_docs():
    manifest = []
    for co_id, co in COMPANIES.items():
        co_dir = os.path.join(DOCS_DIR, f"{co_id}_{co['name']}")
        os.makedirs(co_dir, exist_ok=True)
        for doc, (months, _note) in PRESENCE[co_id].items():
            for month in months:
                degraded = (co_id, doc, month) in DEGRADED
                suffix = "_저품질스캔" if degraded else ""
                if doc == "전기":
                    fname = f"전기고지서_{month}{suffix}.pdf"
                    rec = make_electric_bill(os.path.join(co_dir, fname), co_id, co, month, degraded)
                    manifest.append(rec)
                elif doc == "도시가스":
                    fname = f"도시가스고지서_{month}{suffix}.pdf"
                    rec = make_gas_bill(os.path.join(co_dir, fname), co_id, co, month)
                    manifest.append(rec)
                else:
                    r = _rnd(co_id, doc, month)
                    n = r.randint(*FUEL_PURCHASES_RANGE)
                    size = co["employees"] / 12
                    month_total = _amount(FUEL_BASE_AMOUNT[doc], size, r)
                    amounts = _split_amount(month_total, n, r)
                    days = _purchase_days(month, n, r)
                    for day, amt in zip(days, amounts):
                        fname = f"세금계산서_{doc}_{month}-{day:02d}{suffix}.pdf"
                        rec = make_fuel_invoice(os.path.join(co_dir, fname), co_id, co, doc,
                                                 month, day, amt)
                        manifest.append(rec)
    return manifest


# ── 결측 시나리오 문서 (한눈에 보기) ────────────────────────────────────
def build_scenario_md(manifest):
    lines = [
        "# 사장 직접 업로드 서류 — 결측 시나리오 매트릭스",
        "",
        "```text",
        "Status: synthetic-data",
        "Last updated: 2026-08-12",
        "Scope: data/uploaded_docs/ 의 개별 PDF가 어떤 결측 패턴을 시연하는지 한눈에 보기 위한 문서",
        "```",
        "",
        "> 마이데이터 연동자료(사업자등록증명 등 5종)는 `data/mydata_연동자료_전체기업.csv`",
        "> 하나로 전체 기업을 한 번에 담았다 — 자동 연동이라 개별 서류 개념이 없음.",
        "> 아래는 **사장이 직접 업로드하는** 세금계산서·전기고지서·도시가스고지서만 대상.",
        "",
        "## 회사별 한 줄 요약",
        "",
        "| 회사 | 결측 유형 | 시스템이 해야 할 반응 |",
        "| --- | --- | --- |",
    ]
    scenario_labels = {
        "C001": ("단순 누락 (전기 2월)", "결손 알림 + 사장에게 재업로드 요청"),
        "C002": ("연료 유형 미체크 (LPG 1~2월)", "체크 안 된 연료는 결손 알림 대상에서 제외됨 — 사장이 연료 체크를 해야 시스템이 인지 가능(§8 원칙 8)"),
        "C003": ("도시가스 결손 (2~3월)", "결손 감지 → 업종 평균 임시 보정 + 알림 + 품질등급 하향 표기(킬러씬 A와 동일 패턴)"),
        "C004": ("전면 미제출 (경유·도시가스 0건)", "연료 체크는 됐는데 서류가 아예 없음 → 강한 알림 필요, 업종 평균 보정 비중이 매우 커짐"),
        "C005": ("완비 (결측 없음)", "벤치마크/정상군 — Before/After 비교의 대조군으로 사용"),
        "C006": ("업로드했으나 파싱 실패 (전기 2월 저품질 스캔)", "OCR·금액 추출 실패 → 재업로드 요청(재제출 사유: 화질), 자동 반려 아님"),
    }
    for co_id, co in COMPANIES.items():
        label, action = scenario_labels[co_id]
        lines.append(f"| {co['name']}({co_id}) | {label} | {action} |")

    # 회사×서류종류×월별 실제 생성 건수 (연료 세금계산서는 월 2~4건으로 쪼갰음)
    counts: dict[tuple, int] = {}
    for rec in manifest:
        counts[(rec["company_id"], rec["doc_type"], rec["month"])] = \
            counts.get((rec["company_id"], rec["doc_type"], rec["month"]), 0) + 1

    lines += ["", "## 상세 매트릭스 (회사 × 서류종류 × 월)", "",
              "> 세금계산서는 월 1건이 아니라 실제 주유·구매 횟수만큼(2~4건) 나뉘어 있다 —",
              "> 아래 숫자는 해당 월에 실제로 생성된 PDF 건수.", ""]
    lines.append("| 회사 | 서류종류 | " + " | ".join(MONTHS) + " |")
    lines.append("| --- | --- | " + " | ".join(["---"] * len(MONTHS)) + " |")
    for co_id, co in COMPANIES.items():
        for doc, (months, note) in PRESENCE[co_id].items():
            doc_label = "전기고지서" if doc == "전기" else ("도시가스고지서" if doc == "도시가스" else f"세금계산서({doc})")
            cells = []
            for m in MONTHS:
                if m not in months:
                    cells.append("❌ 없음")
                elif (co_id, doc, m) in DEGRADED:
                    cells.append("⚠️ 업로드됨(파싱실패)")
                else:
                    n = counts.get((co_id, doc_label, m), 1)
                    cells.append(f"✅ {n}건" if n > 1 else "✅ 있음")
            lines.append(f"| {co['name']} | {doc_label} | " + " | ".join(cells) + " |")
            lines.append(f"| | *({note})* | | | |")

    lines += ["", "## 산출물", "", "```text",
              "data/mydata_연동자료_전체기업.csv         — 마이데이터 5종 × 6개 기업 = 30행",
              "data/uploaded_docs/<기업ID>_<기업명>/*.pdf — 서류종류_월[_저품질스캔].pdf",
              "```", "",
              f"생성 PDF 총 {len(manifest)}건. 재생성: `python -m scripts.generate_upload_docs`",
              "(seed 고정 — 항상 같은 파일이 나옴).", ""]

    with open(DOCS_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    mydata_rows = build_mydata_csv()
    print(f"[OK] 마이데이터 연동자료 {len(mydata_rows)}행 → {MYDATA_CSV}")

    manifest = build_upload_docs()
    print(f"[OK] 업로드 서류 PDF {len(manifest)}건 → {DOCS_DIR}")
    for co_id, co in COMPANIES.items():
        n = sum(1 for m in manifest if m["company_id"] == co_id)
        print(f"     - {co['name']}({co_id}): {n}건")

    build_scenario_md(manifest)
    print(f"[OK] 결측 시나리오 문서 → {DOCS_MD}")


if __name__ == "__main__":
    main()
