# 소상공인 트랙(탄소중립포인트) 상하수도 요금고지서 fixture 생성기
# 대상: S001(동성로카페, 정식 고지서 형식 + 2025-07 사용량 급증 이상치)
#      S002(반월당분식, 카카오톡 채널 알림톡 캡처 형식 + 전부 정상)
# 기간: 2024-01 ~ 2026-08 (32개월, 전기고지서와 동일 구간)
# 서식 근거: 용인시 상하수도 요금고지서 실물(사용자 제공)을 OCR로 구조 확인 후 대구시로
#           각색 — 대구시 자체 원본 검증은 아직 아님(docs/small-business-green-supply-data-plan.md §14-2)
# 의존: generate_other_companies_fixtures.ps1의 공용 유틸(Render-ToFile, New-Manifest 등)

. (Join-Path $PSScriptRoot "generate_other_companies_fixtures.ps1")

$Root = "$PSScriptRoot\..\data\fixtures\water_bills"

function New-WaterBillHtml {
    param($Inv)
    $usageFmt = "{0:N0}" -f $Inv.UsageM3
    $prevReadFmt = "{0:N0}" -f $Inv.PrevReading
    $curReadFmt = "{0:N0}" -f $Inv.CurReading
    $waterFeeFmt = "{0:N0}" -f $Inv.WaterFee
    $sewageFeeFmt = "{0:N0}" -f $Inv.SewageFee
    $utilFeeFmt = "{0:N0}" -f $Inv.UtilFee
    $totalFmt = "{0:N0}" -f $Inv.BilledAmount

    $maxUsage = ($Inv.TrendMonths | ForEach-Object { $_.Usage } | Measure-Object -Maximum).Maximum
    $bars = ""
    foreach ($t in $Inv.TrendMonths) {
        $hPct = [math]::Round(($t.Usage / $maxUsage) * 100)
        $barColor = if ($t.Anomaly) { "#c0392b" } else { "#0e7c86" }
        $bars += "<div class=`"bar-col`"><div class=`"bar`" style=`"height:${hPct}%;background:$barColor;`"></div><div class=`"bar-label`">$($t.Label)</div></div>"
    }

@"
<!doctype html><html><head><meta charset="utf-8"><style>
  :root{--teal:#0e7c86;--teal-dark:#0a5b63;--accent:#c0392b;--paper:#ffffff;--text:#1e2530;--muted:#6b7684;--line:#dbe2e8;--panel:#f1f7f7;--badge-gray:#8b8b86;}
  *{box-sizing:border-box;}
  body{margin:0;background:#e7ebee;display:flex;justify-content:center;padding:26px 16px;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:var(--text);}
  .sheet{position:relative;width:880px;background:var(--paper);box-shadow:0 1px 3px rgba(0,0,0,.12);}
  .badge{position:absolute;top:10px;right:14px;font-size:11px;color:var(--badge-gray);border:1px solid var(--badge-gray);padding:3px 8px;border-radius:3px;background:#ffffffcc;z-index:2;}
  .head{background:linear-gradient(135deg,var(--teal) 0%,var(--teal-dark) 100%);color:#fff;padding:20px 30px;display:flex;justify-content:space-between;align-items:flex-end;}
  .head .org{font-size:12.5px;letter-spacing:.06em;opacity:.88;margin-bottom:6px;}
  .head h1{margin:0;font-size:24px;letter-spacing:.05em;}
  .head .copy{font-size:11.5px;opacity:.85;margin-top:4px;}
  .head .period{text-align:right;font-size:13px;line-height:1.6;}
  .head .period b{font-size:16px;display:block;}
  .body{padding:24px 30px 28px;}
  .cust{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:18px;}
  .cust .row{display:grid;grid-template-columns:92px 1fr;border-bottom:1px solid var(--line);}
  .cust .row:last-child{border-bottom:none;}
  .cust .lbl{background:var(--panel);color:var(--muted);font-size:12.5px;display:flex;align-items:center;padding:8px 10px;border-right:1px solid var(--line);}
  .cust .val{display:flex;align-items:center;padding:8px 12px;font-size:13px;}
  .cust .col{border-right:1px solid var(--line);}
  .cust .col:last-child{border-right:none;}

  .sec-title{font-size:13.5px;font-weight:700;color:var(--teal-dark);margin:0 0 8px;padding-left:8px;border-left:4px solid var(--accent);}
  table.usage{width:100%;border-collapse:collapse;margin-bottom:18px;font-size:13px;}
  table.usage th{background:var(--panel);color:var(--muted);font-weight:700;font-size:12px;padding:8px;border:1px solid var(--line);text-align:center;}
  table.usage td{padding:9px 8px;border:1px solid var(--line);text-align:center;font-variant-numeric:tabular-nums;}
  table.usage td.num{font-size:16px;font-weight:700;color:var(--accent);}

  .trend{border:1px solid var(--line);border-radius:6px;padding:14px 16px 8px;margin-bottom:18px;}
  .trend-title{font-size:12px;color:var(--muted);margin-bottom:10px;}
  .trend-chart{display:flex;align-items:flex-end;gap:6px;height:90px;}
  .bar-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;}
  .bar{width:70%;border-radius:2px 2px 0 0;min-height:2px;}
  .bar-label{font-size:9.5px;color:var(--muted);margin-top:4px;white-space:nowrap;}

  .charges{width:100%;border-collapse:collapse;margin-bottom:18px;font-size:13px;}
  .charges td{padding:7px 10px;border-bottom:1px dashed var(--line);}
  .charges td.k{color:var(--muted);} .charges td.v{text-align:right;font-variant-numeric:tabular-nums;}
  .charges tr:last-child td{border-bottom:none;}

  .total{display:flex;justify-content:space-between;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 20px;margin-bottom:14px;}
  .total .lbl{font-size:13.5px;font-weight:700;color:var(--teal-dark);}
  .total .amt{font-size:24px;font-weight:800;color:var(--teal-dark);font-variant-numeric:tabular-nums;}
  .due{font-size:12px;color:var(--muted);text-align:right;}
  .foot{border-top:1px solid var(--line);padding-top:10px;font-size:11px;color:var(--muted);display:flex;justify-content:space-between;}
</style></head><body>
<div class="sheet">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="head">
    <div>
      <div class="org">대구광역시상수도사업본부 · $($Inv.OfficeName)</div>
      <h1>상하수도 요금 고지서</h1>
      <div class="copy">(고객보관용 영수증)</div>
    </div>
    <div class="period">사용월<b>$($Inv.Year)년 $($Inv.Month)월분</b></div>
  </div>
  <div class="body">
    <div class="cust">
      <div class="col">
        <div class="row"><div class="lbl">관리번호</div><div class="val">$($Inv.ManageNumber)</div></div>
        <div class="row"><div class="lbl">사용자</div><div class="val">$($Inv.CompanyName)</div></div>
        <div class="row"><div class="lbl">사용장소</div><div class="val">$($Inv.SiteAddr)</div></div>
      </div>
      <div class="col">
        <div class="row"><div class="lbl">업종</div><div class="val">$($Inv.UsageType)</div></div>
        <div class="row"><div class="lbl">사용기간</div><div class="val">$($Inv.PeriodStart) ~ $($Inv.PeriodEnd)</div></div>
        <div class="row"><div class="lbl">검침일</div><div class="val">$($Inv.MeterDate)</div></div>
      </div>
    </div>

    <div class="sec-title">검침 및 사용량</div>
    <table class="usage">
      <tr><th>전월지침</th><th>당월지침</th><th>사용량</th></tr>
      <tr><td>${prevReadFmt} ㎥</td><td>${curReadFmt} ㎥</td><td class="num">${usageFmt} ㎥</td></tr>
    </table>

    <div class="trend">
      <div class="trend-title">최근 12개월 사용량 추이(㎥)</div>
      <div class="trend-chart">
        $bars
      </div>
    </div>

    <div class="sec-title">요금 내역</div>
    <table class="charges">
      <tr><td class="k">상수도요금</td><td class="v">${waterFeeFmt} 원</td></tr>
      <tr><td class="k">하수도요금</td><td class="v">${sewageFeeFmt} 원</td></tr>
      <tr><td class="k">물이용부담금</td><td class="v">${utilFeeFmt} 원</td></tr>
    </table>

    <div class="total"><div class="lbl">청구금액</div><div class="amt">${totalFmt} 원</div></div>
    <div class="due">납기일: $($Inv.DueDate) · 미납 시 연체료가 부과될 수 있습니다</div>
    <div class="foot"><span>$($Inv.OfficeName) 문의 053-000-0000</span><span>발행일 $($Inv.IssueDate)</span></div>
  </div>
</div>
</body></html>
"@
}

function New-AlimtalkHtml {
    param($Inv)
    $usageFmt = "{0:N0}" -f $Inv.UsageM3
    $totalFmt = "{0:N0}" -f $Inv.BilledAmount

@"
<!doctype html><html><head><meta charset="utf-8"><style>
  *{box-sizing:border-box;}
  body{margin:0;background:#b2c7d9;display:flex;justify-content:center;padding:0;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;}
  .phone{width:420px;background:#b2c7d9;min-height:760px;position:relative;}
  .badge{position:absolute;top:8px;right:8px;font-size:10px;color:#5b6b78;border:1px solid #5b6b78;padding:2px 6px;border-radius:3px;background:#ffffffcc;z-index:2;}
  .topbar{background:#b2c7d9;padding:14px 16px 8px;display:flex;align-items:center;gap:10px;}
  .topbar .back{font-size:20px;color:#333;}
  .topbar .title{font-size:16px;font-weight:700;color:#222;}
  .chatroom{padding:6px 14px 20px;}
  .sender-row{display:flex;align-items:center;gap:8px;margin:10px 0 4px;}
  .sender-icon{width:36px;height:36px;border-radius:8px;background:#0e7c86;color:#fff;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;flex-shrink:0;}
  .sender-name{font-size:13px;font-weight:700;color:#333;}
  .sender-tag{font-size:10px;color:#888;background:#fff;border-radius:8px;padding:1px 6px;margin-left:4px;}
  .bubble-wrap{display:flex;gap:8px;align-items:flex-start;}
  .bubble-spacer{width:36px;flex-shrink:0;}
  .bubble{background:#ffffff;border-radius:4px 12px 12px 12px;padding:14px 16px;max-width:300px;box-shadow:0 1px 2px rgba(0,0,0,.12);font-size:13px;line-height:1.6;color:#222;}
  .bubble .h1{font-weight:700;font-size:13.5px;margin-bottom:8px;}
  .bubble hr{border:none;border-top:1px solid #e5e5e5;margin:8px 0;}
  .bubble .row{display:flex;justify-content:space-between;margin:3px 0;font-size:12.5px;}
  .bubble .row .k{color:#777;}
  .bubble .row .v{font-weight:600;}
  .bubble .amt-row{display:flex;justify-content:space-between;margin-top:8px;font-size:14px;font-weight:800;color:#0e7c86;}
  .bubble .btn{margin-top:12px;text-align:center;background:#f7f7f7;border:1px solid #e5e5e5;border-radius:6px;padding:9px;font-size:12.5px;font-weight:700;color:#333;}
  .timestamp{font-size:10.5px;color:#5b6b78;margin-top:4px;margin-left:44px;}
  .footer-note{font-size:9.5px;color:#5b6b78;text-align:center;margin-top:26px;line-height:1.5;padding:0 20px;}
</style></head><body>
<div class="phone">
  <span class="badge">합성 테스트 데이터 · SAMPLE</span>
  <div class="topbar"><span class="back">‹</span><span class="title">대구상수도사업본부</span></div>
  <div class="chatroom">
    <div class="sender-row">
      <div class="sender-icon">水</div>
      <div class="sender-name">대구상수도사업본부<span class="sender-tag">채널</span></div>
    </div>
    <div class="bubble-wrap">
      <div class="bubble-spacer"></div>
      <div class="bubble">
        <div class="h1">[대구상수도] $($Inv.CompanyName)님, $($Inv.Month)월 상하수도 요금 안내</div>
        <div class="row"><span class="k">관리번호</span><span class="v">$($Inv.ManageNumber)</span></div>
        <div class="row"><span class="k">사용기간</span><span class="v">$($Inv.PeriodStart) ~ $($Inv.PeriodEnd)</span></div>
        <div class="row"><span class="k">사용량</span><span class="v">${usageFmt} ㎥</span></div>
        <hr>
        <div class="amt-row"><span>청구금액</span><span>${totalFmt}원</span></div>
        <div class="row" style="margin-top:6px;"><span class="k">납기일</span><span class="v">$($Inv.DueDate)</span></div>
        <div class="btn">고지서 상세보기 ></div>
      </div>
    </div>
    <div class="timestamp">$($Inv.SentTime)</div>
    <div class="footer-note">본 메시지는 정보성 안내이며, 카카오톡 채널 설정에서<br>수신 거부하실 수 있습니다. 문의 053-000-0000</div>
  </div>
</div>
</body></html>
"@
}

function Build-MonthList {
    param([hashtable]$UsageByYear)
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($y in ($UsageByYear.Keys | Sort-Object)) {
        foreach ($m in ($UsageByYear[$y].Keys | Sort-Object)) {
            $list.Add([pscustomobject]@{Year=$y; Month=$m; Usage=$UsageByYear[$y][$m]})
        }
    }
    return $list
}

# ═══════════════ S001 — 동성로카페 (정식 고지서, 2025-07 이상치) ═══════════════
$s1Usage = @{
    2024=@{1=8;2=8;3=9;4=9;5=10;6=10;7=9;8=9;9=8;10=9;11=8;12=10}
    2025=@{1=9;2=8;3=9;4=9;5=10;6=11;7=35;8=9;9=8;10=9;11=9;12=10}
    2026=@{1=9;2=8;3=9;4=9;5=10;6=10;7=10;8=11}
}
$s1Months = Build-MonthList $s1Usage
$s1StartReading = 1121  # 2023년 12월 말 누적지침(가상)

$s1OutDir = "$Root\S001"
New-Item -ItemType Directory -Force -Path $s1OutDir | Out-Null
$s1Manifest = New-Manifest "record_id,company_id,billing_month,usage_m3,prev_reading,cur_reading,billed_amount_krw,anomaly,file_format,file_name"

$cumReading = $s1StartReading
for ($i = 0; $i -lt $s1Months.Count; $i++) {
    $cur = $s1Months[$i]
    $prevReading = $cumReading
    $curReading = $cumReading + $cur.Usage
    $cumReading = $curReading

    $winStart = [math]::Max(0, $i - 11)
    $trend = @()
    for ($j = $winStart; $j -le $i; $j++) {
        $mm = $s1Months[$j]
        $label = "{0}.{1:D2}" -f ($mm.Year % 100), $mm.Month
        $isAnomaly = ($mm.Year -eq 2025 -and $mm.Month -eq 7)
        $trend += @{Label=$label; Usage=$mm.Usage; Anomaly=$isAnomaly}
    }

    $waterFee = $cur.Usage * 750
    $sewageFee = $cur.Usage * 500
    $utilFee = $cur.Usage * 160
    $total = $waterFee + $sewageFee + $utilFee
    $billingMonth = "{0}-{1:D2}" -f $cur.Year, $cur.Month
    $nextMonth = if ($cur.Month -eq 12) { "{0}-01" -f ($cur.Year+1) } else { "{0}-{1:D2}" -f $cur.Year, ($cur.Month+1) }
    $lastDay = 31
    if ($cur.Month -in @(4,6,9,11)) { $lastDay = 30 } elseif ($cur.Month -eq 2) { $lastDay = 28 }

    $inv = @{
        Year=$cur.Year; Month=$cur.Month
        OfficeName="중부사업소"
        ManageNumber="2203-114820"
        CompanyName="동성로카페"
        SiteAddr="대구 중구 동성로2가 15"
        UsageType="영업용(일반)"
        PeriodStart="{0}-{1:D2}-01" -f $cur.Year, $cur.Month
        PeriodEnd="{0}-{1:D2}-{2}" -f $cur.Year, $cur.Month, $lastDay
        MeterDate="{0}-{1:D2}-{2}" -f $cur.Year, $cur.Month, $lastDay
        PrevReading=$prevReading; CurReading=$curReading; UsageM3=$cur.Usage
        WaterFee=$waterFee; SewageFee=$sewageFee; UtilFee=$utilFee; BilledAmount=$total
        DueDate="$nextMonth-25"; IssueDate="$nextMonth-05"
        TrendMonths=$trend
    }

    $html = New-WaterBillHtml -Inv $inv
    $baseName = "동성로카페_${billingMonth}_상하수도요금고지서"
    $format = $FormatCycle[$i % 3]
    $finalName = "$baseName.$format"
    $finalPath = Join-Path $s1OutDir $finalName
    Render-ToFile -Html $html -FinalPath $finalPath -Format $format -SafeKey "wbS001$i" -W 900 -H 800

    $isAnomalyRow = ($cur.Year -eq 2025 -and $cur.Month -eq 7)
    $s1Manifest.Add("$baseName,S001,$billingMonth,$($cur.Usage),$prevReading,$curReading,$total,$isAnomalyRow,$format,$finalName")
    Write-Host "생성됨: $finalName"
}
Set-Content -Path (Join-Path $s1OutDir "_manifest.csv") -Value ($s1Manifest -join "`n") -Encoding utf8

# ═══════════════ S002 — 반월당분식 (알림톡, 전부 정상) ═══════════════
$s2Usage = @{
    2024=@{1=6;2=6;3=7;4=7;5=8;6=8;7=9;8=9;9=8;10=7;11=7;12=8}
    2025=@{1=7;2=7;3=8;4=8;5=8;6=9;7=9;8=8;9=8;10=7;11=7;12=8}
    2026=@{1=7;2=7;3=8;4=8;5=9;6=9;7=9;8=8}
}
$s2Months = Build-MonthList $s2Usage

$s2OutDir = "$Root\S002"
New-Item -ItemType Directory -Force -Path $s2OutDir | Out-Null
$s2Manifest = New-Manifest "record_id,company_id,billing_month,usage_m3,billed_amount_krw,anomaly,file_format,file_name"

for ($i = 0; $i -lt $s2Months.Count; $i++) {
    $cur = $s2Months[$i]
    $waterFee = $cur.Usage * 750
    $sewageFee = $cur.Usage * 500
    $utilFee = $cur.Usage * 160
    $total = $waterFee + $sewageFee + $utilFee
    $billingMonth = "{0}-{1:D2}" -f $cur.Year, $cur.Month
    $nextMonth = if ($cur.Month -eq 12) { "{0}-01" -f ($cur.Year+1) } else { "{0}-{1:D2}" -f $cur.Year, ($cur.Month+1) }

    $inv = @{
        Month=$cur.Month
        ManageNumber="1187-330256"
        CompanyName="반월당분식"
        PeriodStart="{0}-{1:D2}-01" -f $cur.Year, $cur.Month
        PeriodEnd="{0}-{1:D2}-{2}" -f $cur.Year, $cur.Month, 28
        UsageM3=$cur.Usage
        BilledAmount=$total
        DueDate="$nextMonth-25"
        SentTime="오전 9:12"
    }

    $html = New-AlimtalkHtml -Inv $inv
    $baseName = "반월당분식_${billingMonth}_상하수도요금_알림톡"
    $finalName = "$baseName.jpg"
    $finalPath = Join-Path $s2OutDir $finalName
    Render-ToFile -Html $html -FinalPath $finalPath -Format "jpg" -SafeKey "wbS002$i" -W 420 -H 620

    $s2Manifest.Add("$baseName,S002,$billingMonth,$($cur.Usage),$total,False,jpg,$finalName")
    Write-Host "생성됨: $finalName"
}
Set-Content -Path (Join-Path $s2OutDir "_manifest.csv") -Value ($s2Manifest -join "`n") -Encoding utf8

Write-Host ""
Write-Host "=== 수도요금고지서 전체 완료: S001 $($s1Months.Count)건, S002 $($s2Months.Count)건 ==="
