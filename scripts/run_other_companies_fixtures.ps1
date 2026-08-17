. (Join-Path $PSScriptRoot "generate_other_companies_fixtures.ps1")

$Root = "C:\Users\wkdud\OneDrive\바탕 화면\감탄\GamTan-dev\data\fixtures"
$BuyerType = "제조업"; $BuyerItem = "기타 금속가공제품 제조"

function LI($liters,$fuel,$spec,$memo,$owner){ @{Liters=$liters;Fuel=$fuel;Spec=$spec;Memo=$memo;BuyerOwner=$owner} }

# ═══════════════ 구미정밀(C001) — 일부 결손 후 보완 가능 ═══════════════
$sup1 = @(
    @{Name="형곡주유소";BizNo="214-11-58820";Owner="강태식";Addr="경북 구미시 형곡동 210"},
    @{Name="구미중앙에너지";BizNo="630-05-91274";Owner="윤서준";Addr="경북 구미시 원평동 45"}
)
$owner1 = "김도현"
$plan1 = @{
    1=@((LI 100 "경유" "지게차용" "지게차 연료" $owner1),(LI 100 "경유" "배송차량용" "배송차량 주유" $owner1))
    2=@((LI 105 "경유" "지게차용" "지게차 연료" $owner1),(LI 105 "경유" "배송차량용" "배송차량 주유" $owner1))
    3=@((LI 98  "경유" "지게차용" "지게차 연료" $owner1),(LI 97  "경유" "배송차량용" "배송차량 주유" $owner1))
    4=@((LI 102 "경유" "지게차용" "지게차 연료" $owner1),(LI 103 "경유" "배송차량용" "배송차량 주유" $owner1))
    5=@((LI 107 "경유" "지게차용" "지게차 연료" $owner1),(LI 108 "경유" "배송차량용" "배송차량 주유" $owner1))
    6=@((LI 112 "경유" "지게차용" "지게차 연료" $owner1),(LI 113 "경유" "배송차량용" "배송차량 주유" $owner1))
    7=@((LI 115 "경유" "지게차용" "지게차 연료" $owner1),(LI 115 "경유" "배송차량용" "배송차량 주유" $owner1))
    8=@((LI 110 "경유" "지게차용" "지게차 연료" $owner1),(LI 110 "경유" "배송차량용" "배송차량 주유" $owner1))
    9=@((LI 105 "경유" "지게차용" "지게차 연료" $owner1),(LI 105 "경유" "배송차량용" "배송차량 주유" $owner1))
    10=@((LI 100 "경유" "지게차용" "지게차 연료" $owner1),(LI 100 "경유" "배송차량용" "배송차량 주유" $owner1))
    11=@((LI 97  "경유" "지게차용" "지게차 연료" $owner1),(LI 98  "경유" "배송차량용" "배송차량 주유" $owner1))
    12=@((LI 102 "경유" "지게차용" "지게차 연료" $owner1),(LI 103 "경유" "배송차량용" "배송차량 주유" $owner1))
}
Build-TaxInvoices -CompanyId "C001" -CompanyNameKo "구미정밀" -BuyerBizNo "305-81-22147" -BuyerAddr "경북 구미시 산동읍 첨단기업로 33" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup1 -MonthPlan $plan1 -OutDir "$Root\tax_invoices\C001"

$elec1 = @{
    1=@{Kwh=3300;PrevKwh=3200;BilledAmount=677000}
    # 2월 결손 — 파일 없음
    3=@{Kwh=3450;PrevKwh=3300;BilledAmount=692000}
    4=@{Kwh=3500;PrevKwh=3450;BilledAmount=697000}
    5=@{Kwh=3600;PrevKwh=3500;BilledAmount=707000}
    6=@{Kwh=3800;PrevKwh=3600;BilledAmount=728000}
    7=@{Kwh=3900;PrevKwh=3800;BilledAmount=738000}
    8=@{Kwh=3950;PrevKwh=3900;BilledAmount=743000}
    9=@{Kwh=3700;PrevKwh=3950;BilledAmount=718000}
    10=@{Kwh=3550;PrevKwh=3700;BilledAmount=702000}
    11=@{Kwh=3600;PrevKwh=3550;BilledAmount=707000}
    12=@{Kwh=3750;PrevKwh=3600;BilledAmount=723000}
}
Build-ElectricityBills -CompanyId "C001" -CompanyNameKo "구미정밀" -CustomerNumber "0284-1193-55" -SiteAddr "경북 구미시 산동읍 첨단기업로 33" -ContractType "산업용(을) 저압" -ContractPower "100" -MonthPlan $elec1 -OutDir "$Root\electricity_bills\C001"

# ═══════════════ 대경부품(C002) — Scope1 강함 / Scope2 부실(금액만) ═══════════════
$sup2 = @(
    @{Name="경산셀프주유소";BizNo="501-22-77364";Owner="임재현";Addr="경북 경산시 서상동 12"},
    @{Name="대경에너지";BizNo="339-14-60852";Owner="조은비";Addr="경북 경산시 압량면 부적로 60"}
)
$owner2 = "서지훈"
$plan2 = @{
    1=@((LI 60 "경유" "지게차용" "지게차 연료" $owner2),(LI 28 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    2=@((LI 63 "경유" "지게차용" "지게차 연료" $owner2),(LI 29 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    3=@((LI 58 "경유" "지게차용" "지게차 연료" $owner2),(LI 27 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    4=@((LI 59 "경유" "지게차용" "지게차 연료" $owner2),(LI 27 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    5=@((LI 61 "경유" "지게차용" "지게차 연료" $owner2),(LI 28 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    6=@((LI 64 "경유" "지게차용" "지게차 연료" $owner2),(LI 30 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    7=@((LI 65 "경유" "지게차용" "지게차 연료" $owner2),(LI 31 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    8=@((LI 63 "경유" "지게차용" "지게차 연료" $owner2),(LI 30 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    9=@((LI 60 "경유" "지게차용" "지게차 연료" $owner2),(LI 28 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    10=@((LI 58 "경유" "지게차용" "지게차 연료" $owner2),(LI 27 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    11=@((LI 59 "경유" "지게차용" "지게차 연료" $owner2),(LI 27 "휘발유" "업무차량용" "업무차량 주유" $owner2))
    12=@((LI 63 "경유" "지게차용" "지게차 연료" $owner2),(LI 29 "휘발유" "업무차량용" "업무차량 주유" $owner2))
}
Build-TaxInvoices -CompanyId "C002" -CompanyNameKo "대경부품" -BuyerBizNo "128-86-40391" -BuyerAddr "경북 경산시 하양읍 산업로 88" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup2 -MonthPlan $plan2 -OutDir "$Root\tax_invoices\C002"

$elec2 = @{
    1=@{Kwh=2450;PrevKwh=2400;BilledAmount=590000}
    2=@{Kwh=$null;PrevKwh=2450;BilledAmount=590000}
    3=@{Kwh=2500;PrevKwh=2450;BilledAmount=596000}
    4=@{Kwh=2550;PrevKwh=2500;BilledAmount=601000}
    5=@{Kwh=$null;PrevKwh=2550;BilledAmount=601000}
    6=@{Kwh=2600;PrevKwh=2550;BilledAmount=606000}
    7=@{Kwh=2700;PrevKwh=2600;BilledAmount=616000}
    8=@{Kwh=$null;PrevKwh=2700;BilledAmount=616000}
    9=@{Kwh=2650;PrevKwh=2700;BilledAmount=611000}
    10=@{Kwh=2580;PrevKwh=2650;BilledAmount=604000}
    11=@{Kwh=$null;PrevKwh=2580;BilledAmount=604000}
    12=@{Kwh=2620;PrevKwh=2580;BilledAmount=608000}
}
Build-ElectricityBills -CompanyId "C002" -CompanyNameKo "대경부품" -CustomerNumber "0517-2260-83" -SiteAddr "경북 경산시 하양읍 산업로 88" -ContractType "산업용(을) 저압" -ContractPower "75" -MonthPlan $elec2 -OutDir "$Root\electricity_bills\C002"

# ═══════════════ 칠곡소재(C004) — 5~9인 소규모 벤치마크 기업(정상) ═══════════════
$sup4 = @( @{Name="칠곡주유소";BizNo="855-07-24916";Owner="문성훈";Addr="경북 칠곡군 왜관읍 중앙로 5"} )
$owner4 = "박은서"
$plan4 = @{
    1=@((LI 55 "경유" "화물차용" "연료 구매" $owner4))
    2=@((LI 50 "경유" "화물차용" "연료 구매" $owner4))
    3=@((LI 60 "경유" "화물차용" "연료 구매" $owner4))
    4=@((LI 58 "경유" "화물차용" "연료 구매" $owner4))
    5=@((LI 35 "경유" "화물차용" "연료 구매" $owner4),(LI 30 "경유" "화물차용" "연료 구매" $owner4))
    6=@((LI 38 "경유" "화물차용" "연료 구매" $owner4),(LI 32 "경유" "화물차용" "연료 구매" $owner4))
    7=@((LI 68 "경유" "화물차용" "연료 구매" $owner4))
    8=@((LI 62 "경유" "화물차용" "연료 구매" $owner4))
    9=@((LI 58 "경유" "화물차용" "연료 구매" $owner4))
    10=@((LI 52 "경유" "화물차용" "연료 구매" $owner4))
    11=@((LI 56 "경유" "화물차용" "연료 구매" $owner4))
    12=@((LI 60 "경유" "화물차용" "연료 구매" $owner4))
}
Build-TaxInvoices -CompanyId "C004" -CompanyNameKo "칠곡소재" -BuyerBizNo "742-58-11029" -BuyerAddr "경북 칠곡군 왜관읍 공단로 15" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup4 -MonthPlan $plan4 -OutDir "$Root\tax_invoices\C004"

$elec4 = @{
    1=@{Kwh=1850;PrevKwh=1800;BilledAmount=529000}; 2=@{Kwh=1880;PrevKwh=1850;BilledAmount=533000}
    3=@{Kwh=1900;PrevKwh=1880;BilledAmount=535000}; 4=@{Kwh=1920;PrevKwh=1900;BilledAmount=537000}
    5=@{Kwh=1980;PrevKwh=1920;BilledAmount=543000}; 6=@{Kwh=2050;PrevKwh=1980;BilledAmount=550000}
    7=@{Kwh=2100;PrevKwh=2050;BilledAmount=555000}; 8=@{Kwh=2120;PrevKwh=2100;BilledAmount=557000}
    9=@{Kwh=2000;PrevKwh=2120;BilledAmount=545000}; 10=@{Kwh=1950;PrevKwh=2000;BilledAmount=540000}
    11=@{Kwh=1900;PrevKwh=1950;BilledAmount=535000}; 12=@{Kwh=1980;PrevKwh=1900;BilledAmount=543000}
}
Build-ElectricityBills -CompanyId "C004" -CompanyNameKo "칠곡소재" -CustomerNumber "0663-7702-19" -SiteAddr "경북 칠곡군 왜관읍 공단로 15" -ContractType "일반용(을) 저압" -ContractPower "50" -MonthPlan $elec4 -OutDir "$Root\electricity_bills\C004"

# ═══════════════ 포항이엔지(C005) — 7~8월 전체 누락 ═══════════════
$sup5 = @(
    @{Name="포항해맞이주유소";BizNo="470-19-38225";Owner="배수아";Addr="경북 포항시 남구 오천읍 문충로 30"},
    @{Name="영일대에너지";BizNo="602-33-11487";Owner="신동욱";Addr="경북 포항시 북구 흥해읍 영일만로 8"}
)
$owner5 = "최민준"
$plan5 = @{
    1=@((LI 82 "경유" "지게차용" "지게차 연료" $owner5),(LI 78 "경유" "배송차량용" "배송차량 주유" $owner5))
    2=@((LI 85 "경유" "지게차용" "지게차 연료" $owner5),(LI 80 "경유" "배송차량용" "배송차량 주유" $owner5))
    3=@((LI 80 "경유" "지게차용" "지게차 연료" $owner5),(LI 75 "경유" "배송차량용" "배송차량 주유" $owner5))
    4=@((LI 81 "경유" "지게차용" "지게차 연료" $owner5),(LI 77 "경유" "배송차량용" "배송차량 주유" $owner5))
    5=@((LI 86 "경유" "지게차용" "지게차 연료" $owner5),(LI 82 "경유" "배송차량용" "배송차량 주유" $owner5))
    6=@((LI 90 "경유" "지게차용" "지게차 연료" $owner5),(LI 85 "경유" "배송차량용" "배송차량 주유" $owner5))
    # 7~8월: 서류 전면 누락 (파일 자체를 만들지 않음)
    9=@((LI 87 "경유" "지게차용" "지게차 연료" $owner5),(LI 83 "경유" "배송차량용" "배송차량 주유" $owner5))
    10=@((LI 83 "경유" "지게차용" "지게차 연료" $owner5),(LI 79 "경유" "배송차량용" "배송차량 주유" $owner5))
    11=@((LI 80 "경유" "지게차용" "지게차 연료" $owner5),(LI 78 "경유" "배송차량용" "배송차량 주유" $owner5))
    12=@((LI 84 "경유" "지게차용" "지게차 연료" $owner5),(LI 81 "경유" "배송차량용" "배송차량 주유" $owner5))
}
Build-TaxInvoices -CompanyId "C005" -CompanyNameKo "포항이엔지" -BuyerBizNo "216-87-93340" -BuyerAddr "경북 포항시 남구 연일읍 산업로 200" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup5 -MonthPlan $plan5 -OutDir "$Root\tax_invoices\C005"

$elec5 = @{
    1=@{Kwh=2950;PrevKwh=2900;BilledAmount=641000}; 2=@{Kwh=3000;PrevKwh=2950;BilledAmount=646000}
    3=@{Kwh=3050;PrevKwh=3000;BilledAmount=652000}; 4=@{Kwh=3100;PrevKwh=3050;BilledAmount=657000}
    5=@{Kwh=3200;PrevKwh=3100;BilledAmount=667000}; 6=@{Kwh=3300;PrevKwh=3200;BilledAmount=677000}
    # 7~8월: 전기고지서도 전면 누락
    9=@{Kwh=3250;PrevKwh=3300;BilledAmount=672000}; 10=@{Kwh=3150;PrevKwh=3250;BilledAmount=662000}
    11=@{Kwh=3050;PrevKwh=3150;BilledAmount=652000}; 12=@{Kwh=3100;PrevKwh=3050;BilledAmount=657000}
}
Build-ElectricityBills -CompanyId "C005" -CompanyNameKo "포항이엔지" -CustomerNumber "0741-5528-40" -SiteAddr "경북 포항시 남구 연일읍 산업로 200" -ContractType "산업용(을) 고압A" -ContractPower "120" -MonthPlan $elec5 -OutDir "$Root\electricity_bills\C005"

# ═══════════════ 대구정공(C006) — 이상한 데이터 업로드(관계없는 파일) ═══════════════
$sup6 = @(
    @{Name="북구주유소";BizNo="733-21-59610";Owner="오지민";Addr="대구 북구 침산로 18"},
    @{Name="북대구에너지";BizNo="918-45-30276";Owner="한승우";Addr="대구 북구 유통단지로 66"}
)
$owner6 = "유하은"
$plan6 = @{
    1=@((LI 72 "경유" "지게차용" "지게차 연료" $owner6),(LI 68 "경유" "배송차량용" "배송차량 주유" $owner6))
    2=@((LI 70 "경유" "지게차용" "지게차 연료" $owner6),(LI 65 "경유" "배송차량용" "배송차량 주유" $owner6))
    3=@((LI 74 "경유" "지게차용" "지게차 연료" $owner6),(LI 70 "경유" "배송차량용" "배송차량 주유" $owner6))
    4=@((LI 71 "경유" "지게차용" "지게차 연료" $owner6),(LI 67 "경유" "배송차량용" "배송차량 주유" $owner6))
    # 5월: 진짜 연료 서류 없이 무관한 카페 영수증만 업로드됨(아래 Build-IrrelevantFiles)
    6=@((LI 73 "경유" "지게차용" "지게차 연료" $owner6),(LI 69 "경유" "배송차량용" "배송차량 주유" $owner6))
    7=@((LI 76 "경유" "지게차용" "지게차 연료" $owner6),(LI 72 "경유" "배송차량용" "배송차량 주유" $owner6))
    8=@((LI 78 "경유" "지게차용" "지게차 연료" $owner6),(LI 74 "경유" "배송차량용" "배송차량 주유" $owner6))
    # 9월: 마찬가지로 무관한 파일만 업로드됨
    10=@((LI 74 "경유" "지게차용" "지게차 연료" $owner6),(LI 70 "경유" "배송차량용" "배송차량 주유" $owner6))
    11=@((LI 71 "경유" "지게차용" "지게차 연료" $owner6),(LI 68 "경유" "배송차량용" "배송차량 주유" $owner6))
    12=@((LI 75 "경유" "지게차용" "지게차 연료" $owner6),(LI 71 "경유" "배송차량용" "배송차량 주유" $owner6))
}
Build-TaxInvoices -CompanyId "C006" -CompanyNameKo "대구정공" -BuyerBizNo "189-64-27753" -BuyerAddr "대구 북구 노원로 40" -BuyerType $BuyerType -BuyerItem $BuyerItem -Suppliers $sup6 -MonthPlan $plan6 -OutDir "$Root\tax_invoices\C006"

$receipts6 = @(
    @{ShopName="카페 온기";ShopAddr="대구 북구 침산로 22";Item1="아메리카노";Item1Price="4,500";Item2="카페라떼";Item2Price="5,000";Total="9,500";Date="2025-05-14";Time="14:32"},
    @{ShopName="카페 온기";ShopAddr="대구 북구 침산로 22";Item1="아메리카노";Item1Price="4,500";Item2="크루아상";Item2Price="3,800";Total="8,300";Date="2025-09-09";Time="09:15"}
)
Build-IrrelevantFiles -CompanyId "C006" -CompanyNameKo "대구정공" -Receipts $receipts6 -OutDir "$Root\tax_invoices\C006"

Write-Host ""
Write-Host "=== 전체 완료 ==="
