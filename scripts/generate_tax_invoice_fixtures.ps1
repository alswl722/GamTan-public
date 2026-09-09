param(
    [string]$OutDir = "C:\Users\wkdud\OneDrive\바탕 화면\감탄\GamTan-dev\data\fixtures\tax_invoices\MAIN"
)

$ErrorActionPreference = "Stop"
$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$TmpHtml = Join-Path $env:TEMP "gamtan_invoice_render.html"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ── 세금계산서 금액 숫자칸 라벨 (원본 서식 그대로) ──
$SupplyLabels = @("백","십","억","천","백","십","만","천","백","십","일")   # 11칸
$VatLabels    = @("십","억","천","백","십","만","천","백","십","일")        # 10칸

function Get-AmountCellsHtml {
    param([long]$Amount, [string[]]$Labels)
    $digits = [string]$Amount
    $n = $Labels.Count
    $startIdx = $n - $digits.Length
    $out = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $n; $i++) {
        if ($i -ge $startIdx) {
            $d = $digits[$i - $startIdx]
            $out.Add("<div class=""data"">$d</div>")
        } else {
            $out.Add("<div>$($Labels[$i])</div>")
        }
    }
    return ($out -join "")
}

function New-InvoiceHtml {
    param($Inv)

    $supplyCells = Get-AmountCellsHtml -Amount $Inv.SupplyAmount -Labels $SupplyLabels
    $vatCells    = Get-AmountCellsHtml -Amount $Inv.VatAmount -Labels $VatLabels
    $total = $Inv.SupplyAmount + $Inv.VatAmount

    $qtyFmt   = "{0:N0}" -f $Inv.Qty
    $priceFmt = "{0:N0}" -f $Inv.UnitPrice
    $supplyFmt = "{0:N0}" -f $Inv.SupplyAmount
    $vatFmt    = "{0:N0}" -f $Inv.VatAmount
    $totalFmt  = "{0:N0}" -f $total

@"
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root{
    --paper:#fdfcf7; --ink-red:#c31c22; --ink-black:#1b1b1b;
    --badge-gray:#8b8b86; --page-bg:#e7e3da;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--page-bg);display:flex;justify-content:center;
    padding:26px 16px;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;}
  .sheet{position:relative;width:1080px;margin:0 auto;background:var(--paper);padding:30px 30px 16px;}
  .badge{position:absolute;top:6px;right:6px;font-size:11px;letter-spacing:.04em;color:var(--badge-gray);
    border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;}
  .meta-row{display:flex;justify-content:space-between;color:var(--ink-red);font-size:14px;font-weight:700;padding:0 4px 6px;}
  .frame{border:3px solid var(--ink-red);color:var(--ink-red);}
  .title-row{display:grid;grid-template-columns:1fr 230px;border-bottom:2px dotted var(--ink-red);}
  .title-row h1{margin:0;text-align:center;align-self:center;font-size:32px;letter-spacing:.5em;padding:12px 0 12px 20px;}
  .title-row h1 span.sub{letter-spacing:0;font-size:15px;margin-left:16px;}
  .book-no{border-left:2px dotted var(--ink-red);display:grid;grid-template-rows:1fr 1fr;}
  .book-no .r{display:flex;align-items:center;font-size:13px;font-weight:700;border-bottom:1px dotted var(--ink-red);}
  .book-no .r:last-child{border-bottom:none;}
  .book-no .r span.lbl{padding:0 10px;white-space:nowrap;}
  .book-no .r .cell{flex:1;border-left:1px dotted var(--ink-red);height:100%;display:flex;align-items:center;padding-left:10px;color:var(--ink-black);font-weight:400;}
  .parties{display:grid;grid-template-columns:1fr 1fr;border-bottom:2px dotted var(--ink-red);}
  .party{display:grid;grid-template-columns:34px 1fr;}
  .party + .party{border-left:2px dotted var(--ink-red);}
  .party .tag{display:flex;align-items:center;justify-content:center;writing-mode:vertical-rl;
    font-weight:700;font-size:15px;letter-spacing:.3em;border-right:1px dotted var(--ink-red);}
  .prow{display:grid;grid-template-columns:92px 1fr 26px 76px;border-bottom:1px dotted var(--ink-red);min-height:32px;}
  .prow:last-child{border-bottom:none;}
  .prow .lbl{display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;text-align:center;line-height:1.2;border-right:1px dotted var(--ink-red);padding:2px;}
  .prow .val{display:flex;align-items:center;padding:0 10px;color:var(--ink-black);font-weight:400;font-size:14px;}
  .prow .lbl2{display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;border-right:1px dotted var(--ink-red);border-left:1px dotted var(--ink-red);}
  .prow .val2{display:flex;align-items:center;padding:0 8px;color:var(--ink-black);font-size:14px;}
  .amount-head{display:grid;grid-template-columns:132px 1fr 1fr 90px;border-bottom:1px dotted var(--ink-red);}
  .amount-head > div{text-align:center;font-weight:700;font-size:14px;padding:5px 0;border-right:1px dotted var(--ink-red);}
  .amount-head > div:last-child{border-right:none;}
  .amount-sub{display:grid;grid-template-columns:32px 32px 32px 36px repeat(11,1fr) repeat(10,1fr) 90px;border-bottom:2px dotted var(--ink-red);}
  .amount-sub > div{text-align:center;font-size:12px;font-weight:700;border-right:1px dotted var(--ink-red);padding:4px 0;}
  .amount-sub > div.data{font-weight:400;color:var(--ink-black);font-size:15px;font-variant-numeric:tabular-nums;}
  .amount-sub > div:last-child{border-right:none;}
  .items{display:grid;grid-template-columns:30px 30px 1.4fr .8fr .6fr .8fr 1fr .8fr 1fr;border-bottom:2px solid var(--ink-red);}
  .items > div{border-right:1px dotted var(--ink-red);border-bottom:1px dotted var(--ink-red);display:flex;align-items:center;justify-content:center;font-size:13px;min-height:28px;}
  .items > div.h{font-weight:700;background:#fff;}
  .items > div:nth-child(9n){border-right:none;}
  .items > div.data{color:var(--ink-black);font-variant-numeric:tabular-nums;}
  .items > div.note{font-size:12px;color:var(--ink-black);font-weight:400;}
  .totals{display:grid;grid-template-columns:110px 1fr .8fr .8fr .8fr 1.3fr;}
  .totals > div{border-right:1px dotted var(--ink-red);display:flex;align-items:center;justify-content:center;min-height:42px;font-size:13px;font-weight:700;text-align:center;}
  .totals > div:last-child{border-right:none;}
  .totals .data{font-weight:400;color:var(--ink-black);font-size:14px;font-variant-numeric:tabular-nums;}
  .foot-row{display:flex;justify-content:space-between;font-size:11px;color:var(--ink-red);padding:6px 4px 0;}
</style></head>
<body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="meta-row"><span>[별지 제11호 서식]</span><span>(적색)</span></div>
  <div class="frame">
    <div class="title-row">
      <h1>세 금 계 산 서<span class="sub">(공급자 보관용)</span></h1>
      <div class="book-no">
        <div class="r"><span class="lbl">책&nbsp;번&nbsp;호</span><span class="cell"></span></div>
        <div class="r"><span class="lbl">일련번호</span><span class="cell">$($Inv.SerialNo)</span></div>
      </div>
    </div>
    <div class="parties">
      <div class="party">
        <div class="tag">공급자</div>
        <div class="rows">
          <div class="prow"><div class="lbl">등록번호</div><div class="val">$($Inv.SupplierBizNo)</div><div></div><div></div></div>
          <div class="prow"><div class="lbl">상&nbsp;&nbsp;호<br>(법인명)</div><div class="val">$($Inv.SupplierName)</div><div class="lbl2">성명</div><div class="val2">$($Inv.SupplierOwner) (인)</div></div>
          <div class="prow"><div class="lbl">사업장<br>주&nbsp;&nbsp;소</div><div class="val">$($Inv.SupplierAddr)</div><div></div><div></div></div>
          <div class="prow"><div class="lbl">업&nbsp;&nbsp;태</div><div class="val">$($Inv.SupplierType)</div><div class="lbl2">종목</div><div class="val2">$($Inv.SupplierItem)</div></div>
        </div>
      </div>
      <div class="party">
        <div class="tag">공급받는자</div>
        <div class="rows">
          <div class="prow"><div class="lbl">등록번호</div><div class="val">$($Inv.BuyerBizNo)</div><div></div><div></div></div>
          <div class="prow"><div class="lbl">상&nbsp;&nbsp;호<br>(법인명)</div><div class="val">$($Inv.BuyerName)</div><div class="lbl2">성명</div><div class="val2">$($Inv.BuyerOwner)</div></div>
          <div class="prow"><div class="lbl">사업장<br>주&nbsp;&nbsp;소</div><div class="val">$($Inv.BuyerAddr)</div><div></div><div></div></div>
          <div class="prow"><div class="lbl">업&nbsp;&nbsp;태</div><div class="val">$($Inv.BuyerType)</div><div class="lbl2">종목</div><div class="val2">$($Inv.BuyerItem)</div></div>
        </div>
      </div>
    </div>
    <div class="amount-head"><div>작&nbsp;&nbsp;성</div><div>공&nbsp;급&nbsp;가&nbsp;액</div><div>세&nbsp;&nbsp;액</div><div>비&nbsp;&nbsp;고</div></div>
    <div class="amount-sub">
      <div>$($Inv.Year.ToString().Substring(2))</div><div>$($Inv.Month)</div><div>$($Inv.Day)</div><div></div>
      $supplyCells
      $vatCells
      <div style="border-right:none;"></div>
    </div>
    <div class="items">
      <div class="h">월</div><div class="h">일</div><div class="h">품&nbsp;&nbsp;목</div><div class="h">규격</div><div class="h">수량</div><div class="h">단가</div><div class="h">공급가액</div><div class="h">세액</div><div class="h">비고</div>
      <div class="data">$($Inv.Month)</div><div class="data">$($Inv.Day)</div><div class="data">$($Inv.ItemName)</div><div class="data">$($Inv.Spec)</div><div class="data">$qtyFmt</div><div class="data">$priceFmt</div><div class="data">$supplyFmt</div><div class="data">$vatFmt</div><div class="note">$($Inv.Memo)</div>
      <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
      <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
      <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
    </div>
    <div class="totals">
      <div>합계금액</div><div class="data">$totalFmt</div><div>현금</div><div>수표</div><div>어음</div><div style="font-size:13px;font-weight:700;">위 금액을 <b style="color:var(--ink-red);">영수</b> 함</div>
    </div>
  </div>
  <div class="foot-row"><span>22226-28131일 &nbsp;'96.2.27 개정</span><span>182mm × 128mm 인쇄용지</span></div>
</div>
</body></html>
"@
}

# ── 부산: ○○정밀(MAIN) 2025년 1~3월 경유 세금계산서, 월 2~3건 ──
$Invoices = @(
    @{ Id="MAIN_2025-01_tax_invoice_diesel_01"; Year=2025; Month=1; Day=8;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=65; UnitPrice=1421; SupplyAmount=92365; VatAmount=9237;
       Memo="지게차 연료"; SerialNo="GB-2025-0108-1" },
    @{ Id="MAIN_2025-01_tax_invoice_diesel_02"; Year=2025; Month=1; Day=16;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=70; UnitPrice=1430; SupplyAmount=100100; VatAmount=10010;
       Memo="배송차량 주유"; SerialNo="GB-2025-0116-1" },
    @{ Id="MAIN_2025-01_tax_invoice_diesel_03"; Year=2025; Month=1; Day=27;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=60; UnitPrice=1421; SupplyAmount=85260; VatAmount=8526;
       Memo="지게차 연료"; SerialNo="GB-2025-0127-1" },

    @{ Id="MAIN_2025-02_tax_invoice_diesel_01"; Year=2025; Month=2; Day=10;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=75; UnitPrice=1449; SupplyAmount=108675; VatAmount=10868;
       Memo="지게차 연료"; SerialNo="GB-2025-0210-1" },
    @{ Id="MAIN_2025-02_tax_invoice_diesel_02"; Year=2025; Month=2; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=68; UnitPrice=1449; SupplyAmount=98532; VatAmount=9853;
       Memo="지게차 연료"; SerialNo="GB-2025-0224-1" },

    @{ Id="MAIN_2025-03_tax_invoice_diesel_01"; Year=2025; Month=3; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=58; UnitPrice=1414; SupplyAmount=82012; VatAmount=8201;
       Memo="지게차 연료"; SerialNo="GB-2025-0305-1" },
    @{ Id="MAIN_2025-03_tax_invoice_diesel_02"; Year=2025; Month=3; Day=14;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=62; UnitPrice=1420; SupplyAmount=88040; VatAmount=8804;
       Memo="배송차량 주유"; SerialNo="GB-2025-0314-1" },
    @{ Id="MAIN_2025-03_tax_invoice_diesel_03"; Year=2025; Month=3; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=50; UnitPrice=1414; SupplyAmount=70700; VatAmount=7070;
       Memo="지게차 연료"; SerialNo="GB-2025-0324-1" },

    @{ Id="MAIN_2025-04_tax_invoice_diesel_01"; Year=2025; Month=4; Day=7;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=62; UnitPrice=1376; SupplyAmount=85312; VatAmount=8531;
       Memo="지게차 연료"; SerialNo="GB-2025-0407-1" },
    @{ Id="MAIN_2025-04_tax_invoice_diesel_02"; Year=2025; Month=4; Day=15;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=68; UnitPrice=1385; SupplyAmount=94180; VatAmount=9418;
       Memo="배송차량 주유"; SerialNo="GB-2025-0415-1" },
    @{ Id="MAIN_2025-04_tax_invoice_diesel_03"; Year=2025; Month=4; Day=23;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=58; UnitPrice=1376; SupplyAmount=79808; VatAmount=7981;
       Memo="지게차 연료"; SerialNo="GB-2025-0423-1" },

    @{ Id="MAIN_2025-05_tax_invoice_diesel_01"; Year=2025; Month=5; Day=9;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=66; UnitPrice=1366; SupplyAmount=90156; VatAmount=9016;
       Memo="지게차 연료"; SerialNo="GB-2025-0509-1" },
    @{ Id="MAIN_2025-05_tax_invoice_diesel_02"; Year=2025; Month=5; Day=21;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=64; UnitPrice=1375; SupplyAmount=88000; VatAmount=8800;
       Memo="배송차량 주유"; SerialNo="GB-2025-0521-1" },

    @{ Id="MAIN_2025-06_tax_invoice_diesel_01"; Year=2025; Month=6; Day=6;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=60; UnitPrice=1369; SupplyAmount=82140; VatAmount=8214;
       Memo="지게차 연료"; SerialNo="GB-2025-0606-1" },
    @{ Id="MAIN_2025-06_tax_invoice_diesel_02"; Year=2025; Month=6; Day=14;
       SupplierName="경일주유소"; SupplierBizNo="402-19-58831"; SupplierOwner="한경일";
       SupplierAddr="경북 구미시 산동읍 강동로 77"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=65; UnitPrice=1378; SupplyAmount=89570; VatAmount=8957;
       Memo="배송차량 주유"; SerialNo="GB-2025-0614-1" },
    @{ Id="MAIN_2025-06_tax_invoice_diesel_03"; Year=2025; Month=6; Day=26;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=63; UnitPrice=1369; SupplyAmount=86247; VatAmount=8625;
       Memo="지게차 연료"; SerialNo="GB-2025-0626-1" },

    @{ Id="MAIN_2025-07_tax_invoice_diesel_01"; Year=2025; Month=7; Day=4;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=230; UnitPrice=1392; SupplyAmount=320160; VatAmount=32016;
       Memo="지게차 2대 증차로 사용량 급증"; SerialNo="GB-2025-0704-1" },
    @{ Id="MAIN_2025-07_tax_invoice_diesel_02"; Year=2025; Month=7; Day=15;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=70; UnitPrice=1400; SupplyAmount=98000; VatAmount=9800;
       Memo="배송차량 주유"; SerialNo="GB-2025-0715-1" },
    @{ Id="MAIN_2025-07_tax_invoice_diesel_03"; Year=2025; Month=7; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=225; UnitPrice=1392; SupplyAmount=313200; VatAmount=31320;
       Memo="지게차 증차분"; SerialNo="GB-2025-0724-1" },

    @{ Id="MAIN_2025-08_tax_invoice_diesel_01"; Year=2025; Month=8; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=220; UnitPrice=1396; SupplyAmount=307120; VatAmount=30712;
       Memo="지게차 연료"; SerialNo="GB-2025-0805-1" },
    @{ Id="MAIN_2025-08_tax_invoice_diesel_02"; Year=2025; Month=8; Day=14;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=68; UnitPrice=1404; SupplyAmount=95472; VatAmount=9547;
       Memo="배송차량 주유"; SerialNo="GB-2025-0814-1" },
    @{ Id="MAIN_2025-08_tax_invoice_diesel_03"; Year=2025; Month=8; Day=25;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=210; UnitPrice=1396; SupplyAmount=293160; VatAmount=29316;
       Memo="지게차 연료"; SerialNo="GB-2025-0825-1" },

    @{ Id="MAIN_2025-09_tax_invoice_diesel_01"; Year=2025; Month=9; Day=3;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=205; UnitPrice=1392; SupplyAmount=285360; VatAmount=28536;
       Memo="지게차 연료"; SerialNo="GB-2025-0903-1" },
    @{ Id="MAIN_2025-09_tax_invoice_diesel_02"; Year=2025; Month=9; Day=12;
       SupplierName="경일주유소"; SupplierBizNo="402-19-58831"; SupplierOwner="한경일";
       SupplierAddr="경북 구미시 산동읍 강동로 77"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=66; UnitPrice=1400; SupplyAmount=92400; VatAmount=9240;
       Memo="배송차량 주유"; SerialNo="GB-2025-0912-1" },
    @{ Id="MAIN_2025-09_tax_invoice_diesel_03"; Year=2025; Month=9; Day=22;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=195; UnitPrice=1392; SupplyAmount=271440; VatAmount=27144;
       Memo="지게차 연료"; SerialNo="GB-2025-0922-1" },

    @{ Id="MAIN_2025-10_tax_invoice_diesel_01"; Year=2025; Month=10; Day=6;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=190; UnitPrice=1397; SupplyAmount=265430; VatAmount=26543;
       Memo="지게차 연료"; SerialNo="GB-2025-1006-1" },
    @{ Id="MAIN_2025-10_tax_invoice_diesel_02"; Year=2025; Month=10; Day=16;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=70; UnitPrice=1405; SupplyAmount=98350; VatAmount=9835;
       Memo="배송차량 주유"; SerialNo="GB-2025-1016-1" },
    @{ Id="MAIN_2025-10_tax_invoice_diesel_03"; Year=2025; Month=10; Day=27;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=180; UnitPrice=1397; SupplyAmount=251460; VatAmount=25146;
       Memo="지게차 연료"; SerialNo="GB-2025-1027-1" },

    @{ Id="MAIN_2025-11_tax_invoice_diesel_01"; Year=2025; Month=11; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=188; UnitPrice=1472; SupplyAmount=276736; VatAmount=27674;
       Memo="지게차 연료"; SerialNo="GB-2025-1105-1" },
    @{ Id="MAIN_2025-11_tax_invoice_diesel_02"; Year=2025; Month=11; Day=14;
       SupplierName="경일주유소"; SupplierBizNo="402-19-58831"; SupplierOwner="한경일";
       SupplierAddr="경북 구미시 산동읍 강동로 77"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=65; UnitPrice=1480; SupplyAmount=96200; VatAmount=9620;
       Memo="배송차량 주유"; SerialNo="GB-2025-1114-1" },
    @{ Id="MAIN_2025-11_tax_invoice_diesel_03"; Year=2025; Month=11; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=182; UnitPrice=1472; SupplyAmount=267904; VatAmount=26790;
       Memo="지게차 연료"; SerialNo="GB-2025-1124-1" },

    @{ Id="MAIN_2025-12_tax_invoice_diesel_01"; Year=2025; Month=12; Day=4;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=195; UnitPrice=1500; SupplyAmount=292500; VatAmount=29250;
       Memo="지게차 연료"; SerialNo="GB-2025-1204-1" },
    @{ Id="MAIN_2025-12_tax_invoice_diesel_02"; Year=2025; Month=12; Day=12;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=72; UnitPrice=1508; SupplyAmount=108576; VatAmount=10858;
       Memo="배송차량 주유"; SerialNo="GB-2025-1212-1" },
    @{ Id="MAIN_2025-12_tax_invoice_diesel_03"; Year=2025; Month=12; Day=22;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=200; UnitPrice=1500; SupplyAmount=300000; VatAmount=30000;
       Memo="연말 지게차·난방 병행 사용"; SerialNo="GB-2025-1222-1" },

    # ── 2026년 1~8월: 2025년 7월 증차 이후 상승한 사용량이 새 기준선으로 정착(추가 급증 없음) ──
    @{ Id="MAIN_2026-01_tax_invoice_diesel_01"; Year=2026; Month=1; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=210; UnitPrice=1421; SupplyAmount=298410; VatAmount=29841;
       Memo="지게차 연료"; SerialNo="GB-2026-0105-1" },
    @{ Id="MAIN_2026-01_tax_invoice_diesel_02"; Year=2026; Month=1; Day=15;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=68; UnitPrice=1421; SupplyAmount=96628; VatAmount=9663;
       Memo="배송차량 주유"; SerialNo="GB-2026-0115-1" },
    @{ Id="MAIN_2026-01_tax_invoice_diesel_03"; Year=2026; Month=1; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=205; UnitPrice=1421; SupplyAmount=291305; VatAmount=29131;
       Memo="지게차 연료"; SerialNo="GB-2026-0124-1" },

    @{ Id="MAIN_2026-02_tax_invoice_diesel_01"; Year=2026; Month=2; Day=4;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=200; UnitPrice=1449; SupplyAmount=289800; VatAmount=28980;
       Memo="지게차 연료"; SerialNo="GB-2026-0204-1" },
    @{ Id="MAIN_2026-02_tax_invoice_diesel_02"; Year=2026; Month=2; Day=14;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=66; UnitPrice=1449; SupplyAmount=95634; VatAmount=9563;
       Memo="배송차량 주유"; SerialNo="GB-2026-0214-1" },
    @{ Id="MAIN_2026-02_tax_invoice_diesel_03"; Year=2026; Month=2; Day=23;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=198; UnitPrice=1449; SupplyAmount=286902; VatAmount=28690;
       Memo="지게차 연료"; SerialNo="GB-2026-0223-1" },

    @{ Id="MAIN_2026-03_tax_invoice_diesel_01"; Year=2026; Month=3; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=215; UnitPrice=1414; SupplyAmount=304010; VatAmount=30401;
       Memo="지게차 연료"; SerialNo="GB-2026-0305-1" },
    @{ Id="MAIN_2026-03_tax_invoice_diesel_02"; Year=2026; Month=3; Day=16;
       SupplierName="경일주유소"; SupplierBizNo="402-19-58831"; SupplierOwner="한경일";
       SupplierAddr="경북 구미시 산동읍 강동로 77"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=70; UnitPrice=1414; SupplyAmount=98980; VatAmount=9898;
       Memo="배송차량 주유"; SerialNo="GB-2026-0316-1" },
    @{ Id="MAIN_2026-03_tax_invoice_diesel_03"; Year=2026; Month=3; Day=25;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=208; UnitPrice=1414; SupplyAmount=294112; VatAmount=29411;
       Memo="지게차 연료"; SerialNo="GB-2026-0325-1" },

    @{ Id="MAIN_2026-04_tax_invoice_diesel_01"; Year=2026; Month=4; Day=6;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=220; UnitPrice=1376; SupplyAmount=302720; VatAmount=30272;
       Memo="지게차 연료"; SerialNo="GB-2026-0406-1" },
    @{ Id="MAIN_2026-04_tax_invoice_diesel_02"; Year=2026; Month=4; Day=15;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=72; UnitPrice=1376; SupplyAmount=99072; VatAmount=9907;
       Memo="배송차량 주유"; SerialNo="GB-2026-0415-1" },
    @{ Id="MAIN_2026-04_tax_invoice_diesel_03"; Year=2026; Month=4; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=215; UnitPrice=1376; SupplyAmount=295840; VatAmount=29584;
       Memo="지게차 연료"; SerialNo="GB-2026-0424-1" },

    @{ Id="MAIN_2026-05_tax_invoice_diesel_01"; Year=2026; Month=5; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=225; UnitPrice=1366; SupplyAmount=307350; VatAmount=30735;
       Memo="지게차 연료"; SerialNo="GB-2026-0505-1" },
    @{ Id="MAIN_2026-05_tax_invoice_diesel_02"; Year=2026; Month=5; Day=16;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=74; UnitPrice=1366; SupplyAmount=101084; VatAmount=10108;
       Memo="배송차량 주유"; SerialNo="GB-2026-0516-1" },
    @{ Id="MAIN_2026-05_tax_invoice_diesel_03"; Year=2026; Month=5; Day=26;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=218; UnitPrice=1366; SupplyAmount=297788; VatAmount=29779;
       Memo="지게차 연료"; SerialNo="GB-2026-0526-1" },

    @{ Id="MAIN_2026-06_tax_invoice_diesel_01"; Year=2026; Month=6; Day=4;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=230; UnitPrice=1369; SupplyAmount=314870; VatAmount=31487;
       Memo="지게차 연료"; SerialNo="GB-2026-0604-1" },
    @{ Id="MAIN_2026-06_tax_invoice_diesel_02"; Year=2026; Month=6; Day=14;
       SupplierName="경일주유소"; SupplierBizNo="402-19-58831"; SupplierOwner="한경일";
       SupplierAddr="경북 구미시 산동읍 강동로 77"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=76; UnitPrice=1369; SupplyAmount=104044; VatAmount=10404;
       Memo="배송차량 주유"; SerialNo="GB-2026-0614-1" },
    @{ Id="MAIN_2026-06_tax_invoice_diesel_03"; Year=2026; Month=6; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=222; UnitPrice=1369; SupplyAmount=303918; VatAmount=30392;
       Memo="지게차 연료"; SerialNo="GB-2026-0624-1" },

    @{ Id="MAIN_2026-07_tax_invoice_diesel_01"; Year=2026; Month=7; Day=5;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=235; UnitPrice=1392; SupplyAmount=327120; VatAmount=32712;
       Memo="지게차 연료"; SerialNo="GB-2026-0705-1" },
    @{ Id="MAIN_2026-07_tax_invoice_diesel_02"; Year=2026; Month=7; Day=15;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=78; UnitPrice=1392; SupplyAmount=108576; VatAmount=10858;
       Memo="배송차량 주유"; SerialNo="GB-2026-0715-1" },
    @{ Id="MAIN_2026-07_tax_invoice_diesel_03"; Year=2026; Month=7; Day=25;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=228; UnitPrice=1392; SupplyAmount=317376; VatAmount=31738;
       Memo="증차 1주년, 사용량 안정적으로 유지"; SerialNo="GB-2026-0725-1" },

    @{ Id="MAIN_2026-08_tax_invoice_diesel_01"; Year=2026; Month=8; Day=4;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=232; UnitPrice=1396; SupplyAmount=323872; VatAmount=32387;
       Memo="지게차 연료"; SerialNo="GB-2026-0804-1" },
    @{ Id="MAIN_2026-08_tax_invoice_diesel_02"; Year=2026; Month=8; Day=14;
       SupplierName="왕산주유소"; SupplierBizNo="611-08-93042"; SupplierOwner="최왕산";
       SupplierAddr="경북 구미시 왕산로 45"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="배송차량용"; Qty=77; UnitPrice=1396; SupplyAmount=107492; VatAmount=10749;
       Memo="배송차량 주유"; SerialNo="GB-2026-0814-1" },
    @{ Id="MAIN_2026-08_tax_invoice_diesel_03"; Year=2026; Month=8; Day=24;
       SupplierName="구미석유"; SupplierBizNo="105-25-77213"; SupplierOwner="정유민";
       SupplierAddr="경북 구미시 산동읍 임천로 210"; SupplierType="도소매"; SupplierItem="석유판매업";
       BuyerName="㈜○○정밀"; BuyerBizNo="220-81-45671"; BuyerOwner="이정밀";
       BuyerAddr="경북 구미시 공단로 88"; BuyerType="제조업"; BuyerItem="구조용 금속제품 제조";
       ItemName="경유"; Spec="지게차용"; Qty=225; UnitPrice=1396; SupplyAmount=314100; VatAmount=31410;
       Memo="지게차 연료"; SerialNo="GB-2026-0824-1" }
)

$manifest = New-Object System.Collections.Generic.List[string]
$manifest.Add("record_id,company_id,issue_date,supplier_name,item_name,spec,qty,unit,unit_price_krw,supply_amount_krw,vat_krw,total_krw,memo,file_format,file_name")

function Wait-ForFreshFile {
    param([string]$Path, [datetime]$Since, [int]$TimeoutSec = 15)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $Path) {
            $f = Get-Item $Path
            if ($f.LastWriteTime -ge $Since -and $f.Length -gt 0) { return $true }
        }
        Start-Sleep -Milliseconds 150
    }
    return $false
}

Add-Type -AssemblyName System.Drawing

$CompanyDisplayName = "○○정밀"
# pdf / jpg / png를 순환 배정 — 한 건당 한 포맷만 생성(회사가 스캔해서 PDF로 올리기도 하고
# 휴대폰으로 찍어 jpg/png로 올리기도 하는 실제 업로드 다양성을 반영).
$FormatCycle = @("pdf", "jpg", "png")

$idx = 0
foreach ($inv in $Invoices) {
    $html = New-InvoiceHtml -Inv $inv
    $safeKey = "$($inv.Year)$('{0:D2}' -f $inv.Month)$('{0:D2}' -f $inv.Day)_$idx"
    # 매 건마다 별도 임시 html/프로필을 써서 헤드리스 크롬 인스턴스 간 경쟁을 제거한다
    # (공유 파일 하나를 재사용했더니 크롬이 렌더링을 끝내기 전에 다음 건이 덮어써서
    #  파일명과 내용이 한 칸씩 밀리는 문제가 있었음).
    $invHtml = Join-Path $env:TEMP "gamtan_invoice_$safeKey.html"
    $profileDir = Join-Path $env:TEMP "gamtan_chrome_profile_$safeKey"
    Set-Content -Path $invHtml -Value $html -Encoding utf8

    $issueDate = "{0:D4}-{1:D2}-{2:D2}" -f $inv.Year, $inv.Month, $inv.Day
    $baseName = "${CompanyDisplayName}_${issueDate}_세금계산서_$($inv.ItemName)"
    $format = $FormatCycle[$idx % $FormatCycle.Count]
    $finalName = "$baseName.$format"
    $finalPath = Join-Path $OutDir $finalName

    if ($format -eq "pdf") {
        $t0 = Get-Date
        & $Chrome --headless --disable-gpu "--user-data-dir=$profileDir" --no-pdf-header-footer --print-to-pdf="$finalPath" "file:///$invHtml" 2>$null
        if (-not (Wait-ForFreshFile -Path $finalPath -Since $t0)) { Write-Warning "PDF 생성 지연/실패: $baseName" }
    } else {
        # 크롬 헤드리스 --screenshot=*.jpg 는 이 환경에서 응답이 없어(버전 호환 문제로 추정),
        # 항상 png로 캡처한 뒤 필요하면 System.Drawing으로 jpg 변환한다.
        $pngTmp = Join-Path $env:TEMP "gamtan_shot_$safeKey.png"
        $t1 = Get-Date
        & $Chrome --headless --disable-gpu "--user-data-dir=$profileDir" --window-size=1150,780 --screenshot="$pngTmp" "file:///$invHtml" 2>$null
        if (-not (Wait-ForFreshFile -Path $pngTmp -Since $t1)) {
            Write-Warning "이미지 생성 지연/실패: $baseName"
        } elseif ($format -eq "png") {
            Move-Item -Path $pngTmp -Destination $finalPath -Force
        } else {
            $bmp = [System.Drawing.Image]::FromFile($pngTmp)
            $jpgParams = New-Object System.Drawing.Imaging.EncoderParameters(1)
            $jpgParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [int64]88)
            $jpgCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq "image/jpeg" }
            $bmp.Save($finalPath, $jpgCodec, $jpgParams)
            $bmp.Dispose()
            Remove-Item -Path $pngTmp -Force -ErrorAction SilentlyContinue
        }
    }

    Remove-Item -Path $invHtml -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $profileDir -Recurse -Force -ErrorAction SilentlyContinue

    $total = $inv.SupplyAmount + $inv.VatAmount
    $manifest.Add("$baseName,MAIN,$issueDate,$($inv.SupplierName),$($inv.ItemName),$($inv.Spec),$($inv.Qty),L,$($inv.UnitPrice),$($inv.SupplyAmount),$($inv.VatAmount),$total,$($inv.Memo),$format,$finalName")

    Write-Host "생성됨: $finalName"
    $idx++
}

$manifestPath = Join-Path $OutDir "_manifest.csv"
Set-Content -Path $manifestPath -Value ($manifest -join "`n") -Encoding utf8

Write-Host ""
Write-Host "완료: $($Invoices.Count)건 생성 -> $OutDir"
