"""탄소리포트 2026년 시연 fixture 생성기 — ○○정밀 1~12월 PDF.

현행 텍스트 파서·결정론 룰·이상치 검출기의 실제 계약을 한 회사의 1년치 문서로
재현한다.

  1) 이상치(설명 가능형)  — 7월 경유 약 3,100L 일시 대량 구매. 평월 복귀형 고립
                             spike라 detector의 2.5× median·2× max-peer를 모두 통과하고,
                             최종 상태는 사장 확인 pending이다.
  2) 데이터 결손          — 3~5월 도시가스 고지서는 파일을 만들지 않는다.
  3) 일반 HITL 정확히 3건 — 2월 "유류대금"(R010, 수량·단가 미기재),
                             8월 전기 추정청구(당월 kWh 미기재),
                             12월 "공장용접용가스비"(R018, 가스 종류 미기재).
  4) 친환경 설비 1건      — 11월 "고효율인버터공조설비"(R031)로 설비금융 후보를 만든다.

세금계산서는 별지 제11호 적색 서식, 전기·도시가스는 청구서 계열 레이아웃이다.
Chrome headless ``--print-to-pdf``로 렌더하며 seed와 무관한 결정론적 standalone fixture다.

    .venv/bin/python -m scripts.generate_carbon_report_scenario_fixtures
"""
import calendar
import csv
import glob
import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR = os.path.join(ROOT, "data", "fixtures", "carbon_report_scenario")

YEAR = 2026
LAST_DAY = {month: calendar.monthrange(YEAR, month)[1] for month in range(1, 13)}


def _find_chrome() -> str:
    cands = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for candidate in cands:
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("Chrome/Chromium을 찾지 못했습니다 — 설치 경로를 _find_chrome()에 추가하세요.")


CHROME = _find_chrome()


def render_pdf(html: str, out_path: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        html_path = os.path.join(td, "doc.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        # --user-data-dir를 주면 일부 macOS 샌드박스에서 프로파일 잠금 단계가 멈춘다.
        subprocess.run(
            [
                CHROME,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_path}",
                f"file://{html_path}",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    if not (os.path.exists(out_path) and os.path.getsize(out_path) > 0):
        raise RuntimeError(f"PDF 렌더 실패: {out_path}")


# ══════════════════════ 회사·거래처 정보 ══════════════════════
COMPANY = dict(
    name="○○정밀",
    biznum="514-81-42615",
    ceo="김도현",
    addr="경북 구미시 산동읍 첨단기업1로 42",
    biz_type="제조업",
    biz_item="구조용 금속제품",
    region="경북 구미시",
    cust_no_elec="0312-4471-2",
    cust_no_gas="08-2245-3390",
)
DIESEL_SUPPLIERS = [
    dict(
        name="구미석유",
        biznum="502-11-33042",
        owner="박정수",
        addr="경북 구미시 산동읍 신당로 55",
        spec="지게차용",
    ),
    dict(
        name="왕산주유소",
        biznum="513-25-71880",
        owner="이경호",
        addr="경북 구미시 검성로 210",
        spec="배송차량용",
    ),
]
FACILITY_SUPPLIER = dict(
    name="대성설비",
    biznum="514-81-77203",
    owner="정우진",
    addr="대구 달서구 성서공단로 123",
    biz_type="도소매",
    biz_item="냉난방설비",
)
INDUSTRIAL_GAS_SUPPLIER = dict(
    name="구미산업가스",
    biznum="513-81-12026",
    owner="이현수",
    addr="경북 구미시 3공단1로 118",
    biz_type="도소매",
    biz_item="산업용가스",
)
GAS_SUPPLIER = "대성에너지"
DIESEL_PRICE = {
    1: 1421,
    2: 1449,
    3: 1414,
    4: 1376,
    5: 1366,
    6: 1369,
    7: 1392,
    8: 1396,
    9: 1392,
    10: 1397,
    11: 1472,
    12: 1500,
}
ELEC_PRICE_PER_KWH = 150
GAS_PRICE_PER_M3 = 800
GAS_INDEX_START = 480_000

# 전기·가스 값은 VAT 전 요금 원금이며 PDF/manifest에는 10%를 더한 청구금액이 기록된다.
# 경유 값은 세금계산서 공급가액이다. 8~12월 경유는 평월(약 400~500L)로 복귀한다.
MONTHS = {
    1: dict(diesel=654_000, gas=1_240_000, gas_item="도시가스(동절기난방)", elec=3_420_000),
    2: dict(
        diesel=612_000,
        d_item="유류대금",
        d_memo="유류비 정산분 — 경유/휘발유 구분 불가",
        d_hitl=True,
        gas=1_150_000,
        gas_item="도시가스요금",
        elec=3_180_000,
    ),
    3: dict(diesel=589_000, gas=None, elec=3_560_000),
    4: dict(diesel=601_000, gas=None, elec=3_210_000),
    5: dict(diesel=628_000, gas=None, elec=3_390_000),
    6: dict(diesel=643_000, gas=480_000, gas_item="도시가스", elec=3_710_000),
    7: dict(
        diesel=4_320_000,
        d_item="지게차경유-일시대량구매",
        d_memo="생산라인 집중 가동 대비 일시 대량 구매",
        d_anomaly=True,
        gas=390_000,
        gas_item="도시가스",
        elec=4_120_000,
    ),
    8: dict(
        diesel=650_000,
        gas=320_000,
        gas_item="도시가스",
        elec=4_340_000,
        elec_estimated=True,
    ),
    9: dict(diesel=620_000, gas=410_000, gas_item="도시가스", elec=3_870_000),
    10: dict(diesel=640_000, gas=720_000, gas_item="도시가스(동절기시작)", elec=3_650_000),
    11: dict(
        diesel=660_000,
        gas=1_050_000,
        gas_item="도시가스(난방)",
        elec=3_480_000,
        facility=dict(
            item="고효율인버터공조설비",
            spec="15HP인버터형",
            amount=5_000_000,
            memo="노후 공조설비 교체(에너지효율 1등급) — K-택소노미 적합성 검토 대상",
        ),
    ),
    12: dict(
        diesel=675_000,
        gas=1_380_000,
        gas_item="도시가스(동절기난방)",
        elec=3_290_000,
        review_invoice=dict(
            item="공장용접용가스비",
            amount=320_000,
            memo="용접 공정 가스 정산분 — 가스 종류 상세 미기재",
        ),
    ),
}


def _split(total: int, n: int) -> list[int]:
    base = total // n
    out = [base] * n
    out[-1] += total - base * n
    if n == 2:
        shift = int(total * 0.06)
        out = [out[0] - shift, out[1] + shift]
    return out


# ══════════════════════ 세금계산서 (별지 제11호 적색) ══════════════════════
_SUP_LABELS = ["백", "십", "억", "천", "백", "십", "만", "천", "백", "십", "일"]
_VAT_LABELS = ["십", "억", "천", "백", "십", "만", "천", "백", "십", "일"]


def _amount_cells(amount: int, labels: list[str]) -> str:
    digits = str(amount)
    start = len(labels) - len(digits)
    out = []
    for i, label in enumerate(labels):
        if i >= start:
            out.append(f'<div class="data">{digits[i - start]}</div>')
        else:
            out.append(f"<div>{label}</div>")
    return "".join(out)


def invoice_html(inv: dict) -> str:
    supply, vat = inv["supply"], inv["vat"]
    total = supply + vat
    qty_fmt = f"{inv['qty']:,}" if inv.get("qty") is not None else "-"
    price_fmt = f"{inv['unit_price']:,}" if inv.get("unit_price") is not None else "-"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  :root{{--paper:#fdfcf7;--ink-red:#c31c22;--ink-black:#1b1b1b;--badge-gray:#8b8b86;--page-bg:#e7e3da;}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--page-bg);display:flex;justify-content:center;padding:26px 16px;font-family:"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;}}
  .sheet{{position:relative;width:1080px;margin:0 auto;background:var(--paper);padding:30px 30px 16px;}}
  .badge{{position:absolute;top:6px;right:6px;font-size:11px;color:var(--badge-gray);border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;}}
  .meta-row{{display:flex;justify-content:space-between;color:var(--ink-red);font-size:14px;font-weight:700;padding:0 4px 6px;}}
  .frame{{border:3px solid var(--ink-red);color:var(--ink-red);}}
  .title-row{{display:grid;grid-template-columns:1fr 230px;border-bottom:2px dotted var(--ink-red);}}
  .title-row h1{{margin:0;text-align:center;align-self:center;font-size:32px;letter-spacing:.5em;padding:12px 0 12px 20px;}}
  .title-row h1 span.sub{{letter-spacing:0;font-size:15px;margin-left:16px;}}
  .book-no{{border-left:2px dotted var(--ink-red);display:grid;grid-template-rows:1fr 1fr;}}
  .book-no .r{{display:flex;align-items:center;font-size:13px;font-weight:700;border-bottom:1px dotted var(--ink-red);}}
  .book-no .r:last-child{{border-bottom:none;}}
  .book-no .r span.lbl{{padding:0 10px;white-space:nowrap;}}
  .book-no .r .cell{{flex:1;border-left:1px dotted var(--ink-red);height:100%;display:flex;align-items:center;padding-left:10px;color:var(--ink-black);font-weight:400;}}
  .parties{{display:grid;grid-template-columns:1fr 1fr;border-bottom:2px dotted var(--ink-red);}}
  .party{{display:grid;grid-template-columns:34px 1fr;}}
  .party + .party{{border-left:2px dotted var(--ink-red);}}
  .party .tag{{display:flex;align-items:center;justify-content:center;writing-mode:vertical-rl;font-weight:700;font-size:15px;letter-spacing:.3em;border-right:1px dotted var(--ink-red);}}
  .prow{{display:grid;grid-template-columns:92px 1fr 26px 76px;border-bottom:1px dotted var(--ink-red);min-height:32px;}}
  .prow:last-child{{border-bottom:none;}}
  .prow .lbl{{display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;text-align:center;line-height:1.2;border-right:1px dotted var(--ink-red);padding:2px;}}
  .prow .val{{display:flex;align-items:center;padding:0 10px;color:var(--ink-black);font-weight:400;font-size:14px;}}
  .prow .lbl2{{display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;border-right:1px dotted var(--ink-red);border-left:1px dotted var(--ink-red);}}
  .prow .val2{{display:flex;align-items:center;padding:0 8px;color:var(--ink-black);font-size:14px;}}
  .amount-head{{display:grid;grid-template-columns:132px 1fr 1fr 90px;border-bottom:1px dotted var(--ink-red);}}
  .amount-head > div{{text-align:center;font-weight:700;font-size:14px;padding:5px 0;border-right:1px dotted var(--ink-red);}}
  .amount-head > div:last-child{{border-right:none;}}
  .amount-sub{{display:grid;grid-template-columns:32px 32px 32px 36px repeat(11,1fr) repeat(10,1fr) 90px;border-bottom:2px dotted var(--ink-red);}}
  .amount-sub > div{{text-align:center;font-size:12px;font-weight:700;border-right:1px dotted var(--ink-red);padding:4px 0;}}
  .amount-sub > div.data{{font-weight:400;color:var(--ink-black);font-size:15px;font-variant-numeric:tabular-nums;}}
  .amount-sub > div:last-child{{border-right:none;}}
  .items{{display:grid;grid-template-columns:30px 30px 1.4fr .8fr .6fr .8fr 1fr .8fr 1fr;border-bottom:2px solid var(--ink-red);}}
  .items > div{{border-right:1px dotted var(--ink-red);border-bottom:1px dotted var(--ink-red);display:flex;align-items:center;justify-content:center;font-size:13px;min-height:28px;}}
  .items > div.h{{font-weight:700;background:#fff;}}
  .items > div:nth-child(9n){{border-right:none;}}
  .items > div.data{{color:var(--ink-black);font-variant-numeric:tabular-nums;}}
  .items > div:nth-child(12){{font-size:11px;white-space:nowrap;}}
  .items > div.note{{font-size:12px;color:var(--ink-black);font-weight:400;}}
  .totals{{display:grid;grid-template-columns:110px 1fr .8fr .8fr .8fr 1.3fr;}}
  .totals > div{{border-right:1px dotted var(--ink-red);display:flex;align-items:center;justify-content:center;min-height:42px;font-size:13px;font-weight:700;text-align:center;}}
  .totals > div:last-child{{border-right:none;}}
  .totals .data{{font-weight:400;color:var(--ink-black);font-size:14px;font-variant-numeric:tabular-nums;}}
  .parser-meta{{font-size:11px;color:var(--ink-black);padding:5px 4px 0;}}
  .foot-row{{display:flex;justify-content:space-between;font-size:11px;color:var(--ink-red);padding:4px 4px 0;}}
</style></head><body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="meta-row"><span>[별지 제11호 서식]</span><span>(적색)</span></div>
  <div class="frame">
    <div class="title-row">
      <h1>세 금 계 산 서<span class="sub">(공급자 보관용)</span></h1>
      <div class="book-no">
        <div class="r"><span class="lbl">책&nbsp;번&nbsp;호</span><span class="cell"></span></div>
        <div class="r"><span class="lbl">일련번호</span><span class="cell">{inv['serial']}</span></div>
      </div>
    </div>
    <div class="parties">
      <div class="party"><div class="tag">공급자</div><div class="rows">
        <div class="prow"><div class="lbl">등록번호</div><div class="val">{inv['sup_bizno']}</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">상&nbsp;&nbsp;호<br>(법인명)</div><div class="val">{inv['sup_name']}</div><div class="lbl2">성명</div><div class="val2">{inv['sup_owner']} (인)</div></div>
        <div class="prow"><div class="lbl">사업장<br>주&nbsp;&nbsp;소</div><div class="val">{inv['sup_addr']}</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">업&nbsp;&nbsp;태</div><div class="val">{inv['sup_type']}</div><div class="lbl2">종목</div><div class="val2">{inv['sup_item']}</div></div>
      </div></div>
      <div class="party"><div class="tag">공급받는자</div><div class="rows">
        <div class="prow"><div class="lbl">등록번호</div><div class="val">{COMPANY['biznum']}</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">상&nbsp;&nbsp;호<br>(법인명)</div><div class="val">{COMPANY['name']}</div><div class="lbl2">성명</div><div class="val2">{COMPANY['ceo']}</div></div>
        <div class="prow"><div class="lbl">사업장<br>주&nbsp;&nbsp;소</div><div class="val">{COMPANY['addr']}</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">업&nbsp;&nbsp;태</div><div class="val">{COMPANY['biz_type']}</div><div class="lbl2">종목</div><div class="val2">{COMPANY['biz_item']}</div></div>
      </div></div>
    </div>
    <div class="amount-head"><div>작&nbsp;&nbsp;성</div><div>공&nbsp;급&nbsp;가&nbsp;액</div><div>세&nbsp;&nbsp;액</div><div>비&nbsp;&nbsp;고</div></div>
    <div class="amount-sub">
      <div>{str(inv['year'])[2:]}</div><div>{inv['month']}</div><div>{inv['day']}</div><div></div>
      {_amount_cells(supply, _SUP_LABELS)}
      {_amount_cells(vat, _VAT_LABELS)}
      <div style="border-right:none;"></div>
    </div>
    <div class="items">
      <div class="h">월</div><div class="h">일</div><div class="h">품&nbsp;&nbsp;목</div><div class="h">규격</div><div class="h">수량</div><div class="h">단가</div><div class="h">공급가액</div><div class="h">세액</div><div class="h">비고</div>
      <div class="data">{inv['month']}</div><div class="data">{inv['day']}</div><div class="data">{inv['item']}</div><div class="data">{inv['spec']}</div><div class="data">{qty_fmt}</div><div class="data">{price_fmt}</div><div class="data">{supply:,}</div><div class="data">{vat:,}</div><div class="note">{inv['memo']}</div>
      <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
      <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
    </div>
    <div class="totals"><div>합계금액</div><div class="data">{total:,}</div><div>현금</div><div>수표</div><div>어음</div><div style="font-size:13px;font-weight:700;">위 금액을 <b style="color:var(--ink-red);">영수</b>함</div></div>
  </div>
  <div class="parser-meta">공급자: {inv['sup_name']}</div>
  <div class="foot-row"><span>22226-28131일 &nbsp;'96.2.27 개정</span><span>182mm × 128mm 인쇄용지</span></div>
</div>
</body></html>"""


# ══════════════════════ 전기요금 청구서 (한전) ══════════════════════
def elec_bill_html(inv: dict) -> str:
    amt_fmt = f"{inv['billed']:,}"
    if inv["kwh"] is not None:
        diff = inv["kwh"] - inv["prev_kwh"]
        usage_inline = f'<div class="usage-inline">사용량(kWh): {inv["kwh"]:,}</div>'
        usage_cell = f'<td class="num">{inv["kwh"]:,} kWh</td>'
        prev_cell = f'<td>{inv["prev_kwh"]:,} kWh</td>'
        diff_cell = f'<td>{"+" if diff >= 0 else ""}{diff:,} kWh</td>'
        note_html = ""
    else:
        # 숫자+kWh 토큰을 문서 전체에서 없애 table fallback이 전월 값을 당월로 오인하지 않게 한다.
        usage_inline = ""
        usage_cell = '<td class="num" style="color:#b23b3b;font-size:14px;">검침 확인 지연</td>'
        prev_cell = "<td>확인 중</td>"
        diff_cell = "<td>확인 중</td>"
        note_html = (
            '<div class="est-note">※ 이번 달은 원격검침 장애로 실사용량이 확인되지 않아, '
            '직전월 실적 기준 <b>추정 청구</b>됩니다. 익월 정산 시 차액이 반영됩니다.</div>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  :root{{--blue:#0b5ea8;--blue-dark:#083f73;--teal:#00a19a;--paper:#fff;--text:#1e2530;--muted:#6b7684;--line:#dbe2e8;--panel:#f3f7fa;--badge-gray:#8b8b86;}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:#e7ebee;display:flex;justify-content:center;padding:26px 16px;font-family:"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;color:var(--text);}}
  .sheet{{position:relative;width:860px;background:var(--paper);box-shadow:0 1px 3px rgba(0,0,0,.12);}}
  .badge{{position:absolute;bottom:10px;right:14px;font-size:11px;color:var(--badge-gray);border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;z-index:2;}}
  .head{{background:linear-gradient(135deg,var(--blue) 0%,var(--blue-dark) 100%);color:#fff;padding:22px 30px;display:flex;justify-content:space-between;align-items:flex-end;}}
  .head .org{{font-size:13px;letter-spacing:.08em;opacity:.85;margin-bottom:6px;}}
  .head h1{{margin:0;font-size:26px;letter-spacing:.06em;}}
  .head .period{{text-align:right;font-size:13px;line-height:1.6;}}
  .head .period b{{font-size:17px;display:block;}}
  .body{{padding:26px 30px 30px;}}
  .cust{{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:20px;}}
  .cust .row{{display:grid;grid-template-columns:96px 1fr;border-bottom:1px solid var(--line);}}
  .cust .row:last-child{{border-bottom:none;}}
  .cust .lbl{{background:var(--panel);color:var(--muted);font-size:12.5px;display:flex;align-items:center;padding:9px 10px;border-right:1px solid var(--line);}}
  .cust .val{{display:flex;align-items:center;padding:9px 12px;font-size:13.5px;}}
  .cust .col{{border-right:1px solid var(--line);}}
  .cust .col:last-child{{border-right:none;}}
  .usage-title{{font-size:14px;font-weight:700;color:var(--blue-dark);margin:0 0 8px;padding-left:8px;border-left:4px solid var(--teal);}}
  .usage-inline{{font-size:13px;font-weight:700;color:var(--blue-dark);margin:0 0 8px;}}
  table.usage{{width:100%;border-collapse:collapse;margin-bottom:10px;font-size:13.5px;}}
  table.usage th{{background:var(--panel);color:var(--muted);font-weight:700;font-size:12.5px;padding:9px 8px;border:1px solid var(--line);text-align:center;}}
  table.usage td{{padding:10px 8px;border:1px solid var(--line);text-align:center;font-variant-numeric:tabular-nums;}}
  table.usage td.num{{font-size:16px;font-weight:700;color:var(--blue-dark);}}
  .est-note{{font-size:12px;color:#b23b3b;background:#fdeeee;border:1px solid #f0c9c9;border-radius:6px;padding:8px 12px;margin-bottom:18px;}}
  .charges{{width:100%;border-collapse:collapse;margin-bottom:22px;font-size:13.5px;}}
  .charges td{{padding:8px 10px;border-bottom:1px dashed var(--line);}}
  .charges td.k{{color:var(--muted);}} .charges td.v{{text-align:right;font-variant-numeric:tabular-nums;}}
  .charges tr:last-child td{{border-bottom:none;}}
  .total{{display:flex;justify-content:space-between;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 20px;margin-bottom:16px;}}
  .total .lbl{{font-size:14px;font-weight:700;color:var(--blue-dark);}}
  .total .amt{{font-size:26px;font-weight:800;color:var(--blue-dark);font-variant-numeric:tabular-nums;}}
  .due{{font-size:12.5px;color:var(--muted);text-align:right;}}
  .foot{{border-top:1px solid var(--line);padding-top:12px;font-size:11.5px;color:var(--muted);display:flex;justify-content:space-between;}}
</style></head><body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="head">
    <div><div class="org">한국전력공사 · KOREA ELECTRIC POWER CORP.</div><h1>전 기 요 금 청 구 서</h1></div>
    <div class="period">청구월<b>{inv['year']}년 {inv['month']}월분</b></div>
  </div>
  <div class="body">
    <div class="cust">
      <div class="col">
        <div class="row"><div class="lbl">고객번호</div><div class="val">{COMPANY['cust_no_elec']}</div></div>
        <div class="row"><div class="lbl">사용자</div><div class="val">{COMPANY['name']}</div></div>
        <div class="row"><div class="lbl">사용장소</div><div class="val">{COMPANY['addr']}</div></div>
      </div>
      <div class="col">
        <div class="row"><div class="lbl">계약종별</div><div class="val">산업용(을) 고압A 선택2</div></div>
        <div class="row"><div class="lbl">사용기간</div><div class="val">{inv['year']}-{inv['month']:02d}-01 ~ {inv['year']}-{inv['month']:02d}-{LAST_DAY[inv['month']]}</div></div>
        <div class="row"><div class="lbl">검침일</div><div class="val">{inv['year']}-{inv['month']:02d}-{LAST_DAY[inv['month']]}</div></div>
      </div>
    </div>
    <div class="usage-title">사용량 내역</div>
    {usage_inline}
    <table class="usage"><tr><th>당월 사용량</th><th>전월 사용량</th><th>전월 대비</th><th>계약전력</th></tr>
      <tr>{usage_cell}{prev_cell}{diff_cell}<td>250 kW</td></tr></table>
    {note_html}
    <div class="usage-title">요금 내역</div>
    <table class="charges">
      <tr><td class="k">기본요금</td><td class="v">{inv['base_fee']:,} 원</td></tr>
      <tr><td class="k">전력량요금</td><td class="v">{inv['energy_fee']:,} 원</td></tr>
      <tr><td class="k">부가가치세 및 전력기금</td><td class="v">{inv['tax']:,} 원</td></tr>
    </table>
    <div class="total"><div class="lbl">이번달 청구금액</div><div class="amt">{amt_fmt} 원</div></div>
    <div class="due">납기일: {inv['due']} · 미납 시 연체료가 부과될 수 있습니다</div>
    <div class="foot"><span>고객센터 국번없이 123</span><span>발행일 {inv['issue']}</span></div>
  </div>
</div>
</body></html>"""


# ══════════════════════ 도시가스 요금고지서 ══════════════════════
def gas_bill_html(inv: dict) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  :root{{--g:#1f7a4d;--g-dark:#125233;--amber:#e08a1e;--paper:#fff;--text:#1e2530;--muted:#6b7684;--line:#dde5e0;--panel:#f2f8f4;--badge-gray:#8b8b86;}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:#e8ede9;display:flex;justify-content:center;padding:26px 16px;font-family:"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;color:var(--text);}}
  .sheet{{position:relative;width:860px;background:var(--paper);box-shadow:0 1px 3px rgba(0,0,0,.12);}}
  .badge{{position:absolute;bottom:10px;right:14px;font-size:11px;color:var(--badge-gray);border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;z-index:2;}}
  .head{{background:linear-gradient(135deg,var(--g) 0%,var(--g-dark) 100%);color:#fff;padding:22px 30px;display:flex;justify-content:space-between;align-items:flex-end;}}
  .head .org{{font-size:13px;letter-spacing:.06em;opacity:.9;margin-bottom:6px;}}
  .head h1{{margin:0;font-size:25px;letter-spacing:.05em;}}
  .head .period{{text-align:right;font-size:13px;line-height:1.6;}}
  .head .period b{{font-size:17px;display:block;}}
  .body{{padding:26px 30px 30px;}}
  .cust{{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:20px;}}
  .cust .row{{display:grid;grid-template-columns:96px 1fr;border-bottom:1px solid var(--line);}}
  .cust .row:last-child{{border-bottom:none;}}
  .cust .lbl{{background:var(--panel);color:var(--muted);font-size:12.5px;display:flex;align-items:center;padding:9px 10px;border-right:1px solid var(--line);}}
  .cust .val{{display:flex;align-items:center;padding:9px 12px;font-size:13.5px;}}
  .cust .col{{border-right:1px solid var(--line);}}
  .cust .col:last-child{{border-right:none;}}
  .t{{font-size:14px;font-weight:700;color:var(--g-dark);margin:0 0 8px;padding-left:8px;border-left:4px solid var(--amber);}}
  .usage-inline{{font-size:13px;font-weight:700;color:var(--g-dark);margin:0 0 8px;}}
  table.u{{width:100%;border-collapse:collapse;margin-bottom:18px;font-size:13.5px;}}
  table.u th{{background:var(--panel);color:var(--muted);font-weight:700;font-size:12.5px;padding:9px 8px;border:1px solid var(--line);text-align:center;}}
  table.u td{{padding:10px 8px;border:1px solid var(--line);text-align:center;font-variant-numeric:tabular-nums;}}
  table.u td.num{{font-size:16px;font-weight:700;color:var(--g-dark);}}
  .charges{{width:100%;border-collapse:collapse;margin-bottom:22px;font-size:13.5px;}}
  .charges td{{padding:8px 10px;border-bottom:1px dashed var(--line);}}
  .charges td.k{{color:var(--muted);}} .charges td.v{{text-align:right;font-variant-numeric:tabular-nums;}}
  .charges tr:last-child td{{border-bottom:none;}}
  .total{{display:flex;justify-content:space-between;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 20px;margin-bottom:16px;}}
  .total .lbl{{font-size:14px;font-weight:700;color:var(--g-dark);}}
  .total .amt{{font-size:26px;font-weight:800;color:var(--g-dark);font-variant-numeric:tabular-nums;}}
  .due{{font-size:12.5px;color:var(--muted);text-align:right;}}
  .foot{{border-top:1px solid var(--line);padding-top:12px;font-size:11.5px;color:var(--muted);display:flex;justify-content:space-between;}}
</style></head><body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="head">
    <div><div class="org">{GAS_SUPPLIER} · 도시가스 공급사업자</div><h1>도 시 가 스 요 금 고 지 서</h1></div>
    <div class="period">사용월<b>{inv['year']}년 {inv['month']}월분</b></div>
  </div>
  <div class="body">
    <div class="cust">
      <div class="col">
        <div class="row"><div class="lbl">고객번호</div><div class="val">{COMPANY['cust_no_gas']}</div></div>
        <div class="row"><div class="lbl">사용자</div><div class="val">{COMPANY['name']}</div></div>
        <div class="row"><div class="lbl">사용장소</div><div class="val">{COMPANY['addr']}</div></div>
      </div>
      <div class="col">
        <div class="row"><div class="lbl">용도</div><div class="val">산업용(일반용2)</div></div>
        <div class="row"><div class="lbl">품목 표기</div><div class="val">{inv['item']}</div></div>
        <div class="row"><div class="lbl">검침일</div><div class="val">{inv['year']}-{inv['month']:02d}-{LAST_DAY[inv['month']]}</div></div>
      </div>
    </div>
    <div class="t">사용량 내역</div>
    <div class="usage-inline">사용량(m³): {inv['m3']:,}</div>
    <table class="u"><tr><th>당월 지침</th><th>전월 지침</th><th>사용량</th><th>보정계수</th></tr>
      <tr><td>{inv['cur_index']:,}</td><td>{inv['prev_index']:,}</td><td class="num">{inv['m3']:,} m³</td><td>1.0000</td></tr></table>
    <div class="t">요금 내역</div>
    <table class="charges">
      <tr><td class="k">기본요금</td><td class="v">{inv['base_fee']:,} 원</td></tr>
      <tr><td class="k">사용요금 ({inv['m3']:,} m³)</td><td class="v">{inv['use_fee']:,} 원</td></tr>
      <tr><td class="k">부가가치세</td><td class="v">{inv['vat']:,} 원</td></tr>
    </table>
    <div class="total"><div class="lbl">이번달 청구금액</div><div class="amt">{inv['billed']:,} 원</div></div>
    <div class="due">납기일: {inv['due']}</div>
    <div class="foot"><span>{GAS_SUPPLIER} 고객센터 1544-0000</span><span>발행일 {inv['issue']}</span></div>
  </div>
</div>
</body></html>"""


# ══════════════════════ 오케스트레이션 ══════════════════════
def _next_billing_date(month: int, day: int) -> str:
    """다음 달 날짜를 쓰되 12월분은 fixture 연도 밖으로 넘어가지 않게 연말로 고정."""
    if month == 12:
        return f"{YEAR}-12-{LAST_DAY[12]:02d}"
    return f"{YEAR}-{month + 1:02d}-{day:02d}"


def build_diesel(month: int, spec: dict, manifest: list[dict]) -> None:
    if spec.get("d_anomaly"):
        big = round(spec["diesel"] * 0.78)
        parts = [
            (spec["d_item"], big, spec["d_memo"], False),
            ("배송차량경유", spec["diesel"] - big, "배송차량 연료", False),
        ]
    elif spec.get("d_hitl"):
        first, second = _split(spec["diesel"], 2)
        parts = [
            (spec["d_item"], first, spec["d_memo"], True),
            ("배송차량경유", second, "배송차량 연료", False),
        ]
    else:
        first, second = _split(spec["diesel"], 2)
        parts = [
            ("지게차경유", first, "지게차 연료", False),
            ("배송차량경유", second, "배송차량 연료", False),
        ]

    for i, (item, supply, memo, is_hitl) in enumerate(parts):
        supplier = DIESEL_SUPPLIERS[i]
        price = DIESEL_PRICE[month]
        qty = None if is_hitl else round(supply / price)
        vat = round(supply * 0.1)
        day = (8, 22)[i]
        inv = dict(
            year=YEAR,
            month=month,
            day=day,
            serial=f"CRS-{YEAR}{month:02d}-{i + 1}",
            sup_bizno=supplier["biznum"],
            sup_name=supplier["name"],
            sup_owner=supplier["owner"],
            sup_addr=supplier["addr"],
            sup_type="도소매",
            sup_item="석유판매업",
            item=item,
            spec="-" if is_hitl else supplier["spec"],
            qty=qty,
            unit_price=None if is_hitl else price,
            supply=supply,
            vat=vat,
            memo=memo,
        )
        fname = f"{COMPANY['name']}_{YEAR}-{month:02d}-{day:02d}_세금계산서_경유.pdf"
        render_pdf(invoice_html(inv), os.path.join(OUT_DIR, fname))
        manifest.append(
            dict(
                file=fname,
                doc_type="세금계산서(경유)",
                year_month=f"{YEAR}-{month:02d}",
                issue_date=f"{YEAR}-{month:02d}-{day:02d}",
                supplier=supplier["name"],
                item=item,
                quantity=qty if qty is not None else "",
                unit="",
                supply_amount_krw=supply,
                is_estimated=False,
                scenario=(
                    "이상치(사장확인대기)"
                    if spec.get("d_anomaly") and i == 0
                    else "HITL-연료애매"
                    if is_hitl
                    else "정상"
                ),
            )
        )


def build_facility(month: int, fac: dict, manifest: list[dict]) -> None:
    supply = fac["amount"]
    vat = round(supply * 0.1)
    day = 12
    inv = dict(
        year=YEAR,
        month=month,
        day=day,
        serial=f"CRS-FAC-{YEAR}{month:02d}",
        sup_bizno=FACILITY_SUPPLIER["biznum"],
        sup_name=FACILITY_SUPPLIER["name"],
        sup_owner=FACILITY_SUPPLIER["owner"],
        sup_addr=FACILITY_SUPPLIER["addr"],
        sup_type=FACILITY_SUPPLIER["biz_type"],
        sup_item=FACILITY_SUPPLIER["biz_item"],
        item=fac["item"],
        spec=fac["spec"],
        qty=1,
        unit_price=supply,
        supply=supply,
        vat=vat,
        memo=fac["memo"],
    )
    fname = f"{COMPANY['name']}_{YEAR}-{month:02d}-{day:02d}_세금계산서_설비.pdf"
    render_pdf(invoice_html(inv), os.path.join(OUT_DIR, fname))
    manifest.append(
        dict(
            file=fname,
            doc_type="세금계산서(설비)",
            year_month=f"{YEAR}-{month:02d}",
            issue_date=f"{YEAR}-{month:02d}-{day:02d}",
            supplier=FACILITY_SUPPLIER["name"],
            item=fac["item"],
            quantity=1,
            unit="",
            supply_amount_krw=supply,
            is_estimated=False,
            scenario="친환경설비(R031·K-택소노미)",
        )
    )


def build_review_invoice(month: int, review: dict, manifest: list[dict]) -> None:
    """가스 종류가 명시되지 않아 R018 일반 HITL로 가는 별도 세금계산서 1건."""
    supply = review["amount"]
    vat = round(supply * 0.1)
    day = 15
    inv = dict(
        year=YEAR,
        month=month,
        day=day,
        serial=f"CRS-HITL-{YEAR}{month:02d}",
        sup_bizno=INDUSTRIAL_GAS_SUPPLIER["biznum"],
        sup_name=INDUSTRIAL_GAS_SUPPLIER["name"],
        sup_owner=INDUSTRIAL_GAS_SUPPLIER["owner"],
        sup_addr=INDUSTRIAL_GAS_SUPPLIER["addr"],
        sup_type=INDUSTRIAL_GAS_SUPPLIER["biz_type"],
        sup_item=INDUSTRIAL_GAS_SUPPLIER["biz_item"],
        item=review["item"],
        spec="-",
        qty=None,
        unit_price=None,
        supply=supply,
        vat=vat,
        memo=review["memo"],
    )
    fname = f"{COMPANY['name']}_{YEAR}-{month:02d}-{day:02d}_세금계산서_용접가스.pdf"
    render_pdf(invoice_html(inv), os.path.join(OUT_DIR, fname))
    manifest.append(
        dict(
            file=fname,
            doc_type="세금계산서(용접가스)",
            year_month=f"{YEAR}-{month:02d}",
            issue_date=f"{YEAR}-{month:02d}-{day:02d}",
            supplier=INDUSTRIAL_GAS_SUPPLIER["name"],
            item=review["item"],
            quantity="",
            unit="",
            supply_amount_krw=supply,
            is_estimated=False,
            scenario="HITL-가스종류불명(R018)",
        )
    )


def build_elec(month: int, spec: dict, manifest: list[dict]) -> None:
    pretax = spec["elec"]
    estimated = bool(spec.get("elec_estimated"))
    billed = round(pretax * 1.1)
    kwh = None if estimated else round(pretax / ELEC_PRICE_PER_KWH)
    prev_kwh = round(MONTHS[month - 1]["elec"] / ELEC_PRICE_PER_KWH) if month > 1 else 22_000
    base_fee = 300_000
    energy_fee = round((kwh if kwh is not None else prev_kwh) * 89.5)
    tax = billed - base_fee - energy_fee
    inv = dict(
        year=YEAR,
        month=month,
        kwh=kwh,
        prev_kwh=prev_kwh,
        billed=billed,
        base_fee=base_fee,
        energy_fee=energy_fee,
        tax=tax,
        due=_next_billing_date(month, 25),
        issue=_next_billing_date(month, 5),
    )
    fname = f"{COMPANY['name']}_{YEAR}-{month:02d}_전기요금고지서.pdf"
    render_pdf(elec_bill_html(inv), os.path.join(OUT_DIR, fname))
    manifest.append(
        dict(
            file=fname,
            doc_type="전기요금고지서",
            year_month=f"{YEAR}-{month:02d}",
            issue_date=f"{YEAR}-{month:02d}-{LAST_DAY[month]:02d}",
            supplier="한국전력공사",
            item="전기요금 (산업용 을)",
            quantity="" if estimated else kwh,
            unit="" if estimated else "kWh",
            supply_amount_krw=billed,
            is_estimated=estimated,
            scenario="HITL-추정청구(물량미확인)" if estimated else "정상",
        )
    )


_GAS_INDEX = {"cur": GAS_INDEX_START}


def build_gas(month: int, spec: dict, manifest: list[dict]) -> None:
    if spec.get("gas") is None:
        manifest.append(
            dict(
                file="(파일 없음)",
                doc_type="도시가스요금고지서",
                year_month=f"{YEAR}-{month:02d}",
                issue_date="",
                supplier=GAS_SUPPLIER,
                item="",
                quantity="",
                unit="m3",
                supply_amount_krw="",
                is_estimated=False,
                scenario="데이터 결손",
            )
        )
        return

    pretax = spec["gas"]
    m3 = round(pretax / GAS_PRICE_PER_M3)
    prev_index = _GAS_INDEX["cur"]
    cur_index = prev_index + m3
    _GAS_INDEX["cur"] = cur_index
    base_fee = 12_000
    use_fee = pretax - base_fee
    vat = round(pretax * 0.1)
    billed = pretax + vat
    inv = dict(
        year=YEAR,
        month=month,
        item=spec["gas_item"],
        m3=m3,
        prev_index=prev_index,
        cur_index=cur_index,
        base_fee=base_fee,
        use_fee=use_fee,
        vat=vat,
        billed=billed,
        due=_next_billing_date(month, 20),
        issue=_next_billing_date(month, 3),
    )
    fname = f"{COMPANY['name']}_{YEAR}-{month:02d}_도시가스요금고지서.pdf"
    render_pdf(gas_bill_html(inv), os.path.join(OUT_DIR, fname))
    manifest.append(
        dict(
            file=fname,
            doc_type="도시가스요금고지서",
            year_month=f"{YEAR}-{month:02d}",
            issue_date=f"{YEAR}-{month:02d}-{LAST_DAY[month]:02d}",
            supplier="도시가스",
            item="도시가스",
            quantity=m3,
            unit="m3",
            supply_amount_krw=billed,
            is_estimated=False,
            scenario="정상",
        )
    )


def main() -> None:
    if os.path.isdir(OUT_DIR):
        # 연도와 무관하게 기존 PDF를 전부 지워 2025 산출물이 남지 않게 한다.
        for path in glob.glob(os.path.join(OUT_DIR, "*.pdf")):
            os.remove(path)
    os.makedirs(OUT_DIR, exist_ok=True)
    _GAS_INDEX["cur"] = GAS_INDEX_START
    manifest: list[dict] = []

    for month, spec in MONTHS.items():
        build_diesel(month, spec, manifest)
        build_gas(month, spec, manifest)
        build_elec(month, spec, manifest)
        if spec.get("facility"):
            build_facility(month, spec["facility"], manifest)
        if spec.get("review_invoice"):
            build_review_invoice(month, spec["review_invoice"], manifest)
        print(f"  {YEAR}-{month:02d} 완료")

    with open(os.path.join(OUT_DIR, "_manifest.csv"), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(manifest)

    pdfs = [row for row in manifest if row["file"] != "(파일 없음)"]
    missing = [row for row in manifest if row["file"] == "(파일 없음)"]
    print(
        f"\n[OK] PDF {len(pdfs)}건 + 결손표기 {len(missing)}건 → {OUT_DIR}  "
        f"(렌더러: {os.path.basename(CHROME)})"
    )
    for row in manifest:
        if row["scenario"] != "정상":
            print(f"     - {row['year_month']} {row['doc_type']:16s} {row['scenario']}")


if __name__ == "__main__":
    main()
