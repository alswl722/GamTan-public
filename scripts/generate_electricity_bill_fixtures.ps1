param(
    [string]$OutDir = "C:\Users\wkdud\OneDrive\바탕 화면\감탄\GamTan-dev\data\fixtures\electricity_bills\C003"
)

$ErrorActionPreference = "Stop"
$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
Add-Type -AssemblyName System.Drawing

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function New-BillHtml {
    param($Inv)

    $usageFmt = "{0:N0}" -f $Inv.UsageKwh
    $prevFmt  = "{0:N0}" -f $Inv.PrevUsageKwh
    $amtFmt   = "{0:N0}" -f $Inv.BilledAmount
    $diff = $Inv.UsageKwh - $Inv.PrevUsageKwh
    $diffSign = if ($diff -ge 0) { "+" } else { "" }
    $diffFmt = "$diffSign" + ("{0:N0}" -f $diff)

@"
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root{
    --blue:#0b5ea8; --blue-dark:#083f73; --teal:#00a19a;
    --paper:#ffffff; --text:#1e2530; --muted:#6b7684;
    --line:#dbe2e8; --panel:#f3f7fa; --badge-gray:#8b8b86;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:#e7ebee;display:flex;justify-content:center;
    padding:26px 16px;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:var(--text);}
  .sheet{position:relative;width:860px;background:var(--paper);box-shadow:0 1px 3px rgba(0,0,0,.12);}
  .badge{position:absolute;top:10px;right:14px;font-size:11px;letter-spacing:.04em;color:var(--badge-gray);
    border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;z-index:2;}
  .head{background:linear-gradient(135deg,var(--blue) 0%,var(--blue-dark) 100%);color:#fff;
    padding:22px 30px;display:flex;justify-content:space-between;align-items:flex-end;}
  .head .org{font-size:13px;letter-spacing:.08em;opacity:.85;margin-bottom:6px;}
  .head h1{margin:0;font-size:26px;letter-spacing:.06em;}
  .head .period{text-align:right;font-size:13px;line-height:1.6;}
  .head .period b{font-size:17px;display:block;}
  .body{padding:26px 30px 30px;}
  .cust{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:20px;}
  .cust .row{display:grid;grid-template-columns:96px 1fr;border-bottom:1px solid var(--line);}
  .cust .row:last-child{border-bottom:none;}
  .cust .col:first-child .row:last-child{border-bottom:1px solid var(--line);}
  .cust .lbl{background:var(--panel);color:var(--muted);font-size:12.5px;display:flex;align-items:center;padding:9px 10px;border-right:1px solid var(--line);}
  .cust .val{display:flex;align-items:center;padding:9px 12px;font-size:13.5px;}
  .cust .col{border-right:1px solid var(--line);}
  .cust .col:last-child{border-right:none;}

  .usage-title{font-size:14px;font-weight:700;color:var(--blue-dark);margin:0 0 8px;padding-left:2px;border-left:4px solid var(--teal);padding-left:8px;}
  table.usage{width:100%;border-collapse:collapse;margin-bottom:22px;font-size:13.5px;}
  table.usage th{background:var(--panel);color:var(--muted);font-weight:700;font-size:12.5px;padding:9px 8px;border:1px solid var(--line);text-align:center;}
  table.usage td{padding:10px 8px;border:1px solid var(--line);text-align:center;font-variant-numeric:tabular-nums;}
  table.usage td.num{font-size:16px;font-weight:700;color:var(--blue-dark);}

  .charges{width:100%;border-collapse:collapse;margin-bottom:22px;font-size:13.5px;}
  .charges td{padding:8px 10px;border-bottom:1px dashed var(--line);}
  .charges td.k{color:var(--muted);}
  .charges td.v{text-align:right;font-variant-numeric:tabular-nums;}
  .charges tr:last-child td{border-bottom:none;}

  .total{display:flex;justify-content:space-between;align-items:center;
    background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 20px;margin-bottom:16px;}
  .total .lbl{font-size:14px;font-weight:700;color:var(--blue-dark);}
  .total .amt{font-size:26px;font-weight:800;color:var(--blue-dark);font-variant-numeric:tabular-nums;}
  .due{font-size:12.5px;color:var(--muted);text-align:right;}
  .foot{border-top:1px solid var(--line);padding-top:12px;font-size:11.5px;color:var(--muted);display:flex;justify-content:space-between;}
</style></head>
<body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="head">
    <div>
      <div class="org">한국전력공사 · KOREA ELECTRIC POWER CORP.</div>
      <h1>전 기 요 금 청 구 서</h1>
    </div>
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
    <table class="usage">
      <tr><th>당월 사용량</th><th>전월 사용량</th><th>전월 대비</th><th>계약전력</th></tr>
      <tr><td class="num">${usageFmt} kWh</td><td>${prevFmt} kWh</td><td>${diffFmt} kWh</td><td>$($Inv.ContractPower) kW</td></tr>
    </table>

    <div class="usage-title">요금 내역</div>
    <table class="charges">
      <tr><td class="k">기본요금</td><td class="v">$('{0:N0}' -f $Inv.BaseFee) 원</td></tr>
      <tr><td class="k">전력량요금</td><td class="v">$('{0:N0}' -f $Inv.EnergyFee) 원</td></tr>
      <tr><td class="k">부가가치세 및 전력기금</td><td class="v">$('{0:N0}' -f $Inv.Tax) 원</td></tr>
    </table>

    <div class="total">
      <div class="lbl">이번달 청구금액</div>
      <div class="amt">${amtFmt} 원</div>
    </div>
    <div class="due">납기일: $($Inv.DueDate) · 미납 시 연체료가 부과될 수 있습니다</div>

    <div class="foot">
      <span>고객센터 국번없이 123</span>
      <span>발행일 $($Inv.IssueDate)</span>
    </div>
  </div>
</div>
</body></html>
"@
}

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

# ── 성서테크(C003) 2025년 전기요금고지서 12개월 — 12월 사용량 이상치(원인 미확정) ──
$CompanyName = "성서테크"
$Bills = @(
    @{ Year=2025; Month=1;  UsageKwh=4150;  PrevUsageKwh=4020;  BaseFee=328000; EnergyFee=371425; Tax=99575;  BilledAmount=720000;  DueDate="2025-02-25"; IssueDate="2025-02-05"; PeriodStart="2025-01-01"; PeriodEnd="2025-01-31"; MeterDate="2025-01-31" },
    @{ Year=2025; Month=2;  UsageKwh=4320;  PrevUsageKwh=4150;  BaseFee=328000; EnergyFee=386640; Tax=105360; BilledAmount=748000;  DueDate="2025-03-25"; IssueDate="2025-03-05"; PeriodStart="2025-02-01"; PeriodEnd="2025-02-28"; MeterDate="2025-02-28" },
    @{ Year=2025; Month=3;  UsageKwh=4480;  PrevUsageKwh=4320;  BaseFee=328000; EnergyFee=401120; Tax=109880; BilledAmount=774000;  DueDate="2025-04-25"; IssueDate="2025-04-05"; PeriodStart="2025-03-01"; PeriodEnd="2025-03-31"; MeterDate="2025-03-31" },
    @{ Year=2025; Month=4;  UsageKwh=4600;  PrevUsageKwh=4480;  BaseFee=328000; EnergyFee=411700; Tax=113300; BilledAmount=793000;  DueDate="2025-05-25"; IssueDate="2025-05-04"; PeriodStart="2025-04-01"; PeriodEnd="2025-04-30"; MeterDate="2025-04-30" },
    @{ Year=2025; Month=5;  UsageKwh=4750;  PrevUsageKwh=4600;  BaseFee=328000; EnergyFee=425075; Tax=117925; BilledAmount=817000;  DueDate="2025-06-25"; IssueDate="2025-06-04"; PeriodStart="2025-05-01"; PeriodEnd="2025-05-31"; MeterDate="2025-05-31" },
    @{ Year=2025; Month=6;  UsageKwh=5100;  PrevUsageKwh=4750;  BaseFee=328000; EnergyFee=456450; Tax=127550; BilledAmount=872000;  DueDate="2025-07-25"; IssueDate="2025-07-04"; PeriodStart="2025-06-01"; PeriodEnd="2025-06-30"; MeterDate="2025-06-30" },
    @{ Year=2025; Month=7;  UsageKwh=5450;  PrevUsageKwh=5100;  BaseFee=328000; EnergyFee=487775; Tax=139225; BilledAmount=927000;  DueDate="2025-08-25"; IssueDate="2025-08-04"; PeriodStart="2025-07-01"; PeriodEnd="2025-07-31"; MeterDate="2025-07-31" },
    @{ Year=2025; Month=8;  UsageKwh=5600;  PrevUsageKwh=5450;  BaseFee=328000; EnergyFee=501200; Tax=141800; BilledAmount=951000;  DueDate="2025-09-25"; IssueDate="2025-09-04"; PeriodStart="2025-08-01"; PeriodEnd="2025-08-31"; MeterDate="2025-08-31" },
    @{ Year=2025; Month=9;  UsageKwh=5050;  PrevUsageKwh=5600;  BaseFee=328000; EnergyFee=451975; Tax=124025; BilledAmount=864000;  DueDate="2025-10-25"; IssueDate="2025-10-04"; PeriodStart="2025-09-01"; PeriodEnd="2025-09-30"; MeterDate="2025-09-30" },
    @{ Year=2025; Month=10; UsageKwh=4700;  PrevUsageKwh=5050;  BaseFee=328000; EnergyFee=420650; Tax=110350; BilledAmount=809000;  DueDate="2025-11-25"; IssueDate="2025-11-04"; PeriodStart="2025-10-01"; PeriodEnd="2025-10-31"; MeterDate="2025-10-31" },
    @{ Year=2025; Month=11; UsageKwh=4900;  PrevUsageKwh=4700;  BaseFee=328000; EnergyFee=438550; Tax=113450; BilledAmount=840000;  DueDate="2025-12-25"; IssueDate="2025-12-04"; PeriodStart="2025-11-01"; PeriodEnd="2025-11-30"; MeterDate="2025-11-30" },
    @{ Year=2025; Month=12; UsageKwh=11800; PrevUsageKwh=4900;  BaseFee=328000; EnergyFee=1056100; Tax=328900; BilledAmount=1928000; DueDate="2026-01-25"; IssueDate="2026-01-05"; PeriodStart="2025-12-01"; PeriodEnd="2025-12-31"; MeterDate="2025-12-31" },

    # ── 2026년 1~8월: 12월 스파이크(11,800kWh) 이후 일부 되돌아왔지만 이전 기준선(4,900)으로는
    #    복귀하지 않고 8,000대에서 재상승 — 청구서에 원인 설명 여전히 없음(진행 중인 이상치) ──
    @{ Year=2026; Month=1;  UsageKwh=9200;  PrevUsageKwh=11800; BaseFee=328000; EnergyFee=823400;  Tax=394600; BilledAmount=1546000; DueDate="2026-02-25"; IssueDate="2026-02-05"; PeriodStart="2026-01-01"; PeriodEnd="2026-01-31"; MeterDate="2026-01-31" },
    @{ Year=2026; Month=2;  UsageKwh=8700;  PrevUsageKwh=9200;  BaseFee=328000; EnergyFee=778650;  Tax=355350; BilledAmount=1462000; DueDate="2026-03-25"; IssueDate="2026-03-05"; PeriodStart="2026-02-01"; PeriodEnd="2026-02-28"; MeterDate="2026-02-28" },
    @{ Year=2026; Month=3;  UsageKwh=8300;  PrevUsageKwh=8700;  BaseFee=328000; EnergyFee=742850;  Tax=323150; BilledAmount=1394000; DueDate="2026-04-25"; IssueDate="2026-04-05"; PeriodStart="2026-03-01"; PeriodEnd="2026-03-31"; MeterDate="2026-03-31" },
    @{ Year=2026; Month=4;  UsageKwh=8000;  PrevUsageKwh=8300;  BaseFee=328000; EnergyFee=716000;  Tax=300000; BilledAmount=1344000; DueDate="2026-05-25"; IssueDate="2026-05-05"; PeriodStart="2026-04-01"; PeriodEnd="2026-04-30"; MeterDate="2026-04-30" },
    @{ Year=2026; Month=5;  UsageKwh=8600;  PrevUsageKwh=8000;  BaseFee=328000; EnergyFee=769700;  Tax=347300; BilledAmount=1445000; DueDate="2026-06-25"; IssueDate="2026-06-05"; PeriodStart="2026-05-01"; PeriodEnd="2026-05-31"; MeterDate="2026-05-31" },
    @{ Year=2026; Month=6;  UsageKwh=9800;  PrevUsageKwh=8600;  BaseFee=328000; EnergyFee=877100;  Tax=440900; BilledAmount=1646000; DueDate="2026-07-25"; IssueDate="2026-07-05"; PeriodStart="2026-06-01"; PeriodEnd="2026-06-30"; MeterDate="2026-06-30" },
    @{ Year=2026; Month=7;  UsageKwh=11200; PrevUsageKwh=9800;  BaseFee=328000; EnergyFee=1002400; Tax=551600; BilledAmount=1882000; DueDate="2026-08-25"; IssueDate="2026-08-05"; PeriodStart="2026-07-01"; PeriodEnd="2026-07-31"; MeterDate="2026-07-31" },
    @{ Year=2026; Month=8;  UsageKwh=12500; PrevUsageKwh=11200; BaseFee=328000; EnergyFee=1118750; Tax=653250; BilledAmount=2100000; DueDate="2026-09-25"; IssueDate="2026-09-05"; PeriodStart="2026-08-01"; PeriodEnd="2026-08-31"; MeterDate="2026-08-31" }
)

$common = @{
    CompanyName="$CompanyName"; CustomerNumber="0192-8834-71"; SiteAddr="대구 달서구 성서공단로 120";
    ContractType="산업용(을) 고압A"; ContractPower="150"
}

Add-Type -AssemblyName System.Drawing
$FormatCycle = @("pdf", "jpg", "png")
$manifest = New-Object System.Collections.Generic.List[string]
$manifest.Add("record_id,company_id,billing_month,usage_kwh,prev_usage_kwh,base_fee_krw,energy_fee_krw,tax_krw,billed_amount_krw,due_date,file_format,file_name")

$idx = 0
foreach ($b in $Bills) {
    $inv = $common + $b
    $html = New-BillHtml -Inv $inv
    $safeKey = "$($b.Year)$('{0:D2}' -f $b.Month)_$idx"
    $invHtml = Join-Path $env:TEMP "gamtan_elecbill_$safeKey.html"
    $profileDir = Join-Path $env:TEMP "gamtan_chrome_profile_eb_$safeKey"
    Set-Content -Path $invHtml -Value $html -Encoding utf8

    $billingMonth = "{0:D4}-{1:D2}" -f $b.Year, $b.Month
    $baseName = "${CompanyName}_${billingMonth}_전기요금고지서"
    $format = $FormatCycle[$idx % $FormatCycle.Count]
    $finalName = "$baseName.$format"
    $finalPath = Join-Path $OutDir $finalName

    if ($format -eq "pdf") {
        $t0 = Get-Date
        & $Chrome --headless --disable-gpu "--user-data-dir=$profileDir" --no-pdf-header-footer --print-to-pdf="$finalPath" "file:///$invHtml" 2>$null
        if (-not (Wait-ForFreshFile -Path $finalPath -Since $t0)) { Write-Warning "PDF 생성 지연/실패: $baseName" }
    } else {
        $pngTmp = Join-Path $env:TEMP "gamtan_elecshot_$safeKey.png"
        $t1 = Get-Date
        & $Chrome --headless --disable-gpu "--user-data-dir=$profileDir" --window-size=900,720 --screenshot="$pngTmp" "file:///$invHtml" 2>$null
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

    $manifest.Add("$baseName,C003,$billingMonth,$($b.UsageKwh),$($b.PrevUsageKwh),$($b.BaseFee),$($b.EnergyFee),$($b.Tax),$($b.BilledAmount),$($b.DueDate),$format,$finalName")
    Write-Host "생성됨: $finalName"
    $idx++
}

$manifestPath = Join-Path $OutDir "_manifest.csv"
Set-Content -Path $manifestPath -Value ($manifest -join "`n") -Encoding utf8
Write-Host ""
Write-Host "완료: $($Bills.Count)건 생성 -> $OutDir"
