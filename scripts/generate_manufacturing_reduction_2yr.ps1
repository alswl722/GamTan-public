# 제조업 트랙 "전년 대비 감축" 데모 시나리오 — C004(칠곡소재)·C005(포항이엔지)
# 배경: 목표 설정(company_goals) 진행률이 롤링 12개월 기준값 vs 다음 12개월 비교값을
#       계산하는데(db/pcaf_engine/company_goals.py), 기존 C004·C005 데이터는 2025년
#       1개년 + 2026년 YTD뿐이고 그나마 사용량이 완만히 "증가"하는 추세라 목표 카드가
#       0%/미측정으로만 표시됐다(팀 채팅 보고, 2026-08-25).
# 기간: 2024-01 ~ 2026-08 (32개월) — S001·S002(소상공인 트랙) fixture와 같은 관례.
#       2024=기준년도, 2025=비교년도(YoY), 2026 YTD=최신 추세. company_goals의 롤링
#       윈도우는 목표 설정월 기준이라 정확히 "이 달"에 맞출 필요는 없고, 24개월 이상의
#       연속 데이터 + 명확한 감소 추세만 있으면 어느 달에 목표를 세워도 비교가 성립한다.
# 시나리오: 전기(Scope2) 사용량과 경유(Scope1) 사용량 둘 다 매년 감소.
#   - C004 칠곡소재: 강한 감축(연 약 8%) — "목표 달성" 배지 데모용
#   - C005 포항이엔지: 완만한 감축(연 약 4%) — "진행 중" 카드 데모용(달성 전 상태를 보여줌)
# ⚠️ 기존 C004·C005 데이터(2025년 정상 흐름 시나리오)는 덮어쓰기 전
#    data/fixtures_backup_2026-08-25/ 에 백업해뒀다 — 원본이 필요하면 거기서 복원.
#
# 실행 후 남은 작업(이 스크립트 범위 밖 — Python·DATABASE_URL 필요):
#   scripts/ingest_manufacturing_fixtures.py 로 실제 업로드 파이프라인을 태워 DB에 반영.

. (Join-Path $PSScriptRoot "generate_other_companies_fixtures.ps1")

$Root = Join-Path $PSScriptRoot "..\data\fixtures"
$BuyerType = "제조업"; $BuyerItem = "기타 금속가공제품 제조"

function Calc-Billed([int]$Kwh) {
    return [long]([math]::Round((300000 + $Kwh * 89.5) * 1.15 / 1000.0)) * 1000
}

function Build-ElecPlan {
    param([array]$YearMaps, [int]$StartPrevKwh)
    $plan = [ordered]@{}
    $prev = $StartPrevKwh
    foreach ($ym in $YearMaps) {
        foreach ($m in ($ym.Map.Keys | Sort-Object)) {
            $kwh = $ym.Map[$m]
            $key = "{0}-{1:D2}" -f $ym.Year, $m
            $plan[$key] = @{ Kwh = $kwh; PrevKwh = $prev; BilledAmount = (Calc-Billed $kwh) }
            $prev = $kwh
        }
    }
    return $plan
}

function Build-DieselPlan {
    param([array]$YearMaps, [string]$BuyerOwner, [string]$Spec = "지게차용", [string]$Memo = "지게차 연료")
    $plan = [ordered]@{}
    foreach ($ym in $YearMaps) {
        foreach ($m in ($ym.Map.Keys | Sort-Object)) {
            $key = "{0}-{1:D2}" -f $ym.Year, $m
            $plan[$key] = @(@{ Liters = $ym.Map[$m]; Fuel = "경유"; Spec = $Spec; Memo = $Memo; BuyerOwner = $BuyerOwner })
        }
    }
    return $plan
}

# S001·S002(generate_small_business_fixtures.ps1)와 동일한 골든셋 포맷 — 제조업 트랙에도
# 그대로 재사용해 "전년 대비/2년 평균 대비 감축률"을 파일로 검증할 수 있게 한다.
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

# ═══════════════ C004 — 칠곡소재 (강한 감축, 연 약 8% — "목표 달성" 데모용) ═══════════════
$c4_elec_2024 = @{1=2450;2=2420;3=2400;4=2380;5=2410;6=2460;7=2520;8=2540;9=2470;10=2430;11=2410;12=2440}
$c4_elec_2025 = @{1=2250;2=2225;3=2210;4=2190;5=2215;6=2260;7=2320;8=2335;9=2270;10=2235;11=2215;12=2245}
$c4_elec_2026 = @{1=2070;2=2045;3=2035;4=2015;5=2040;6=2080;7=2135;8=2150}

$c4_diesel_2024 = @{1=70;2=68;3=72;4=75;5=78;6=82;7=88;8=90;9=80;10=75;11=72;12=74}
$c4_diesel_2025 = @{1=64;2=63;3=66;4=69;5=72;6=75;7=81;8=83;9=74;10=69;11=66;12=68}
$c4_diesel_2026 = @{1=59;2=58;3=61;4=63;5=66;6=69;7=74;8=76}

$sup4 = @(@{Name="칠곡주유소"; BizNo="855-07-24916"; Owner="문성훈"; Addr="경북 칠곡군 왜관읍 중앙로 5"})
$owner4 = "박은서"
$c4Addr = "경북 칠곡군 왜관읍 공단로 15"

$c4ElecPlan = Build-ElecPlan -YearMaps @(
    @{Year=2024; Map=$c4_elec_2024}, @{Year=2025; Map=$c4_elec_2025}, @{Year=2026; Map=$c4_elec_2026}
) -StartPrevKwh 2500
Build-ElectricityBills -CompanyId "C004" -CompanyNameKo "칠곡소재" -CustomerNumber "0663-7702-19" `
    -SiteAddr $c4Addr -ContractType "일반용(을) 저압" -ContractPower "50" `
    -MonthPlan $c4ElecPlan -OutDir "$Root\electricity_bills\C004"

$c4DieselPlan = Build-DieselPlan -YearMaps @(
    @{Year=2024; Map=$c4_diesel_2024}, @{Year=2025; Map=$c4_diesel_2025}, @{Year=2026; Map=$c4_diesel_2026}
) -BuyerOwner $owner4
Build-TaxInvoices -CompanyId "C004" -CompanyNameKo "칠곡소재" -BuyerBizNo "742-58-11029" -BuyerAddr $c4Addr `
    -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup4 -MonthPlan $c4DieselPlan -OutDir "$Root\tax_invoices\C004"

Write-ReductionGoldenSet -OutDir "$Root\electricity_bills\C004" -Kwh2024 $c4_elec_2024 -Kwh2025 $c4_elec_2025 -Kwh2026 $c4_elec_2026 `
    -Note "전기(Scope2) 사용량 — 연 약 8% 감축, 목표 달성 데모용"

# ═══════════════ C005 — 포항이엔지 (완만한 감축, 연 약 4% — "진행 중" 데모용) ═══════════════
$c5_elec_2024 = @{1=3600;2=3550;3=3520;4=3500;5=3560;6=3650;7=3750;8=3800;9=3700;10=3600;11=3560;12=3600}
$c5_elec_2025 = @{1=3455;2=3410;3=3380;4=3360;5=3420;6=3505;7=3600;8=3650;9=3550;10=3455;11=3420;12=3455}
$c5_elec_2026 = @{1=3315;2=3275;3=3245;4=3225;5=3285;6=3365;7=3455;8=3505}

$c5_diesel_2024 = @{1=165;2=160;3=168;4=172;5=178;6=186;7=192;8=196;9=182;10=174;11=168;12=172}
$c5_diesel_2025 = @{1=158;2=154;3=161;4=165;5=171;6=179;7=184;8=188;9=175;10=167;11=161;12=165}
$c5_diesel_2026 = @{1=152;2=148;3=155;4=158;5=164;6=172;7=177;8=180}

$sup5 = @(@{Name="포항해맞이주유소"; BizNo="470-19-38225"; Owner="배수아"; Addr="경북 포항시 남구 오천읍 문충로 30"})
$owner5 = "최민준"
$c5Addr = "경북 포항시 남구 연일읍 산업로 200"

$c5ElecPlan = Build-ElecPlan -YearMaps @(
    @{Year=2024; Map=$c5_elec_2024}, @{Year=2025; Map=$c5_elec_2025}, @{Year=2026; Map=$c5_elec_2026}
) -StartPrevKwh 3650
Build-ElectricityBills -CompanyId "C005" -CompanyNameKo "포항이엔지" -CustomerNumber "0741-5528-40" `
    -SiteAddr $c5Addr -ContractType "산업용(을) 고압A" -ContractPower "120" `
    -MonthPlan $c5ElecPlan -OutDir "$Root\electricity_bills\C005"

$c5DieselPlan = Build-DieselPlan -YearMaps @(
    @{Year=2024; Map=$c5_diesel_2024}, @{Year=2025; Map=$c5_diesel_2025}, @{Year=2026; Map=$c5_diesel_2026}
) -BuyerOwner $owner5
Build-TaxInvoices -CompanyId "C005" -CompanyNameKo "포항이엔지" -BuyerBizNo "216-87-93340" -BuyerAddr $c5Addr `
    -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup5 -MonthPlan $c5DieselPlan -OutDir "$Root\tax_invoices\C005"

Write-ReductionGoldenSet -OutDir "$Root\electricity_bills\C005" -Kwh2024 $c5_elec_2024 -Kwh2025 $c5_elec_2025 -Kwh2026 $c5_elec_2026 `
    -Note "전기(Scope2) 사용량 — 연 약 4% 감축, 목표 진행 중(미달성) 데모용"

Write-Host ""
Write-Host "=== 제조업 2년 감축 시나리오 완료: C004·C005 각 32개월(전기+경유) ==="

