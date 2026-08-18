$ErrorActionPreference = "Stop"
$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$DataRoot = "C:\Users\wkdud\OneDrive\바탕 화면\감탄\GamTan-dev\data\fixtures"
Add-Type -AssemblyName System.Drawing

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

function Render-ToFile {
    param([string]$Html, [string]$FinalPath, [string]$Format, [string]$SafeKey, [int]$W = 1150, [int]$H = 780)
    $invHtml = Join-Path $env:TEMP "gamtan_r_$SafeKey.html"
    $profileDir = Join-Path $env:TEMP "gamtan_p_$SafeKey"
    Set-Content -Path $invHtml -Value $Html -Encoding utf8
    if ($Format -eq "pdf") {
        $t0 = Get-Date
        & $Chrome --headless --disable-gpu "--user-data-dir=$profileDir" --no-pdf-header-footer --print-to-pdf="$FinalPath" "file:///$invHtml" 2>$null
        if (-not (Wait-ForFreshFile -Path $FinalPath -Since $t0)) { Write-Warning "PDF 실패: $FinalPath" }
    } else {
        $pngTmp = Join-Path $env:TEMP "gamtan_s_$SafeKey.png"
        $t1 = Get-Date
        & $Chrome --headless --disable-gpu "--user-data-dir=$profileDir" --window-size=$W,$H --screenshot="$pngTmp" "file:///$invHtml" 2>$null
        if (-not (Wait-ForFreshFile -Path $pngTmp -Since $t1)) {
            Write-Warning "이미지 실패: $FinalPath"
        } elseif ($Format -eq "png") {
            Move-Item -Path $pngTmp -Destination $FinalPath -Force
        } else {
            $bmp = [System.Drawing.Image]::FromFile($pngTmp)
            $p = New-Object System.Drawing.Imaging.EncoderParameters(1)
            $p.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [int64]88)
            $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq "image/jpeg" }
            $bmp.Save($FinalPath, $codec, $p)
            $bmp.Dispose()
            Remove-Item -Path $pngTmp -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -Path $invHtml -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $profileDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ══════════════════════════ 세금계산서 템플릿 ══════════════════════════
$SupplyLabels = @("백","십","억","천","백","십","만","천","백","십","일")
$VatLabels    = @("십","억","천","백","십","만","천","백","십","일")

function Get-AmountCellsHtml {
    param([long]$Amount, [string[]]$Labels)
    $digits = [string]$Amount
    $n = $Labels.Count
    $startIdx = $n - $digits.Length
    $out = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $n; $i++) {
        if ($i -ge $startIdx) { $out.Add("<div class=""data"">$($digits[$i - $startIdx])</div>") }
        else { $out.Add("<div>$($Labels[$i])</div>") }
    }
    return ($out -join "")
}

function New-InvoiceHtml {
    param($Inv)
    $supplyCells = Get-AmountCellsHtml -Amount $Inv.SupplyAmount -Labels $SupplyLabels
    $vatCells    = Get-AmountCellsHtml -Amount $Inv.VatAmount -Labels $VatLabels
    $total = $Inv.SupplyAmount + $Inv.VatAmount
    $qtyFmt = "{0:N0}" -f $Inv.Qty; $priceFmt = "{0:N0}" -f $Inv.UnitPrice
    $supplyFmt = "{0:N0}" -f $Inv.SupplyAmount; $vatFmt = "{0:N0}" -f $Inv.VatAmount; $totalFmt = "{0:N0}" -f $total
@"
<!doctype html><html><head><meta charset="utf-8"><style>
  :root{--paper:#fdfcf7;--ink-red:#c31c22;--ink-black:#1b1b1b;--badge-gray:#8b8b86;--page-bg:#e7e3da;}
  *{box-sizing:border-box;}
  body{margin:0;background:var(--page-bg);display:flex;justify-content:center;padding:26px 16px;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;}
  .sheet{position:relative;width:1080px;margin:0 auto;background:var(--paper);padding:30px 30px 16px;}
  .badge{position:absolute;top:6px;right:6px;font-size:11px;color:var(--badge-gray);border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;}
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
  .party .tag{display:flex;align-items:center;justify-content:center;writing-mode:vertical-rl;font-weight:700;font-size:15px;letter-spacing:.3em;border-right:1px dotted var(--ink-red);}
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
</style></head><body>
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
      <div class="party"><div class="tag">공급자</div><div class="rows">
        <div class="prow"><div class="lbl">등록번호</div><div class="val">$($Inv.SupplierBizNo)</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">상&nbsp;&nbsp;호<br>(법인명)</div><div class="val">$($Inv.SupplierName)</div><div class="lbl2">성명</div><div class="val2">$($Inv.SupplierOwner) (인)</div></div>
        <div class="prow"><div class="lbl">사업장<br>주&nbsp;&nbsp;소</div><div class="val">$($Inv.SupplierAddr)</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">업&nbsp;&nbsp;태</div><div class="val">$($Inv.SupplierType)</div><div class="lbl2">종목</div><div class="val2">$($Inv.SupplierItem)</div></div>
      </div></div>
      <div class="party"><div class="tag">공급받는자</div><div class="rows">
        <div class="prow"><div class="lbl">등록번호</div><div class="val">$($Inv.BuyerBizNo)</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">상&nbsp;&nbsp;호<br>(법인명)</div><div class="val">$($Inv.BuyerName)</div><div class="lbl2">성명</div><div class="val2">$($Inv.BuyerOwner)</div></div>
        <div class="prow"><div class="lbl">사업장<br>주&nbsp;&nbsp;소</div><div class="val">$($Inv.BuyerAddr)</div><div></div><div></div></div>
        <div class="prow"><div class="lbl">업&nbsp;&nbsp;태</div><div class="val">$($Inv.BuyerType)</div><div class="lbl2">종목</div><div class="val2">$($Inv.BuyerItem)</div></div>
      </div></div>
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
    </div>
    <div class="totals"><div>합계금액</div><div class="data">$totalFmt</div><div>현금</div><div>수표</div><div>어음</div><div style="font-size:13px;font-weight:700;">위 금액을 <b style="color:var(--ink-red);">영수</b> 함</div></div>
  </div>
  <div class="foot-row"><span>22226-28131일 &nbsp;'96.2.27 개정</span><span>182mm × 128mm 인쇄용지</span></div>
</div>
</body></html>
"@
}

# ══════════════════════════ 전기요금고지서 템플릿 (null=검침 확인 지연) ══════════════════════════
function New-BillHtml {
    param($Inv)
    $amtFmt = "{0:N0}" -f $Inv.BilledAmount
    if ($Inv.UsageKwh -ne $null) {
        $usageCell = "<td class=""num"">$('{0:N0}' -f $Inv.UsageKwh) kWh</td>"
        $diff = $Inv.UsageKwh - $Inv.PrevUsageKwh
        $diffSign = if ($diff -ge 0) { "+" } else { "" }
        $diffCell = "<td>$diffSign$('{0:N0}' -f $diff) kWh</td>"
        $noteHtml = ""
    } else {
        $usageCell = "<td class=""num"" style=""color:#b23b3b;font-size:14px;"">검침 확인 지연</td>"
        $diffCell = "<td>-</td>"
        $noteHtml = "<div class=""est-note"">※ 이번 달은 원격검침 장애로 실사용량이 확인되지 않아, 직전월 실적 기준 <b>추정 청구</b>됩니다. 익월 정산 시 차액이 반영됩니다.</div>"
    }
    $prevFmt = "{0:N0}" -f $Inv.PrevUsageKwh
@"
<!doctype html><html><head><meta charset="utf-8"><style>
  :root{--blue:#0b5ea8;--blue-dark:#083f73;--teal:#00a19a;--paper:#ffffff;--text:#1e2530;--muted:#6b7684;--line:#dbe2e8;--panel:#f3f7fa;--badge-gray:#8b8b86;}
  *{box-sizing:border-box;}
  body{margin:0;background:#e7ebee;display:flex;justify-content:center;padding:26px 16px;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:var(--text);}
  .sheet{position:relative;width:860px;background:var(--paper);box-shadow:0 1px 3px rgba(0,0,0,.12);}
  .badge{position:absolute;top:10px;right:14px;font-size:11px;color:var(--badge-gray);border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;z-index:2;}
  .head{background:linear-gradient(135deg,var(--blue) 0%,var(--blue-dark) 100%);color:#fff;padding:22px 30px;display:flex;justify-content:space-between;align-items:flex-end;}
  .head .org{font-size:13px;letter-spacing:.08em;opacity:.85;margin-bottom:6px;}
  .head h1{margin:0;font-size:26px;letter-spacing:.06em;}
  .head .period{text-align:right;font-size:13px;line-height:1.6;}
  .head .period b{font-size:17px;display:block;}
  .body{padding:26px 30px 30px;}
  .cust{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:20px;}
  .cust .row{display:grid;grid-template-columns:96px 1fr;border-bottom:1px solid var(--line);}
  .cust .row:last-child{border-bottom:none;}
  .cust .lbl{background:var(--panel);color:var(--muted);font-size:12.5px;display:flex;align-items:center;padding:9px 10px;border-right:1px solid var(--line);}
  .cust .val{display:flex;align-items:center;padding:9px 12px;font-size:13.5px;}
  .cust .col{border-right:1px solid var(--line);}
  .cust .col:last-child{border-right:none;}
  .usage-title{font-size:14px;font-weight:700;color:var(--blue-dark);margin:0 0 8px;padding-left:8px;border-left:4px solid var(--teal);}
  table.usage{width:100%;border-collapse:collapse;margin-bottom:10px;font-size:13.5px;}
  table.usage th{background:var(--panel);color:var(--muted);font-weight:700;font-size:12.5px;padding:9px 8px;border:1px solid var(--line);text-align:center;}
  table.usage td{padding:10px 8px;border:1px solid var(--line);text-align:center;font-variant-numeric:tabular-nums;}
  table.usage td.num{font-size:16px;font-weight:700;color:var(--blue-dark);}
  .est-note{font-size:12px;color:#b23b3b;background:#fdeeee;border:1px solid #f0c9c9;border-radius:6px;padding:8px 12px;margin-bottom:18px;}
  .charges{width:100%;border-collapse:collapse;margin-bottom:22px;font-size:13.5px;}
  .charges td{padding:8px 10px;border-bottom:1px dashed var(--line);}
  .charges td.k{color:var(--muted);} .charges td.v{text-align:right;font-variant-numeric:tabular-nums;}
  .charges tr:last-child td{border-bottom:none;}
  .total{display:flex;justify-content:space-between;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 20px;margin-bottom:16px;}
  .total .lbl{font-size:14px;font-weight:700;color:var(--blue-dark);}
  .total .amt{font-size:26px;font-weight:800;color:var(--blue-dark);font-variant-numeric:tabular-nums;}
  .due{font-size:12.5px;color:var(--muted);text-align:right;}
  .foot{border-top:1px solid var(--line);padding-top:12px;font-size:11.5px;color:var(--muted);display:flex;justify-content:space-between;}
</style></head><body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="head">
    <div><div class="org">한국전력공사 · KOREA ELECTRIC POWER CORP.</div><h1>전 기 요 금 청 구 서</h1></div>
    <div class="period">청구월<b>$($Inv.Year)년 $($Inv.Month)월분</b></div>
  </div>
  <div class="body">
    <div class="cust">
      <div class="col">
        <div class="row"><div class="lbl">고객번호</div><div class="val">$($Inv.CustomerNumber)</div></div>
        <div class="row"><div class="lbl">사용자</div><div class="val">$($Inv.CompanyName)</div></div>
        <div class="row"><div class="lbl">사용장소</div><div class="val">$($Inv.SiteAddr)</div></div>
      </div>
      <div class="col">
        <div class="row"><div class="lbl">계약종별</div><div class="val">$($Inv.ContractType)</div></div>
        <div class="row"><div class="lbl">사용기간</div><div class="val">$($Inv.PeriodStart) ~ $($Inv.PeriodEnd)</div></div>
        <div class="row"><div class="lbl">검침일</div><div class="val">$($Inv.MeterDate)</div></div>
      </div>
    </div>
    <div class="usage-title">사용량 내역</div>
    <table class="usage"><tr><th>당월 사용량</th><th>전월 사용량</th><th>전월 대비</th><th>계약전력</th></tr>
      <tr>$usageCell<td>${prevFmt} kWh</td>$diffCell<td>$($Inv.ContractPower) kW</td></tr></table>
    $noteHtml
    <div class="usage-title">요금 내역</div>
    <table class="charges">
      <tr><td class="k">기본요금</td><td class="v">$('{0:N0}' -f $Inv.BaseFee) 원</td></tr>
      <tr><td class="k">전력량요금</td><td class="v">$('{0:N0}' -f $Inv.EnergyFee) 원</td></tr>
      <tr><td class="k">부가가치세 및 전력기금</td><td class="v">$('{0:N0}' -f $Inv.Tax) 원</td></tr>
    </table>
    <div class="total"><div class="lbl">이번달 청구금액</div><div class="amt">${amtFmt} 원</div></div>
    <div class="due">납기일: $($Inv.DueDate) · 미납 시 연체료가 부과될 수 있습니다</div>
    <div class="foot"><span>고객센터 국번없이 123</span><span>발행일 $($Inv.IssueDate)</span></div>
  </div>
</div>
</body></html>
"@
}

# ══════════════════════════ 무관 파일(카페 영수증) 템플릿 ══════════════════════════
function New-CafeReceiptHtml {
    param($R)
@"
<!doctype html><html><head><meta charset="utf-8"><style>
  body{margin:0;background:#d9d9d9;display:flex;justify-content:center;padding:40px 16px;font-family:"Malgun Gothic",sans-serif;}
  .receipt{width:340px;background:#fff;padding:18px 20px;box-shadow:0 2px 8px rgba(0,0,0,.25);font-size:13px;color:#222;transform:rotate(-1deg);}
  .receipt h2{margin:0 0 4px;text-align:center;font-size:16px;letter-spacing:.1em;}
  .receipt .sub{text-align:center;color:#777;font-size:11px;margin-bottom:12px;}
  .receipt hr{border:none;border-top:1px dashed #999;margin:10px 0;}
  .row{display:flex;justify-content:space-between;margin:3px 0;}
  .row.total{font-weight:700;font-size:15px;margin-top:8px;}
  .meta{color:#666;font-size:11px;margin-top:10px;}
</style></head><body>
<div class="receipt">
  <h2>$($R.ShopName)</h2>
  <div class="sub">$($R.ShopAddr)</div>
  <hr>
  <div class="row"><span>$($R.Item1)</span><span>$($R.Item1Price)원</span></div>
  <div class="row"><span>$($R.Item2)</span><span>$($R.Item2Price)원</span></div>
  <hr>
  <div class="row total"><span>합계</span><span>$($R.Total)원</span></div>
  <div class="meta">$($R.Date) $($R.Time) · 카드결제</div>
</div>
</body></html>
"@
}

Write-Host "템플릿 로드 완료"

# ══════════════════════════ 단가표 (2025, 원) ══════════════════════════
$DieselPrice   = @{1=1421;2=1449;3=1414;4=1376;5=1366;6=1369;7=1392;8=1396;9=1392;10=1397;11=1472;12=1500}
$GasolinePrice = @{1=1554;2=1571;3=1535;4=1497;5=1488;6=1493;7=1516;8=1514;9=1509;10=1512;11=1562;12=1582}
$FormatCycle = @("pdf","jpg","png")

function New-Manifest { param([string]$header) $m = New-Object System.Collections.Generic.List[string]; $m.Add($header); return ,$m }

# ── 세금계산서 일괄 생성 ──
function Build-TaxInvoices {
    param($CompanyId, $CompanyNameKo, $BuyerBizNo, $BuyerAddr, $BuyerType, $BuyerItem, $Suppliers, $MonthPlan, $OutDir)
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $manifest = New-Manifest "record_id,company_id,issue_date,supplier_name,item_name,spec,qty,unit,unit_price_krw,supply_amount_krw,vat_krw,total_krw,memo,file_format,file_name"
    $days2 = @(8,22); $days3 = @(6,16,26)
    $idx = 0
    foreach ($m in ($MonthPlan.Keys | Sort-Object)) {
        $plan = $MonthPlan[$m]  # array of hashtables: @{Liters=..; Fuel="경유"|"휘발유"; Spec=..}
        $n = $plan.Count
        $days = if ($n -ge 3) { $days3 } else { $days2 }
        for ($i = 0; $i -lt $n; $i++) {
            $p = $plan[$i]
            $sup = $Suppliers[$i % $Suppliers.Count]
            $price = if ($p.Fuel -eq "휘발유") { $GasolinePrice[$m] } else { $DieselPrice[$m] }
            $qty = $p.Liters
            $supply = [long]($qty * $price)
            $vat = [long][math]::Round($supply * 0.1)
            $inv = @{
                Year=2025; Month=$m; Day=$days[$i]
                SupplierName=$sup.Name; SupplierBizNo=$sup.BizNo; SupplierOwner=$sup.Owner; SupplierAddr=$sup.Addr
                SupplierType="도소매"; SupplierItem="석유판매업"
                BuyerName=$CompanyNameKo; BuyerBizNo=$BuyerBizNo; BuyerOwner=$p.BuyerOwner
                BuyerAddr=$BuyerAddr; BuyerType=$BuyerType; BuyerItem=$BuyerItem
                ItemName=$p.Fuel; Spec=$p.Spec; Qty=$qty; UnitPrice=$price; SupplyAmount=$supply; VatAmount=$vat
                Memo=$p.Memo; SerialNo="$CompanyId-$('{0:D2}' -f $m)-$($i+1)"
            }
            $html = New-InvoiceHtml -Inv $inv
            $issueDate = "2025-{0:D2}-{1:D2}" -f $m, $days[$i]
            $baseName = "${CompanyNameKo}_${issueDate}_세금계산서_$($p.Fuel)"
            $format = $FormatCycle[$idx % 3]
            $finalName = "$baseName.$format"
            $finalPath = Join-Path $OutDir $finalName
            Render-ToFile -Html $html -FinalPath $finalPath -Format $format -SafeKey "$CompanyId$m$i"
            $total = $supply + $vat
            $manifest.Add("$baseName,$CompanyId,$issueDate,$($sup.Name),$($p.Fuel),$($p.Spec),$qty,L,$price,$supply,$vat,$total,$($p.Memo),$format,$finalName")
            Write-Host "생성됨: $finalName"
            $idx++
        }
    }
    Set-Content -Path (Join-Path $OutDir "_manifest.csv") -Value ($manifest -join "`n") -Encoding utf8
}

# ── 전기요금고지서 일괄 생성 ──
function Build-ElectricityBills {
    param($CompanyId, $CompanyNameKo, $CustomerNumber, $SiteAddr, $ContractType, $ContractPower, $MonthPlan, $OutDir)
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $manifest = New-Manifest "record_id,company_id,billing_month,usage_kwh,prev_usage_kwh,billed_amount_krw,is_estimated,due_date,file_format,file_name"
    $idx = 0
    $months = $MonthPlan.Keys | Sort-Object
    foreach ($m in $months) {
        $p = $MonthPlan[$m]  # @{Kwh=n or $null; PrevKwh=n; BilledAmount=n}
        $baseFee = 300000
        if ($p.Kwh -ne $null) {
            $energyFee = [long]($p.Kwh * 89.5)
        } else {
            $energyFee = [long]($p.PrevKwh * 89.5)  # 추정: 전월 실적 기준
        }
        $tax = $p.BilledAmount - $baseFee - $energyFee
        $billingMonth = "2025-{0:D2}" -f $m
        $nextMonth = if ($m -eq 12) { "2026-01" } else { "2025-{0:D2}" -f ($m+1) }
        $lastDay = 31
        if ($m -in @(4,6,9,11)) { $lastDay = 30 } elseif ($m -eq 2) { $lastDay = 28 }
        $inv = @{
            Year=2025; Month=$m; CompanyName=$CompanyNameKo; CustomerNumber=$CustomerNumber
            SiteAddr=$SiteAddr; ContractType=$ContractType; ContractPower=$ContractPower
            UsageKwh=$p.Kwh; PrevUsageKwh=$p.PrevKwh; BaseFee=$baseFee; EnergyFee=$energyFee; Tax=$tax
            BilledAmount=$p.BilledAmount
            PeriodStart="2025-{0:D2}-01" -f $m; PeriodEnd="2025-{0:D2}-{1}" -f $m,$lastDay
            MeterDate="2025-{0:D2}-{1}" -f $m,$lastDay
            DueDate="$nextMonth-25"; IssueDate="$nextMonth-05"
        }
        $html = New-BillHtml -Inv $inv
        $baseName = "${CompanyNameKo}_${billingMonth}_전기요금고지서"
        $format = $FormatCycle[$idx % 3]
        $finalName = "$baseName.$format"
        $finalPath = Join-Path $OutDir $finalName
        Render-ToFile -Html $html -FinalPath $finalPath -Format $format -SafeKey "eb$CompanyId$m" -W 900 -H 720
        $kwhCol = if ($p.Kwh -ne $null) { $p.Kwh } else { "" }
        $manifest.Add("$baseName,$CompanyId,$billingMonth,$kwhCol,$($p.PrevKwh),$($p.BilledAmount),$($p.Kwh -eq $null),$($inv.DueDate),$format,$finalName")
        Write-Host "생성됨: $finalName"
        $idx++
    }
    Set-Content -Path (Join-Path $OutDir "_manifest.csv") -Value ($manifest -join "`n") -Encoding utf8
}

# ── 무관 파일(카페 영수증) 생성 ──
function Build-IrrelevantFiles {
    param($CompanyId, $CompanyNameKo, $Receipts, $OutDir)
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $manifest = New-Manifest "record_id,company_id,file_date,doc_type,total_krw,expected_action,file_format,file_name"
    $idx = 0
    foreach ($r in $Receipts) {
        $html = New-CafeReceiptHtml -R $r
        $baseName = "${CompanyNameKo}_$($r.Date)_관계없는파일_카페영수증"
        $format = "jpg"
        $finalName = "$baseName.$format"
        $finalPath = Join-Path $OutDir $finalName
        Render-ToFile -Html $html -FinalPath $finalPath -Format $format -SafeKey "irr$CompanyId$idx" -W 420 -H 520
        $manifest.Add("$baseName,$CompanyId,$($r.Date),cafe_receipt,$($r.Total),자동반려,$format,$finalName")
        Write-Host "생성됨: $finalName"
        $idx++
    }
    Set-Content -Path (Join-Path $OutDir "_manifest.csv") -Value ($manifest -join "`n") -Encoding utf8
}

Write-Host "함수 정의 완료 — 회사별 실행은 run_companies.ps1에서"

