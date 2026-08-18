. (Join-Path $PSScriptRoot "generate_other_companies_fixtures.ps1")

# 2026년 1~8월 YTD 연장 배치 — docs/fixture-scenarios.md "남은 후보"의 미착수 항목.
# 2025년 12개월치(run_other_companies_fixtures.ps1)는 그대로 두고, 같은 회사·같은
# 시나리오 성격을 1~8월로 자연스럽게 이어간다. _manifest.csv는 기존 2025년 행 뒤에 append된다
# (generate_other_companies_fixtures.ps1::Save-Manifest).
$Root = "C:\Users\hi\Desktop\GamTan-dev\data\fixtures"
$BuyerType = "제조업"; $BuyerItem = "기타 금속가공제품 제조"

function LI($liters,$fuel,$spec,$memo,$owner){ @{Liters=$liters;Fuel=$fuel;Spec=$spec;Memo=$memo;BuyerOwner=$owner} }

# ═══════════════ 구미정밀(C001) — 안정적 흐름 지속, 2월 결손은 2025년 1회성이라 2026년엔 완비 ═══════════════
$sup1 = @(
    @{Name="형곡주유소";BizNo="214-11-58820";Owner="강태식";Addr="경북 구미시 형곡동 210"},
    @{Name="구미중앙에너지";BizNo="630-05-91274";Owner="윤서준";Addr="경북 구미시 원평동 45"}
)
$owner1 = "김도현"
$plan1_2026 = @{
    1=@((LI 100 "경유" "지게차용" "지게차 연료" $owner1),(LI 101 "경유" "배송차량용" "배송차량 주유" $owner1))
    2=@((LI 103 "경유" "지게차용" "지게차 연료" $owner1),(LI 104 "경유" "배송차량용" "배송차량 주유" $owner1))
    3=@((LI 99  "경유" "지게차용" "지게차 연료" $owner1),(LI 100 "경유" "배송차량용" "배송차량 주유" $owner1))
    4=@((LI 104 "경유" "지게차용" "지게차 연료" $owner1),(LI 105 "경유" "배송차량용" "배송차량 주유" $owner1))
    5=@((LI 108 "경유" "지게차용" "지게차 연료" $owner1),(LI 109 "경유" "배송차량용" "배송차량 주유" $owner1))
    6=@((LI 112 "경유" "지게차용" "지게차 연료" $owner1),(LI 113 "경유" "배송차량용" "배송차량 주유" $owner1))
    7=@((LI 115 "경유" "지게차용" "지게차 연료" $owner1),(LI 116 "경유" "배송차량용" "배송차량 주유" $owner1))
    8=@((LI 110 "경유" "지게차용" "지게차 연료" $owner1),(LI 111 "경유" "배송차량용" "배송차량 주유" $owner1))
}
Build-TaxInvoices -CompanyId "C001" -CompanyNameKo "구미정밀" -BuyerBizNo "305-81-22147" -BuyerAddr "경북 구미시 산동읍 첨단기업로 33" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup1 -MonthPlan $plan1_2026 -OutDir "$Root\tax_invoices\C001" -Year 2026

$elec1_2026 = @{
    1=@{Kwh=3700;PrevKwh=3750;BilledAmount=725000}
    2=@{Kwh=3800;PrevKwh=3700;BilledAmount=745000}
    3=@{Kwh=3850;PrevKwh=3800;BilledAmount=755000}
    4=@{Kwh=3900;PrevKwh=3850;BilledAmount=764000}
    5=@{Kwh=3950;PrevKwh=3900;BilledAmount=774000}
    6=@{Kwh=4100;PrevKwh=3950;BilledAmount=804000}
    7=@{Kwh=4200;PrevKwh=4100;BilledAmount=823000}
    8=@{Kwh=4250;PrevKwh=4200;BilledAmount=833000}
}
Build-ElectricityBills -CompanyId "C001" -CompanyNameKo "구미정밀" -CustomerNumber "0284-1193-55" -SiteAddr "경북 구미시 산동읍 첨단기업로 33" -ContractType "산업용(을) 저압" -ContractPower "100" -MonthPlan $elec1_2026 -OutDir "$Root\electricity_bills\C001" -Year 2026

# ═══════════════ 대경부품(C002) — Scope1 지속 강세 / Scope2 4개월 주기 추정청구 계속(2·5·8월) ═══════════════
$sup2 = @(
    @{Name="경산셀프주유소";BizNo="501-22-77364";Owner="임재현";Addr="경북 경산시 서상동 12"},
    @{Name="대경에너지";BizNo="339-14-60852";Owner="조은비";Addr="경북 경산시 압량면 부적로 60"}
)
$owner2 = "서지훈"
$plan2_2026 = @{
    1=@((LI 61 "경유" "지게차용" "지게차 연료" $owner2),(LI 28 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    2=@((LI 64 "경유" "지게차용" "지게차 연료" $owner2),(LI 29 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    3=@((LI 59 "경유" "지게차용" "지게차 연료" $owner2),(LI 27 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    4=@((LI 60 "경유" "지게차용" "지게차 연료" $owner2),(LI 27 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    5=@((LI 62 "경유" "지게차용" "지게차 연료" $owner2),(LI 28 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    6=@((LI 65 "경유" "지게차용" "지게차 연료" $owner2),(LI 30 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    7=@((LI 66 "경유" "지게차용" "지게차 연료" $owner2),(LI 31 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    8=@((LI 64 "경유" "지게차용" "지게차 연료" $owner2),(LI 30 "휘발유" "업무차량용" "업무차량 주유" $owner2))
}
Build-TaxInvoices -CompanyId "C002" -CompanyNameKo "대경부품" -BuyerBizNo "128-86-40391" -BuyerAddr "경북 경산시 하양읍 산업로 88" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup2 -MonthPlan $plan2_2026 -OutDir "$Root\tax_invoices\C002" -Year 2026

$elec2_2026 = @{
    1=@{Kwh=2650;PrevKwh=2620;BilledAmount=617000}
    2=@{Kwh=$null;PrevKwh=2650;BilledAmount=617000}
    3=@{Kwh=2700;PrevKwh=2650;BilledAmount=629000}
    4=@{Kwh=2720;PrevKwh=2700;BilledAmount=634000}
    5=@{Kwh=$null;PrevKwh=2720;BilledAmount=634000}
    6=@{Kwh=2750;PrevKwh=2720;BilledAmount=641000}
    7=@{Kwh=2800;PrevKwh=2750;BilledAmount=652000}
    8=@{Kwh=$null;PrevKwh=2800;BilledAmount=652000}
}
Build-ElectricityBills -CompanyId "C002" -CompanyNameKo "대경부품" -CustomerNumber "0517-2260-83" -SiteAddr "경북 경산시 하양읍 산업로 88" -ContractType "산업용(을) 저압" -ContractPower "75" -MonthPlan $elec2_2026 -OutDir "$Root\electricity_bills\C002" -Year 2026

# ═══════════════ 칠곡소재(C004) — 5~9인 벤치마크, 계속 정상 ═══════════════
$sup4 = @( @{Name="칠곡주유소";BizNo="855-07-24916";Owner="문성훈";Addr="경북 칠곡군 왜관읍 중앙로 5"} )
$owner4 = "박은서"
$plan4_2026 = @{
    1=@((LI 56 "경유" "화물차용" "연료 구매" $owner4))
    2=@((LI 52 "경유" "화물차용" "연료 구매" $owner4))
    3=@((LI 61 "경유" "화물차용" "연료 구매" $owner4))
    4=@((LI 59 "경유" "화물차용" "연료 구매" $owner4))
    5=@((LI 36 "경유" "화물차용" "연료 구매" $owner4),(LI 31 "경유" "화물차용" "연료 구매" $owner4))
    6=@((LI 39 "경유" "화물차용" "연료 구매" $owner4),(LI 33 "경유" "화물차용" "연료 구매" $owner4))
    7=@((LI 69 "경유" "화물차용" "연료 구매" $owner4))
    8=@((LI 63 "경유" "화물차용" "연료 구매" $owner4))
}
Build-TaxInvoices -CompanyId "C004" -CompanyNameKo "칠곡소재" -BuyerBizNo "742-58-11029" -BuyerAddr "경북 칠곡군 왜관읍 공단로 15" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup4 -MonthPlan $plan4_2026 -OutDir "$Root\tax_invoices\C004" -Year 2026

$elec4_2026 = @{
    1=@{Kwh=1900;PrevKwh=1980;BilledAmount=526000}; 2=@{Kwh=1930;PrevKwh=1900;BilledAmount=535000}
    3=@{Kwh=1950;PrevKwh=1930;BilledAmount=540000}; 4=@{Kwh=1970;PrevKwh=1950;BilledAmount=546000}
    5=@{Kwh=2020;PrevKwh=1970;BilledAmount=560000}; 6=@{Kwh=2080;PrevKwh=2020;BilledAmount=576000}
    7=@{Kwh=2130;PrevKwh=2080;BilledAmount=590000}; 8=@{Kwh=2150;PrevKwh=2130;BilledAmount=596000}
}
Build-ElectricityBills -CompanyId "C004" -CompanyNameKo "칠곡소재" -CustomerNumber "0663-7702-19" -SiteAddr "경북 칠곡군 왜관읍 공단로 15" -ContractType "일반용(을) 저압" -ContractPower "50" -MonthPlan $elec4_2026 -OutDir "$Root\electricity_bills\C004" -Year 2026

# ═══════════════ 포항이엔지(C005) — 2025년 7~8월 결손은 1회성, 2026년엔 완비로 복귀 ═══════════════
$sup5 = @(
    @{Name="포항해맞이주유소";BizNo="470-19-38225";Owner="배수아";Addr="경북 포항시 남구 오천읍 문충로 30"},
    @{Name="영일대에너지";BizNo="602-33-11487";Owner="신동욱";Addr="경북 포항시 북구 흥해읍 영일만로 8"}
)
$owner5 = "최민준"
$plan5_2026 = @{
    1=@((LI 83 "경유" "지게차용" "지게차 연료" $owner5),(LI 79 "경유" "배송차량용" "배송차량 주유" $owner5))
    2=@((LI 86 "경유" "지게차용" "지게차 연료" $owner5),(LI 81 "경유" "배송차량용" "배송차량 주유" $owner5))
    3=@((LI 81 "경유" "지게차용" "지게차 연료" $owner5),(LI 76 "경유" "배송차량용" "배송차량 주유" $owner5))
    4=@((LI 82 "경유" "지게차용" "지게차 연료" $owner5),(LI 78 "경유" "배송차량용" "배송차량 주유" $owner5))
    5=@((LI 87 "경유" "지게차용" "지게차 연료" $owner5),(LI 83 "경유" "배송차량용" "배송차량 주유" $owner5))
    6=@((LI 91 "경유" "지게차용" "지게차 연료" $owner5),(LI 86 "경유" "배송차량용" "배송차량 주유" $owner5))
    7=@((LI 93 "경유" "지게차용" "지게차 연료" $owner5),(LI 88 "경유" "배송차량용" "배송차량 주유" $owner5))
    8=@((LI 89 "경유" "지게차용" "지게차 연료" $owner5),(LI 85 "경유" "배송차량용" "배송차량 주유" $owner5))
}
Build-TaxInvoices -CompanyId "C005" -CompanyNameKo "포항이엔지" -BuyerBizNo "216-87-93340" -BuyerAddr "경북 포항시 남구 연일읍 산업로 200" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup5 -MonthPlan $plan5_2026 -OutDir "$Root\tax_invoices\C005" -Year 2026

$elec5_2026 = @{
    1=@{Kwh=3150;PrevKwh=3100;BilledAmount=671000}; 2=@{Kwh=3200;PrevKwh=3150;BilledAmount=682000}
    3=@{Kwh=3250;PrevKwh=3200;BilledAmount=692000}; 4=@{Kwh=3300;PrevKwh=3250;BilledAmount=703000}
    5=@{Kwh=3400;PrevKwh=3300;BilledAmount=724000}; 6=@{Kwh=3500;PrevKwh=3400;BilledAmount=746000}
    7=@{Kwh=3600;PrevKwh=3500;BilledAmount=767000}; 8=@{Kwh=3650;PrevKwh=3600;BilledAmount=777000}
}
Build-ElectricityBills -CompanyId "C005" -CompanyNameKo "포항이엔지" -CustomerNumber "0741-5528-40" -SiteAddr "경북 포항시 남구 연일읍 산업로 200" -ContractType "산업용(을) 고압A" -ContractPower "120" -MonthPlan $elec5_2026 -OutDir "$Root\electricity_bills\C005" -Year 2026

# ═══════════════ 대구정공(C006) — 2025년 카페영수증 오염(5·9월)은 1회성, 2026년엔 정상 제출 ═══════════════
$sup6 = @(
    @{Name="북구주유소";BizNo="733-21-59610";Owner="오지민";Addr="대구 북구 침산로 18"},
    @{Name="북대구에너지";BizNo="918-45-30276";Owner="한승우";Addr="대구 북구 유통단지로 66"}
)
$owner6 = "유하은"
$plan6_2026 = @{
    1=@((LI 73 "경유" "지게차용" "지게차 연료" $owner6),(LI 69 "경유" "배송차량용" "배송차량 주유" $owner6))
    2=@((LI 71 "경유" "지게차용" "지게차 연료" $owner6),(LI 66 "경유" "배송차량용" "배송차량 주유" $owner6))
    3=@((LI 75 "경유" "지게차용" "지게차 연료" $owner6),(LI 71 "경유" "배송차량용" "배송차량 주유" $owner6))
    4=@((LI 72 "경유" "지게차용" "지게차 연료" $owner6),(LI 68 "경유" "배송차량용" "배송차량 주유" $owner6))
    5=@((LI 74 "경유" "지게차용" "지게차 연료" $owner6),(LI 70 "경유" "배송차량용" "배송차량 주유" $owner6))
    6=@((LI 76 "경유" "지게차용" "지게차 연료" $owner6),(LI 72 "경유" "배송차량용" "배송차량 주유" $owner6))
    7=@((LI 78 "경유" "지게차용" "지게차 연료" $owner6),(LI 74 "경유" "배송차량용" "배송차량 주유" $owner6))
    8=@((LI 80 "경유" "지게차용" "지게차 연료" $owner6),(LI 76 "경유" "배송차량용" "배송차량 주유" $owner6))
}
Build-TaxInvoices -CompanyId "C006" -CompanyNameKo "대구정공" -BuyerBizNo "189-64-27753" -BuyerAddr "대구 북구 노원로 40" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup6 -MonthPlan $plan6_2026 -OutDir "$Root\tax_invoices\C006" -Year 2026

Write-Host ""
Write-Host "=== 2026년 1~8월 배치 완료 ==="
