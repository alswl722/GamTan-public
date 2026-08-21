# 소상공인 트랙(탄소중립포인트) 전기요금고지서 fixture 생성기
# 대상: S001(동성로카페, 감축 성공 케이스) / S002(반월당분식, 감축 미달·대조군 케이스)
# 기간: 2024-01 ~ 2026-08 (32개월 — 기준년도 2024 + 비교년도 2025 + 최근 YTD 2026.1~8)
# 계약종별: 일반용(을) — 산업용 전기를 쓰는 제조업(MAIN, C001~C006)과 구분되는 소상공인 판별용
# 의존: generate_other_companies_fixtures.ps1의 공용 템플릿(New-BillHtml, Render-ToFile 등)

. (Join-Path $PSScriptRoot "generate_other_companies_fixtures.ps1")

$Root = "$PSScriptRoot\..\data\fixtures"

function Build-BillsForYear {
    param($CompanyId, $CompanyNameKo, $CustomerNumber, $SiteAddr, $ContractType, $ContractPower,
          $BaseFee, $Year, $MonthPlan, $OutDir, $IdxBase)
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $manifestPath = Join-Path $OutDir "_manifest.csv"
    $manifest = New-Manifest "record_id,company_id,billing_month,usage_kwh,prev_usage_kwh,billed_amount_krw,is_estimated,due_date,file_format,file_name"
    if (Test-Path $manifestPath) {
        $existing = Get-Content $manifestPath
        for ($i = 1; $i -lt $existing.Count; $i++) { if ($existing[$i].Trim() -ne "") { $manifest.Add($existing[$i]) } }
    }
    $idx = $IdxBase
    foreach ($m in ($MonthPlan.Keys | Sort-Object)) {
        $p = $MonthPlan[$m]
        $energyFee = [long]($p.Kwh * 185)
        $tax = $p.BilledAmount - $BaseFee - $energyFee
        $billingMonth = "{0}-{1:D2}" -f $Year, $m
        $nextMonth = if ($m -eq 12) { "{0}-01" -f ($Year+1) } else { "{0}-{1:D2}" -f $Year, ($m+1) }
        $lastDay = 31
        if ($m -in @(4,6,9,11)) { $lastDay = 30 } elseif ($m -eq 2) { $lastDay = 28 }
        $inv = @{
            Year=$Year; Month=$m; CompanyName=$CompanyNameKo; CustomerNumber=$CustomerNumber
            SiteAddr=$SiteAddr; ContractType=$ContractType; ContractPower=$ContractPower
            UsageKwh=$p.Kwh; PrevUsageKwh=$p.PrevKwh; BaseFee=$BaseFee; EnergyFee=$energyFee; Tax=$tax
            BilledAmount=$p.BilledAmount
            PeriodStart="{0}-{1:D2}-01" -f $Year, $m; PeriodEnd="{0}-{1:D2}-{2}" -f $Year, $m, $lastDay
            MeterDate="{0}-{1:D2}-{2}" -f $Year, $m, $lastDay
            DueDate="$nextMonth-25"; IssueDate="$nextMonth-05"
        }
        $html = New-BillHtml -Inv $inv
        $baseName = "${CompanyNameKo}_${billingMonth}_전기요금고지서"
        $format = $FormatCycle[$idx % 3]
        $finalName = "$baseName.$format"
        $finalPath = Join-Path $OutDir $finalName
        Render-ToFile -Html $html -FinalPath $finalPath -Format $format -SafeKey "eb$CompanyId$Year$m" -W 900 -H 720
        $manifest.Add("$baseName,$CompanyId,$billingMonth,$($p.Kwh),$($p.PrevKwh),$($p.BilledAmount),False,$($inv.DueDate),$format,$finalName")
        Write-Host "생성됨: $finalName"
        $idx++
    }
    Set-Content -Path $manifestPath -Value ($manifest -join "`n") -Encoding utf8
}

function PlanFromMap($map, $baseFee, $priorLastMonthKwh) {
    $plan = @{}
    foreach ($m in ($map.Keys | Sort-Object)) {
        $prevKwh = if ($m -eq 1) { $priorLastMonthKwh } else { $map[$m-1] }
        $kwh = $map[$m]
        $billed = [long][math]::Round(($baseFee + $kwh*185) * 1.08)
        $plan[$m] = @{Kwh=$kwh; PrevKwh=$prevKwh; BilledAmount=$billed}
    }
    return $plan
}

function Write-ReductionGoldenSet {
    param($OutDir, $Kwh2024, $Kwh2025, $Kwh2026, $Note)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("year_month,usage_kwh,prior_year_same_month_kwh,yoy_reduction_pct,yoy_eligible_5pct,avg_prior_2yr_kwh,reduction_vs_2yr_avg_pct,avg2yr_eligible_5pct,note")

    function Row($year, $m, $cur, $priorYearMap) {
        $monthStr = "{0:D2}" -f $m
        $yearMonth = "$year-$monthStr"
        if ($priorYearMap.ContainsKey($m)) {
            $prior = $priorYearMap[$m]
            $yoyPct = [math]::Round((($prior - $cur) / $prior) * 100, 2)
            $yoyEligible = $yoyPct -ge 5
        } else { $prior = ""; $yoyPct = ""; $yoyEligible = "" }
        if ($Kwh2024.ContainsKey($m) -and $Kwh2025.ContainsKey($m) -and $year -eq 2026) {
            $avg2yr = ($Kwh2024[$m] + $Kwh2025[$m]) / 2.0
            $avgPct = [math]::Round((($avg2yr - $cur) / $avg2yr) * 100, 2)
            $avgEligible = $avgPct -ge 5
            $avg2yrStr = [math]::Round($avg2yr, 1)
        } else { $avg2yrStr = ""; $avgPct = ""; $avgEligible = "" }
        $lines.Add("$yearMonth,$cur,$prior,$yoyPct,$yoyEligible,$avg2yrStr,$avgPct,$avgEligible,$Note")
    }

    foreach ($m in ($Kwh2024.Keys | Sort-Object)) { Row 2024 $m $Kwh2024[$m] @{} }
    foreach ($m in ($Kwh2025.Keys | Sort-Object)) { Row 2025 $m $Kwh2025[$m] $Kwh2024 }
    foreach ($m in ($Kwh2026.Keys | Sort-Object)) { Row 2026 $m $Kwh2026[$m] $Kwh2025 }

    Set-Content -Path (Join-Path $OutDir "_reduction_expected.csv") -Value ($lines -join "`n") -Encoding utf8
}

# ═══════════════ S001 — 동성로카페 (감축 성공 케이스) ═══════════════
$s1_2024 = @{1=420;2=400;3=410;4=430;5=450;6=480;7=520;8=540;9=470;10=440;11=430;12=460}
$s1_2025 = @{1=389;2=370;3=379;4=398;5=416;6=444;7=481;8=500;9=435;10=407;11=398;12=426}
$s1_2026 = @{1=377;2=359;3=368;4=386;5=404;6=431;7=467;8=485}
$s1Common = @{
    CompanyId="S001"; CompanyNameKo="동성로카페"; CustomerNumber="0355-7712-90"
    SiteAddr="대구 중구 동성로2가 15"; ContractType="일반용(을)"; ContractPower="5"; BaseFee=105000
    OutDir="$Root\electricity_bills\S001"
}
Build-BillsForYear @s1Common -Year 2024 -MonthPlan (PlanFromMap $s1_2024 105000 440) -IdxBase 0
Build-BillsForYear @s1Common -Year 2025 -MonthPlan (PlanFromMap $s1_2025 105000 $s1_2024[12]) -IdxBase 12
Build-BillsForYear @s1Common -Year 2026 -MonthPlan (PlanFromMap $s1_2026 105000 $s1_2025[12]) -IdxBase 24
Write-ReductionGoldenSet -OutDir $s1Common.OutDir -Kwh2024 $s1_2024 -Kwh2025 $s1_2025 -Kwh2026 $s1_2026 `
    -Note "전년동월단순비교/2년평균비교 (산식 확정 전까지 두 해석 모두 참고)"

# ═══════════════ S002 — 반월당분식 (감축 미달·대조군 케이스) ═══════════════
$s2_2024 = @{1=360;2=350;3=365;4=375;5=390;6=410;7=440;8=460;9=400;10=380;11=370;12=395}
$s2_2025 = @{1=369;2=359;3=374;4=384;5=400;6=420;7=451;8=472;9=410;10=390;11=379;12=405}
$s2_2026 = @{1=373;2=363;3=378;4=388;5=404;6=424;7=456;8=477}
$s2Common = @{
    CompanyId="S002"; CompanyNameKo="반월당분식"; CustomerNumber="0871-2245-63"
    SiteAddr="대구 중구 반월당네거리 8"; ContractType="일반용(을)"; ContractPower="4"; BaseFee=98000
    OutDir="$Root\electricity_bills\S002"
}
Build-BillsForYear @s2Common -Year 2024 -MonthPlan (PlanFromMap $s2_2024 98000 340) -IdxBase 0
Build-BillsForYear @s2Common -Year 2025 -MonthPlan (PlanFromMap $s2_2025 98000 $s2_2024[12]) -IdxBase 12
Build-BillsForYear @s2Common -Year 2026 -MonthPlan (PlanFromMap $s2_2026 98000 $s2_2025[12]) -IdxBase 24
Write-ReductionGoldenSet -OutDir $s2Common.OutDir -Kwh2024 $s2_2024 -Kwh2025 $s2_2025 -Kwh2026 $s2_2026 `
    -Note "대조군: 사용량 증가 시나리오 — 어떤 산식으로도 자격 미달이어야 정상"

Write-Host ""
Write-Host "=== 소상공인 트랙 fixture 완료: S001·S002 각 32개월 ==="
