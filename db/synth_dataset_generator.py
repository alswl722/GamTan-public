"""감탄 합성데이터셋 생성기 — 17개 시트 통합 워크북.

기준 문서: 합성데이터_제작가이드.md (합성데이터 제작 가이드).
db/synth_generator.py(대량 전표 벌크 생성)와는 목적이 다르다 — 이 스크립트는
스케일이 아니라 "서비스 흐름 전체(마이데이터→업로드→분류→계산→PCAF 품질→
HITL→K-택소노미→은행 대시보드)"를 시나리오 단위로 완결성 있게 검증하기 위한
소규모(4개 기업, 15개 시나리오) 데이터셋을 만든다.

데이터는 절차적 난수가 아니라 가이드에 명시된 예시값을 그대로 채택하고,
가이드 5절의 15개 시나리오(SCE001~SCE015) 중 예시에 빠진 4개
(SCE005 전기 kWh 미기재 / SCE007 도시가스 금액만 / SCE014 유지보수비 불명확
설비투자 / SCE015 동일 전표 중복 업로드)를 보강해 전체 시나리오를 채운다.
값 자체가 고정이므로 재실행해도 항상 같은 워크북이 나온다(재현성).

사용:
  python -m db.synth_dataset_generator --out data/감탄_합성데이터_v1.xlsx
"""
import argparse
import os

from openpyxl import Workbook

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "감탄_합성데이터_v1.xlsx"
)


# ────────────────────────── 1. README ──────────────────────────
def sheet_readme():
    cols = ["항목", "내용"]
    rows = [
        {"항목": "데이터셋 목적", "내용": "영세 소부장 기업의 실제 전표·고지서 구조를 반영한 감탄 MVP 검증용 합성데이터"},
        {"항목": "기준기간", "내용": "2025년 1월~6월 중 일부 월"},
        {"항목": "대상기업", "내용": "대구·경북 지역 제조업(금속가공·전자부품·표면처리·플라스틱부품) 가상 기업 4개"},
        {"항목": "주요 입력자료", "내용": "세금계산서, 영수증, 전기요금 고지서, 도시가스 고지서, 마이데이터 확인자료"},
        {"항목": "주요 검증항목", "내용": "Scope 1/2 분류, 배출량 계산, 데이터 품질점수, HITL 분기, K-택소노미 후보 탐지, 설비금융 리드"},
        {"항목": "주의사항", "내용": "본 데이터는 실제 기업 자료가 아닌 공모전 MVP 검증용 합성데이터임. 사업자번호·거래처명 모두 가상값."},
        {"항목": "생성 스크립트", "내용": "db/synth_dataset_generator.py (python -m db.synth_dataset_generator)"},
        {"항목": "생성 기준 문서", "내용": "합성데이터_제작가이드.md 합성데이터 제작 가이드 (2026-08-12 반입)"},
        {"항목": "포함 시나리오", "내용": "SCE001~SCE015 전체 15개 (자동계산·금액역산·HITL·K-택소노미·설비투자·중복업로드)"},
        {"항목": "기존 데이터와의 관계", "내용": "data/감탄_데이터준비_샘플.xlsx(db/excel_loader.py가 읽는 운영 시트)와는 별개 파일 — 스키마 충돌 없음"},
        {"항목": "금융 mock 데이터 주의", "내용": "bank_loans_mock·portfolio_dashboard_mock의 여신잔액·귀속계수·금융배출량은 전부 시연용 mock, 실제 데이터 아님"},
    ]
    return cols, rows


# ────────────────────────── 2. company_master ──────────────────────────
def sheet_company_master():
    cols = [
        "company_id", "company_name", "business_number", "region", "industry",
        "ksic_code", "employee_count", "annual_revenue_krw", "is_sme",
        "main_energy_type", "has_electricity", "has_diesel", "has_gasoline",
        "has_citygas", "has_lpg", "created_at",
    ]
    rows = [
        dict(company_id="C001", company_name="구미정밀", business_number="123-45-67890",
             region="경북 구미", industry="금속가공", ksic_code="C259", employee_count=18,
             annual_revenue_krw=2_500_000_000, is_sme="Y", main_energy_type="전기, 경유",
             has_electricity="Y", has_diesel="Y", has_gasoline="N", has_citygas="N", has_lpg="N",
             created_at="2026-08-12"),
        dict(company_id="C002", company_name="대경부품", business_number="111-22-33333",
             region="경북 경산", industry="전자부품", ksic_code="C264", employee_count=12,
             annual_revenue_krw=1_800_000_000, is_sme="Y", main_energy_type="전기, 도시가스",
             has_electricity="Y", has_diesel="N", has_gasoline="Y", has_citygas="Y", has_lpg="N",
             created_at="2026-08-12"),
        dict(company_id="C003", company_name="성서테크", business_number="444-55-66666",
             region="대구 달서", industry="표면처리", ksic_code="C242", employee_count=25,
             annual_revenue_krw=3_200_000_000, is_sme="Y", main_energy_type="전기, 경유, 도시가스",
             has_electricity="Y", has_diesel="Y", has_citygas="Y", has_gasoline="N", has_lpg="UNKNOWN",
             created_at="2026-08-12"),
        dict(company_id="C004", company_name="칠곡소재", business_number="222-33-44444",
             region="경북 칠곡", industry="플라스틱 부품", ksic_code="C222", employee_count=9,
             annual_revenue_krw=950_000_000, is_sme="Y", main_energy_type="전기, LPG",
             has_electricity="Y", has_diesel="N", has_gasoline="N", has_citygas="N", has_lpg="Y",
             created_at="2026-08-12"),
    ]
    return cols, rows


# ────────────────────────── 3. mydata_documents ──────────────────────────
def sheet_mydata_documents():
    cols = ["doc_id", "company_id", "provider", "document_name", "collected_by",
            "collected_status", "key_fields", "used_for", "limitation"]
    rows = [
        dict(doc_id="MD001", company_id="C001", provider="국세청", document_name="사업자등록증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="사업자번호, 기업명",
             used_for="기업 식별", limitation="탄소 사용량 정보 없음"),
        dict(doc_id="MD002", company_id="C001", provider="국세청", document_name="부가가치세과세표준증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="매출 규모",
             used_for="매출 규모 확인", limitation="품목별 에너지 사용량 없음"),
        dict(doc_id="MD003", company_id="C001", provider="국세청", document_name="표준재무제표증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="자산·부채·자본",
             used_for="재무정보 확인", limitation="은행 내부 여신 데이터와 별도 연동 필요"),
        dict(doc_id="MD004", company_id="C001", provider="중소벤처기업부", document_name="중소기업확인서",
             collected_by="마이데이터", collected_status="확인완료", key_fields="중소기업 여부",
             used_for="중소기업 여부 확인", limitation="배출량 정보 없음"),
        dict(doc_id="MD005", company_id="C001", provider="한국전력공사", document_name="전기요금 납부내역",
             collected_by="마이데이터", collected_status="확인완료", key_fields="납부금액, 납부일",
             used_for="전기 자료 보조", limitation="kWh 포함 여부 확인 필요"),
        dict(doc_id="MD006", company_id="C002", provider="국세청", document_name="사업자등록증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="사업자번호, 기업명",
             used_for="기업 식별", limitation="탄소 사용량 정보 없음"),
        dict(doc_id="MD007", company_id="C002", provider="중소벤처기업부", document_name="중소기업확인서",
             collected_by="마이데이터", collected_status="확인완료", key_fields="중소기업 여부",
             used_for="중소기업 여부 확인", limitation="배출량 정보 없음"),
        dict(doc_id="MD008", company_id="C003", provider="국세청", document_name="사업자등록증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="사업자번호, 기업명",
             used_for="기업 식별", limitation="탄소 사용량 정보 없음"),
        dict(doc_id="MD009", company_id="C003", provider="국세청", document_name="표준재무제표증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="자산·부채·자본",
             used_for="재무정보 확인", limitation="은행 내부 여신 데이터와 별도 연동 필요"),
        dict(doc_id="MD010", company_id="C004", provider="국세청", document_name="사업자등록증명",
             collected_by="마이데이터", collected_status="확인완료", key_fields="사업자번호, 기업명",
             used_for="기업 식별", limitation="탄소 사용량 정보 없음"),
        dict(doc_id="MD011", company_id="C004", provider="중소벤처기업부", document_name="중소기업확인서",
             collected_by="마이데이터", collected_status="확인완료", key_fields="중소기업 여부",
             used_for="중소기업 여부 확인", limitation="배출량 정보 없음"),
    ]
    return cols, rows


# ────────────────────────── 4. uploaded_files ──────────────────────────
def sheet_uploaded_files():
    cols = ["file_id", "company_id", "file_name", "file_type", "document_type",
            "period_month", "upload_source", "parse_status", "reject_status",
            "reject_reason", "linked_record_id"]
    rows = [
        dict(file_id="F001", company_id="C001", file_name="2025_03_경유_세금계산서.pdf", file_type="PDF",
             document_type="세금계산서", period_month="2025-03", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV001"),
        dict(file_id="F002", company_id="C001", file_name="2025_03_전기고지서.pdf", file_type="PDF",
             document_type="전기고지서", period_month="2025-03", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="ELEC001"),
        dict(file_id="F003", company_id="C003", file_name="2025_04_LPG_영수증.jpg", file_type="JPG",
             document_type="영수증", period_month="2025-04", upload_source="기업 업로드",
             parse_status="부분성공", reject_status="N", reject_reason="품목·단위 불명확", linked_record_id="INV004"),
        dict(file_id="F004", company_id="C002", file_name="식비영수증.jpg", file_type="JPG",
             document_type="기타", period_month="2025-04", upload_source="기업 업로드",
             parse_status="실패", reject_status="Y", reject_reason="탄소계산과 무관한 파일", linked_record_id=""),
        dict(file_id="F005", company_id="C001", file_name="2025_03_경유_세금계산서(2).pdf", file_type="PDF",
             document_type="세금계산서", period_month="2025-03", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV010"),
        dict(file_id="F006", company_id="C004", file_name="2025_03_전기요금_납부내역.pdf", file_type="PDF",
             document_type="전기고지서", period_month="2025-03", upload_source="기업 업로드",
             parse_status="부분성공", reject_status="N", reject_reason="사용량 kWh 미기재", linked_record_id="ELEC005"),
        dict(file_id="F007", company_id="C004", file_name="2025_03_도시가스_요금고지서.pdf", file_type="PDF",
             document_type="도시가스고지서", period_month="2025-03", upload_source="기업 업로드",
             parse_status="부분성공", reject_status="N", reject_reason="사용량 m³ 미기재, 청구금액만 확인", linked_record_id="GAS004"),
        dict(file_id="F008", company_id="C001", file_name="2025_05_유지보수비_영수증.jpg", file_type="JPG",
             document_type="영수증", period_month="2025-05", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV009"),
        dict(file_id="F009", company_id="C001", file_name="2025_03_경유_영수증.jpg", file_type="JPG",
             document_type="영수증", period_month="2025-03", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV002"),
        dict(file_id="F010", company_id="C002", file_name="2025_03_휘발유_영수증.jpg", file_type="JPG",
             document_type="영수증", period_month="2025-03", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV003"),
        dict(file_id="F011", company_id="C001", file_name="2025_05_설비_세금계산서.pdf", file_type="PDF",
             document_type="세금계산서", period_month="2025-05", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV005"),
        dict(file_id="F012", company_id="C002", file_name="2025_05_태양광_세금계산서.pdf", file_type="PDF",
             document_type="세금계산서", period_month="2025-05", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV006"),
        dict(file_id="F013", company_id="C003", file_name="2025_05_지게차리스_세금계산서.pdf", file_type="PDF",
             document_type="세금계산서", period_month="2025-05", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV007"),
        dict(file_id="F014", company_id="C004", file_name="2025_06_절삭유_세금계산서.pdf", file_type="PDF",
             document_type="세금계산서", period_month="2025-06", upload_source="기업 업로드",
             parse_status="성공", reject_status="N", reject_reason="", linked_record_id="INV008"),
    ]
    return cols, rows


# ────────────────────────── 5. tax_invoices_receipts ──────────────────────────
def sheet_tax_invoices_receipts():
    cols = ["record_id", "company_id", "source_file_id", "document_type", "issue_date",
            "supplier_name", "supplier_business_number", "buyer_name", "item_name",
            "specification", "quantity", "unit", "unit_price_krw", "supply_amount_krw",
            "vat_krw", "total_amount_krw", "memo", "ocr_text"]

    def vat(supply):
        v = round(supply * 0.1)
        return v, supply + v

    rows = []

    v, t = vat(169_639)
    rows.append(dict(record_id="INV001", company_id="C001", source_file_id="F001",
        document_type="세금계산서", issue_date="2025-03-15", supplier_name="구미에너지주유소",
        supplier_business_number="333-11-22222", buyer_name="구미정밀", item_name="경유",
        specification="지게차용", quantity=120, unit="L", unit_price_krw=1413.66,
        supply_amount_krw=169_639, vat_krw=v, total_amount_krw=t, memo="3월 지게차 연료",
        ocr_text="경유 120L 공급가액 169,639원"))

    v, t = vat(280_000)
    rows.append(dict(record_id="INV002", company_id="C001", source_file_id="F009",
        document_type="영수증", issue_date="2025-03-08", supplier_name="대구주유소",
        supplier_business_number="222-11-00000", buyer_name="구미정밀", item_name="경유",
        specification="", quantity=None, unit=None, unit_price_krw=None,
        supply_amount_krw=280_000, vat_krw=v, total_amount_krw=t, memo="수량 없음, 금액만 있음(3월 월별단가로 역산)",
        ocr_text="경유 대금 280,000원"))

    v, t = vat(122_831)
    rows.append(dict(record_id="INV003", company_id="C002", source_file_id="F010",
        document_type="영수증", issue_date="2025-03-20", supplier_name="경산에너지",
        supplier_business_number="555-22-11111", buyer_name="대경부품", item_name="휘발유",
        specification="업무차량", quantity=80, unit="L", unit_price_krw=1535.39,
        supply_amount_krw=122_831, vat_krw=v, total_amount_krw=t, memo="업무차량 주유",
        ocr_text="휘발유 80L 공급가액 122,831원"))

    v, t = vat(280_000)
    rows.append(dict(record_id="INV004", company_id="C003", source_file_id="F003",
        document_type="영수증", issue_date="2025-04-05", supplier_name="OO충전소",
        supplier_business_number="666-33-22222", buyer_name="성서테크", item_name="LPG 외 1종",
        specification="", quantity=None, unit=None, unit_price_krw=None,
        supply_amount_krw=280_000, vat_krw=v, total_amount_krw=t, memo="품목·단위 불명확",
        ocr_text="LPG 외 1종 280,000원"))

    v, t = vat(5_000_000)
    rows.append(dict(record_id="INV005", company_id="C001", source_file_id="F011",
        document_type="세금계산서", issue_date="2025-05-02", supplier_name="대한기계",
        supplier_business_number="777-44-33333", buyer_name="구미정밀", item_name="고효율 압축기",
        specification="15kW", quantity=1, unit="대", unit_price_krw=5_000_000,
        supply_amount_krw=5_000_000, vat_krw=v, total_amount_krw=t, memo="노후 압축기 교체",
        ocr_text="고효율 압축기 15kW 1대 공급가액 5,000,000원"))

    v, t = vat(30_000_000)
    rows.append(dict(record_id="INV006", company_id="C002", source_file_id="F012",
        document_type="세금계산서", issue_date="2025-05-10", supplier_name="솔라테크",
        supplier_business_number="888-55-44444", buyer_name="대경부품", item_name="태양광 설비 설치",
        specification="20kW", quantity=1, unit="식", unit_price_krw=30_000_000,
        supply_amount_krw=30_000_000, vat_krw=v, total_amount_krw=t, memo="공장 지붕 태양광",
        ocr_text="태양광 설비 설치 20kW 공급가액 30,000,000원"))

    v, t = vat(1_200_000)
    rows.append(dict(record_id="INV007", company_id="C003", source_file_id="F013",
        document_type="세금계산서", issue_date="2025-05-15", supplier_name="전동물류",
        supplier_business_number="999-66-55555", buyer_name="성서테크", item_name="전동지게차 리스료",
        specification="", quantity=1, unit="대", unit_price_krw=1_200_000,
        supply_amount_krw=1_200_000, vat_krw=v, total_amount_krw=t, memo="월 리스료",
        ocr_text="전동지게차 리스료 1대 월 1,200,000원"))

    v, t = vat(100_000)
    rows.append(dict(record_id="INV008", company_id="C004", source_file_id="F014",
        document_type="세금계산서", issue_date="2025-06-01", supplier_name="부품상사",
        supplier_business_number="123-99-88888", buyer_name="칠곡소재", item_name="절삭유",
        specification="", quantity=20, unit="L", unit_price_krw=5_000,
        supply_amount_krw=100_000, vat_krw=v, total_amount_krw=t, memo="생산 소모품",
        ocr_text="절삭유 20L 공급가액 100,000원"))

    v, t = vat(850_000)
    rows.append(dict(record_id="INV009", company_id="C001", source_file_id="F008",
        document_type="영수증", issue_date="2025-05-20", supplier_name="구미설비유지",
        supplier_business_number="321-88-77777", buyer_name="구미정밀", item_name="유지보수비",
        specification="공조설비 정기점검", quantity=None, unit=None, unit_price_krw=None,
        supply_amount_krw=850_000, vat_krw=v, total_amount_krw=t,
        memo="정기 유지보수, 신규 설비투자 여부 불명확(SCE014)", ocr_text="설비 유지보수비 850,000원"))

    v, t = vat(169_639)
    rows.append(dict(record_id="INV010", company_id="C001", source_file_id="F005",
        document_type="세금계산서", issue_date="2025-03-15", supplier_name="구미에너지주유소",
        supplier_business_number="333-11-22222", buyer_name="구미정밀", item_name="경유",
        specification="지게차용", quantity=120, unit="L", unit_price_krw=1413.66,
        supply_amount_krw=169_639, vat_krw=v, total_amount_krw=t,
        memo="INV001과 동일 문서 중복 업로드(중복 제외 검증용, SCE015)",
        ocr_text="경유 120L 공급가액 169,639원"))

    return cols, rows


# ────────────────────────── 6. electricity_bills ──────────────────────────
def sheet_electricity_bills():
    cols = ["bill_id", "company_id", "source_file_id", "provider", "customer_number",
            "site_name", "usage_month", "period_start", "period_end", "electricity_kwh",
            "billed_amount_krw", "contract_type", "ocr_confidence"]
    rows = [
        dict(bill_id="ELEC001", company_id="C001", source_file_id="F002", provider="한국전력공사",
             customer_number="1234567890", site_name="구미정밀 본공장", usage_month="2025-03",
             period_start="2025-03-01", period_end="2025-03-31", electricity_kwh=3000,
             billed_amount_krw=450_000, contract_type="산업용", ocr_confidence=0.96),
        dict(bill_id="ELEC002", company_id="C001", source_file_id="", provider="한국전력공사",
             customer_number="1234567890", site_name="구미정밀 본공장", usage_month="2025-04",
             period_start="2025-04-01", period_end="2025-04-30", electricity_kwh=2800,
             billed_amount_krw=420_000, contract_type="산업용", ocr_confidence=0.96),
        dict(bill_id="ELEC003", company_id="C002", source_file_id="", provider="한국전력공사",
             customer_number="2233445566", site_name="대경부품 본사", usage_month="2025-03",
             period_start="2025-03-01", period_end="2025-03-31", electricity_kwh=2100,
             billed_amount_krw=315_000, contract_type="일반용", ocr_confidence=0.95),
        dict(bill_id="ELEC004", company_id="C003", source_file_id="", provider="한국전력공사",
             customer_number="3344556677", site_name="성서테크 공장동", usage_month="2025-04",
             period_start="2025-04-01", period_end="2025-04-30", electricity_kwh=5200,
             billed_amount_krw=780_000, contract_type="산업용", ocr_confidence=0.94),
        dict(bill_id="ELEC005", company_id="C004", source_file_id="F006", provider="한국전력공사",
             customer_number="4455667788", site_name="칠곡소재 본공장", usage_month="2025-03",
             period_start="2025-03-01", period_end="2025-03-31", electricity_kwh=None,
             billed_amount_krw=380_000, contract_type="일반용", ocr_confidence=0.55),
    ]
    return cols, rows


# ────────────────────────── 7. citygas_bills ──────────────────────────
def sheet_citygas_bills():
    cols = ["bill_id", "company_id", "source_file_id", "provider", "customer_number",
            "site_name", "usage_month", "gas_usage_amount", "gas_usage_unit",
            "billed_amount_krw", "usage_type", "ocr_confidence"]
    rows = [
        dict(bill_id="GAS001", company_id="C002", source_file_id="", provider="영남에너지서비스",
             customer_number="G123456", site_name="대경부품 본사", usage_month="2025-03",
             gas_usage_amount=520, gas_usage_unit="m³", billed_amount_krw=390_000,
             usage_type="산업용", ocr_confidence=0.93),
        dict(bill_id="GAS002", company_id="C002", source_file_id="", provider="영남에너지서비스",
             customer_number="G123456", site_name="대경부품 본사", usage_month="2025-04",
             gas_usage_amount=480, gas_usage_unit="m³", billed_amount_krw=360_000,
             usage_type="산업용", ocr_confidence=0.93),
        dict(bill_id="GAS003", company_id="C003", source_file_id="", provider="대성에너지",
             customer_number="G654321", site_name="성서테크 공장동", usage_month="2025-04",
             gas_usage_amount=950, gas_usage_unit="m³", billed_amount_krw=720_000,
             usage_type="산업용", ocr_confidence=0.91),
        dict(bill_id="GAS004", company_id="C004", source_file_id="F007", provider="대성에너지",
             customer_number="G998877", site_name="칠곡소재 본공장", usage_month="2025-03",
             gas_usage_amount=None, gas_usage_unit=None, billed_amount_krw=310_000,
             usage_type="일반용", ocr_confidence=0.52),
    ]
    return cols, rows


# ────────────────────────── 8. emission_factors ──────────────────────────
def sheet_emission_factors():
    cols = ["factor_id", "fuel_type", "scope", "activity_unit", "emission_factor",
            "emission_unit", "source_name", "valid_year", "note"]
    rows = [
        dict(factor_id="EF001", fuel_type="전기", scope="Scope 2", activity_unit="kWh",
             emission_factor=0.4541, emission_unit="kgCO2e/kWh", source_name="내부 기준표",
             valid_year=2025, note="전력 배출계수"),
        dict(factor_id="EF002", fuel_type="경유", scope="Scope 1", activity_unit="L",
             emission_factor=2.616, emission_unit="kgCO2/L", source_name="내부 기준표",
             valid_year=2025, note="액체연료"),
        dict(factor_id="EF003", fuel_type="휘발유", scope="Scope 1", activity_unit="L",
             emission_factor=2.221, emission_unit="kgCO2/L", source_name="내부 기준표",
             valid_year=2025, note="액체연료"),
        dict(factor_id="EF004", fuel_type="도시가스", scope="Scope 1", activity_unit="m³",
             emission_factor=2.210, emission_unit="kgCO2/m³", source_name="내부 기준표",
             valid_year=2025, note="LNG 기준"),
        dict(factor_id="EF005", fuel_type="LPG", scope="Scope 1", activity_unit="kg",
             emission_factor=3.000, emission_unit="kgCO2/kg", source_name="내부 기준표",
             valid_year=2025, note="MVP에서는 단위 불명확 시 HITL"),
    ]
    return cols, rows


# ────────────────────────── 9. monthly_fuel_prices ──────────────────────────
def sheet_monthly_fuel_prices():
    cols = ["price_id", "year_month", "fuel_type", "unit_price_krw_per_l", "price_basis", "note"]
    monthly = [
        ("2025-01", 1553.90, 1421.39), ("2025-02", 1571.15, 1449.10),
        ("2025-03", 1535.39, 1413.66), ("2025-04", 1496.99, 1375.65),
        ("2025-05", 1487.68, 1365.59), ("2025-06", 1492.80, 1368.57),
        ("2025-07", 1515.98, 1392.32), ("2025-08", 1514.46, 1396.13),
        ("2025-09", 1508.98, 1391.52), ("2025-10", 1512.02, 1397.11),
        ("2025-11", 1561.95, 1471.91), ("2025-12", 1582.00, 1500.45),
    ]
    rows = []
    n = 1
    for ym, gasoline, diesel in monthly:
        rows.append(dict(price_id=f"FP{n:03d}", year_month=ym, fuel_type="휘발유",
                          unit_price_krw_per_l=gasoline, price_basis="공급가액 기준", note="부가세 제외"))
        n += 1
        rows.append(dict(price_id=f"FP{n:03d}", year_month=ym, fuel_type="경유",
                          unit_price_krw_per_l=diesel, price_basis="공급가액 기준", note="부가세 제외"))
        n += 1
    return cols, rows


# ────────────────────────── 10. classification_rules ──────────────────────────
def sheet_classification_rules():
    cols = ["rule_id", "keyword", "target_field", "carbon_category", "scope",
            "calculation_method", "default_hitl", "reason"]
    rows = [
        dict(rule_id="R001", keyword="경유", target_field="item_name", carbon_category="경유",
             scope="Scope 1", calculation_method="수량기반/금액역산", default_hitl="N",
             reason="액체연료 직접연소"),
        dict(rule_id="R002", keyword="휘발유", target_field="item_name", carbon_category="휘발유",
             scope="Scope 1", calculation_method="수량기반/금액역산", default_hitl="N",
             reason="액체연료 직접연소"),
        dict(rule_id="R003", keyword="전기요금", target_field="item_name", carbon_category="전기",
             scope="Scope 2", calculation_method="kWh 기반", default_hitl="N",
             reason="구매전력 사용"),
        dict(rule_id="R004", keyword="kWh", target_field="item_name", carbon_category="전기",
             scope="Scope 2", calculation_method="kWh 기반", default_hitl="N",
             reason="전력 사용량 단위"),
        dict(rule_id="R005", keyword="도시가스", target_field="item_name", carbon_category="도시가스",
             scope="Scope 1", calculation_method="m³ 기반", default_hitl="N",
             reason="가스 연료 사용"),
        dict(rule_id="R006", keyword="LPG", target_field="item_name", carbon_category="LPG",
             scope="Scope 1 후보", calculation_method="단위 확인 필요", default_hitl="Y",
             reason="단위·성분 불명확 가능성"),
        dict(rule_id="R007", keyword="외 1종", target_field="item_name", carbon_category="검토필요",
             scope="검토필요", calculation_method="계산 보류", default_hitl="Y",
             reason="혼합 품목"),
        dict(rule_id="R008", keyword="절삭유", target_field="item_name", carbon_category="제외/Scope3 후보",
             scope="제외", calculation_method="계산 제외", default_hitl="N",
             reason="MVP Scope 1/2 핵심 아님"),
    ]
    return cols, rows


# ────────────────────────── 11. k_taxonomy_mapping ──────────────────────────
def sheet_k_taxonomy_mapping():
    cols = ["kt_rule_id", "keyword", "candidate_type", "facility_investment_detected",
            "facility_type", "finance_lead_type", "auto_confirm_allowed", "hitl_required",
            "evidence_rule"]
    data = [
        ("KT001", "태양광", "재생에너지 설비", "태양광 설비", "녹색여신 후보"),
        ("KT002", "ESS", "에너지저장장치", "ESS", "녹색여신·설비금융 후보"),
        ("KT003", "전동지게차", "저탄소 장비 전환", "전동지게차", "리스금융 후보"),
        ("KT004", "고효율 압축기", "에너지효율 개선", "압축기", "설비금융 후보"),
        ("KT005", "LED 조명", "에너지효율 개선", "조명", "설비금융 후보"),
        ("KT006", "히트펌프", "에너지효율 개선", "열관리 설비", "설비금융 후보"),
        ("KT007", "집진기", "오염방지 및 관리", "대기방지시설", "환경설비금융 후보"),
        ("KT008", "폐수처리설비", "물 관리/오염방지", "수처리 설비", "환경설비금융 후보"),
        ("KT009", "재활용 설비", "순환경제 전환", "재활용 설비", "녹색여신 후보"),
    ]
    rows = [
        dict(kt_rule_id=rid, keyword=kw, candidate_type=ctype, facility_investment_detected="Y",
             facility_type=ftype, finance_lead_type=lead, auto_confirm_allowed="N",
             hitl_required="Y", evidence_rule=f"품목명에 '{kw}' 포함")
        for rid, kw, ctype, ftype, lead in data
    ]
    return cols, rows


# ────────────────────────── 12. facility_keywords ──────────────────────────
def sheet_facility_keywords():
    cols = ["keyword_id", "category", "keyword", "facility_type", "default_lead_type", "risk_note"]
    rows = [
        dict(keyword_id="FK001", category="재생에너지", keyword="태양광", facility_type="태양광 설비",
             default_lead_type="녹색여신 후보", risk_note="설치 목적 확인 필요"),
        dict(keyword_id="FK002", category="에너지저장", keyword="ESS", facility_type="에너지저장장치",
             default_lead_type="녹색여신 후보", risk_note="재생에너지 연계 여부 확인 필요"),
        dict(keyword_id="FK003", category="전동화", keyword="전동지게차", facility_type="운반장비",
             default_lead_type="리스금융 후보", risk_note="기존 경유 장비 대체 여부 확인 필요"),
        dict(keyword_id="FK004", category="에너지효율", keyword="고효율 압축기", facility_type="압축기",
             default_lead_type="설비금융 후보", risk_note="고효율 인증·교체 여부 확인 필요"),
        dict(keyword_id="FK005", category="에너지효율", keyword="LED", facility_type="조명",
             default_lead_type="설비금융 후보", risk_note="단순 소모품 구매와 구분 필요"),
        dict(keyword_id="FK006", category="열관리", keyword="히트펌프", facility_type="열관리 설비",
             default_lead_type="설비금융 후보", risk_note="사용처 확인 필요"),
        dict(keyword_id="FK007", category="오염방지", keyword="집진기", facility_type="대기방지시설",
             default_lead_type="환경설비금융 후보", risk_note="설비투자 규모 확인 필요"),
        dict(keyword_id="FK008", category="수처리", keyword="폐수처리설비", facility_type="수처리 설비",
             default_lead_type="환경설비금융 후보", risk_note="처리 대상 확인 필요"),
        dict(keyword_id="FK009", category="보류", keyword="유지보수", facility_type="불명확",
             default_lead_type="검토필요", risk_note="신규 설비투자인지 불명확"),
        dict(keyword_id="FK010", category="보류", keyword="수리비", facility_type="불명확",
             default_lead_type="검토필요", risk_note="감축효과 확인 어려움"),
        dict(keyword_id="FK011", category="보류", keyword="공사비", facility_type="불명확",
             default_lead_type="검토필요", risk_note="공사 내용 확인 필요"),
    ]
    return cols, rows


# ────────────────────────── 13. expected_results ──────────────────────────
def sheet_expected_results():
    cols = ["record_id", "expected_document_type", "expected_carbon_category", "expected_scope",
            "expected_activity_amount", "expected_activity_unit", "expected_emission_factor",
            "expected_emissions_kgco2e", "expected_data_quality_score", "expected_hitl_required",
            "expected_k_taxonomy_candidate", "expected_facility_investment",
            "expected_finance_lead_type", "expected_reason"]
    rows = [
        dict(record_id="INV001", expected_document_type="세금계산서", expected_carbon_category="경유",
             expected_scope="Scope 1", expected_activity_amount=120, expected_activity_unit="L",
             expected_emission_factor=2.616, expected_emissions_kgco2e=313.92,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="품목명 경유, 수량 120L 확인"),
        dict(record_id="INV002", expected_document_type="영수증", expected_carbon_category="경유",
             expected_scope="Scope 1", expected_activity_amount=198.07, expected_activity_unit="L",
             expected_emission_factor=2.616, expected_emissions_kgco2e=518.14,
             expected_data_quality_score=3, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="수량 없음, 3월 월별단가(1,413.66원/L)로 금액역산"),
        dict(record_id="INV003", expected_document_type="영수증", expected_carbon_category="휘발유",
             expected_scope="Scope 1", expected_activity_amount=80, expected_activity_unit="L",
             expected_emission_factor=2.221, expected_emissions_kgco2e=177.68,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="품목명 휘발유, 수량 80L 확인"),
        dict(record_id="INV004", expected_document_type="영수증", expected_carbon_category="LPG 후보",
             expected_scope="Scope 1 후보", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="LPG 키워드는 있으나 수량·단위 없음, 사람검토 필요"),
        dict(record_id="INV005", expected_document_type="세금계산서", expected_carbon_category="배출량 계산 제외",
             expected_scope="제외", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="REVIEW", expected_facility_investment="Y",
             expected_finance_lead_type="설비금융 후보",
             expected_reason="품목명에 '고효율 압축기' 포함, 설비투자로 판단해 배출량 계산에서 제외"),
        dict(record_id="INV006", expected_document_type="세금계산서", expected_carbon_category="배출량 계산 제외",
             expected_scope="제외", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="REVIEW", expected_facility_investment="Y",
             expected_finance_lead_type="녹색여신 후보",
             expected_reason="품목명에 '태양광' 포함, 재생에너지 설비투자로 판단"),
        dict(record_id="INV007", expected_document_type="세금계산서", expected_carbon_category="배출량 계산 제외",
             expected_scope="제외", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="REVIEW", expected_facility_investment="Y",
             expected_finance_lead_type="리스금융 후보",
             expected_reason="품목명에 '전동지게차' 포함, 저탄소 장비 전환 리스로 판단"),
        dict(record_id="INV008", expected_document_type="세금계산서", expected_carbon_category="제외/Scope3 후보",
             expected_scope="제외", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="생산 소모품, MVP Scope 1/2 핵심 아님, 계산 제외"),
        dict(record_id="INV009", expected_document_type="영수증", expected_carbon_category="설비투자 불명확",
             expected_scope="검토필요", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="N", expected_facility_investment="UNKNOWN",
             expected_finance_lead_type="",
             expected_reason="품목명이 유지보수비로 신규 설비투자인지 단순 수리인지 불명확, 사람검토 필요"),
        dict(record_id="INV010", expected_document_type="세금계산서", expected_carbon_category="중복 전표",
             expected_scope="제외", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="INV001과 동일 문서(file_hash 중복), 자동 중복 제외"),
        dict(record_id="ELEC001", expected_document_type="전기고지서", expected_carbon_category="전기",
             expected_scope="Scope 2", expected_activity_amount=3000, expected_activity_unit="kWh",
             expected_emission_factor=0.4541, expected_emissions_kgco2e=1362.30,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 3,000kWh 확인"),
        dict(record_id="ELEC002", expected_document_type="전기고지서", expected_carbon_category="전기",
             expected_scope="Scope 2", expected_activity_amount=2800, expected_activity_unit="kWh",
             expected_emission_factor=0.4541, expected_emissions_kgco2e=1271.48,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 2,800kWh 확인"),
        dict(record_id="ELEC003", expected_document_type="전기고지서", expected_carbon_category="전기",
             expected_scope="Scope 2", expected_activity_amount=2100, expected_activity_unit="kWh",
             expected_emission_factor=0.4541, expected_emissions_kgco2e=953.61,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 2,100kWh 확인"),
        dict(record_id="ELEC004", expected_document_type="전기고지서", expected_carbon_category="전기",
             expected_scope="Scope 2", expected_activity_amount=5200, expected_activity_unit="kWh",
             expected_emission_factor=0.4541, expected_emissions_kgco2e=2361.32,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 5,200kWh 확인"),
        dict(record_id="ELEC005", expected_document_type="전기고지서", expected_carbon_category="전기(사용량 미확인)",
             expected_scope="검토필요", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="",
             expected_reason="청구금액만 확인, kWh 미기재 — 전기고지서 재제출 또는 사람검토 필요"),
        dict(record_id="GAS001", expected_document_type="도시가스고지서", expected_carbon_category="도시가스",
             expected_scope="Scope 1", expected_activity_amount=520, expected_activity_unit="m³",
             expected_emission_factor=2.210, expected_emissions_kgco2e=1149.20,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 520m³ 확인"),
        dict(record_id="GAS002", expected_document_type="도시가스고지서", expected_carbon_category="도시가스",
             expected_scope="Scope 1", expected_activity_amount=480, expected_activity_unit="m³",
             expected_emission_factor=2.210, expected_emissions_kgco2e=1060.80,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 480m³ 확인"),
        dict(record_id="GAS003", expected_document_type="도시가스고지서", expected_carbon_category="도시가스",
             expected_scope="Scope 1", expected_activity_amount=950, expected_activity_unit="m³",
             expected_emission_factor=2.210, expected_emissions_kgco2e=2099.50,
             expected_data_quality_score=2, expected_hitl_required="N",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="", expected_reason="고지서 실사용량 950m³ 확인"),
        dict(record_id="GAS004", expected_document_type="도시가스고지서", expected_carbon_category="도시가스(사용량 미확인)",
             expected_scope="검토필요", expected_activity_amount=None, expected_activity_unit=None,
             expected_emission_factor=None, expected_emissions_kgco2e=None,
             expected_data_quality_score=None, expected_hitl_required="Y",
             expected_k_taxonomy_candidate="N", expected_facility_investment="N",
             expected_finance_lead_type="",
             expected_reason="청구금액만 확인, 사용량(m³) 미기재 — 자동계산 제외, 보완요청 또는 사람검토"),
    ]
    return cols, rows


# ────────────────────────── 14. ai_outputs_mock ──────────────────────────
def sheet_ai_outputs_mock():
    cols = ["output_id", "source_record_id", "carbon_category", "scope", "activity_amount",
            "activity_unit", "emission_factor", "emissions_kgco2e", "data_quality_score",
            "k_taxonomy_candidate", "k_taxonomy_candidate_type", "facility_investment_detected",
            "facility_investment_type", "finance_lead_type", "confidence", "evidence",
            "hitl_required", "hitl_reason", "trace_plan", "trace_observation", "trace_action"]
    # (source_record_id, category, scope, amount, unit, factor, kgco2e, dq, kt, kt_type,
    #  facility, facility_type, lead, confidence, evidence, hitl, hitl_reason)
    data = [
        ("INV001", "경유", "Scope 1", 120, "L", 2.616, 313.92, 2, "N", None, "N", None, None,
         0.94, "품목명에 '경유'가 있고 수량 120L가 확인됨", False, None),
        ("INV002", "경유", "Scope 1", 198.07, "L", 2.616, 518.14, 3, "N", None, "N", None, None,
         0.82, "품목명 경유 확인, 수량 미기재로 3월 월별단가 역산 적용", False, None),
        ("INV003", "휘발유", "Scope 1", 80, "L", 2.221, 177.68, 2, "N", None, "N", None, None,
         0.93, "품목명에 '휘발유'가 있고 수량 80L가 확인됨", False, None),
        ("INV004", "LPG 후보", "Scope 1 후보", None, None, None, None, None, "N", None, "N", None, None,
         0.61, "LPG 키워드는 있으나 수량·단위 없음", True, "LPG 단위·성분 불명확, 거래명세서 재확인 필요"),
        ("INV005", "배출량 계산 제외", "제외", None, None, None, None, None, "REVIEW", "에너지효율 개선",
         "Y", "고효율 압축기", "설비금융 후보",
         0.88, "품목명에 '고효율 압축기'가 포함됨", True, "K-택소노미 최종 적합성은 은행 담당자 검토 필요"),
        ("INV006", "배출량 계산 제외", "제외", None, None, None, None, None, "REVIEW", "재생에너지 설비",
         "Y", "태양광 설비", "녹색여신 후보",
         0.92, "품목명에 '태양광 설비 설치'가 포함됨", True, "K-택소노미 최종 적합성은 은행 담당자 검토 필요"),
        ("INV007", "배출량 계산 제외", "제외", None, None, None, None, None, "REVIEW", "저탄소 장비 전환",
         "Y", "전동지게차", "리스금융 후보",
         0.85, "품목명에 '전동지게차 리스료'가 포함됨", True, "설비투자·리스 여부 은행 담당자 확인 필요"),
        ("INV008", "제외/Scope3 후보", "제외", None, None, None, None, None, "N", None, "N", None, None,
         0.90, "품목명 '절삭유', 생산 소모품으로 판단", False, None),
        ("INV009", "설비투자 불명확", "검토필요", None, None, None, None, None, "N", None, "UNKNOWN",
         "유지보수", "",
         0.55, "품목명 '유지보수비', 신규 설비투자·단순 수리 여부 판단 불가", True,
         "신규 설비투자인지 단순 유지보수인지 불명확, 사람검토 필요"),
        ("INV010", "중복 전표", "제외", None, None, None, None, None, "N", None, "N", None, None,
         0.97, "INV001과 품목·금액·거래처·작성일자 동일, file_hash 중복 탐지", False,
         "중복 문서로 자동 제외(감사로그 기록)"),
        ("ELEC001", "전기", "Scope 2", 3000, "kWh", 0.4541, 1362.30, 2, "N", None, "N", None, None,
         0.97, "전기고지서 실사용량 3,000kWh 확인", False, None),
        ("ELEC002", "전기", "Scope 2", 2800, "kWh", 0.4541, 1271.48, 2, "N", None, "N", None, None,
         0.97, "전기고지서 실사용량 2,800kWh 확인", False, None),
        ("ELEC003", "전기", "Scope 2", 2100, "kWh", 0.4541, 953.61, 2, "N", None, "N", None, None,
         0.96, "전기고지서 실사용량 2,100kWh 확인", False, None),
        ("ELEC004", "전기", "Scope 2", 5200, "kWh", 0.4541, 2361.32, 2, "N", None, "N", None, None,
         0.96, "전기고지서 실사용량 5,200kWh 확인", False, None),
        ("ELEC005", "전기(사용량 미확인)", "검토필요", None, None, None, None, None, "N", None, "N", None, None,
         0.40, "전기요금 납부내역만 확인, kWh 필드 없음", True, "전기고지서 재제출 또는 사람검토로 이관"),
        ("GAS001", "도시가스", "Scope 1", 520, "m³", 2.210, 1149.20, 2, "N", None, "N", None, None,
         0.95, "도시가스 고지서 실사용량 520m³ 확인", False, None),
        ("GAS002", "도시가스", "Scope 1", 480, "m³", 2.210, 1060.80, 2, "N", None, "N", None, None,
         0.95, "도시가스 고지서 실사용량 480m³ 확인", False, None),
        ("GAS003", "도시가스", "Scope 1", 950, "m³", 2.210, 2099.50, 2, "N", None, "N", None, None,
         0.94, "도시가스 고지서 실사용량 950m³ 확인", False, None),
        ("GAS004", "도시가스(사용량 미확인)", "검토필요", None, None, None, None, None, "N", None, "N", None, None,
         0.38, "청구금액만 확인, 사용량(m³) 필드 없음", True, "도시가스 고지서 재제출 또는 사람검토로 이관"),
    ]
    rows = []
    for i, d in enumerate(data, start=1):
        (rid, cat, scope, amt, unit, factor, kg, dq, kt, kt_type, fac, fac_type, lead,
         conf, evidence, hitl, hitl_reason) = d
        rows.append(dict(
            output_id=f"OUT{i:03d}", source_record_id=rid, carbon_category=cat, scope=scope,
            activity_amount=amt, activity_unit=unit, emission_factor=factor, emissions_kgco2e=kg,
            data_quality_score=dq, k_taxonomy_candidate=kt, k_taxonomy_candidate_type=kt_type,
            facility_investment_detected=fac, facility_investment_type=fac_type,
            finance_lead_type=lead, confidence=conf, evidence=evidence,
            hitl_required=hitl, hitl_reason=hitl_reason,
            trace_plan="전표 품목과 수량·단위를 확인한다",
            trace_observation=evidence,
            trace_action=(f"{cat}로 계산한다" if not hitl else "사람검토 큐로 이관한다"),
        ))
    return cols, rows


# ────────────────────────── 15. hitl_queue_mock ──────────────────────────
def sheet_hitl_queue_mock():
    cols = ["hitl_id", "company_id", "source_record_id", "issue_type", "original_text",
            "ai_suggestion", "confidence", "evidence", "reviewer_action_needed", "final_status"]
    rows = [
        dict(hitl_id="H001", company_id="C003", source_record_id="INV004", issue_type="단위 불명확",
             original_text="LPG 외 1종", ai_suggestion="LPG 후보", confidence=0.61,
             evidence="LPG 키워드는 있으나 수량·단위 없음", reviewer_action_needed="거래명세서 요청",
             final_status="대기"),
        dict(hitl_id="H002", company_id="C001", source_record_id="INV005", issue_type="K-택소노미 후보",
             original_text="고효율 압축기 구입", ai_suggestion="에너지효율 개선 후보", confidence=0.88,
             evidence="품목명에 '고효율 압축기' 포함", reviewer_action_needed="설비투자 목적 확인",
             final_status="대기"),
        dict(hitl_id="H003", company_id="C002", source_record_id="INV006", issue_type="K-택소노미 후보",
             original_text="태양광 설비 설치", ai_suggestion="재생에너지 설비 후보", confidence=0.92,
             evidence="품목명에 '태양광' 포함", reviewer_action_needed="녹색여신 검토",
             final_status="대기"),
        dict(hitl_id="H004", company_id="C002", source_record_id="F004", issue_type="관계없는 파일",
             original_text="식비영수증", ai_suggestion="탄소계산 무관", confidence=0.97,
             evidence="품목·거래처가 식비로 확인됨", reviewer_action_needed="자동반려 확인",
             final_status="완료"),
        dict(hitl_id="H005", company_id="C003", source_record_id="INV007", issue_type="K-택소노미 후보",
             original_text="전동지게차 리스료", ai_suggestion="저탄소 장비 전환 후보", confidence=0.85,
             evidence="품목명에 '전동지게차' 포함", reviewer_action_needed="리스금융 리드 검토",
             final_status="대기"),
        dict(hitl_id="H006", company_id="C001", source_record_id="INV009", issue_type="설비투자 불명확",
             original_text="유지보수비", ai_suggestion="판단 보류", confidence=0.55,
             evidence="신규 설비투자인지 단순 수리인지 불명확", reviewer_action_needed="세부 내역 확인 요청",
             final_status="대기"),
        dict(hitl_id="H007", company_id="C004", source_record_id="ELEC005", issue_type="사용량 미기재",
             original_text="전기요금 납부내역(kWh 없음)", ai_suggestion="계산 보류", confidence=0.40,
             evidence="청구금액만 확인, kWh 필드 없음", reviewer_action_needed="전기고지서 재제출 요청",
             final_status="대기"),
        dict(hitl_id="H008", company_id="C004", source_record_id="GAS004", issue_type="사용량 미기재",
             original_text="도시가스 고지서(사용량 없음)", ai_suggestion="계산 보류", confidence=0.38,
             evidence="청구금액만 확인, m³ 필드 없음", reviewer_action_needed="도시가스 고지서 재제출 요청",
             final_status="대기"),
        dict(hitl_id="H009", company_id="C001", source_record_id="INV010", issue_type="중복 의심",
             original_text="경유 120L (INV001과 동일)", ai_suggestion="중복 전표, 자동 제외", confidence=0.97,
             evidence="file_hash·품목·금액·작성일자 동일", reviewer_action_needed="확인 후 자동제외 승인",
             final_status="완료"),
    ]
    return cols, rows


# ────────────────────────── 16. bank_loans_mock ──────────────────────────
def sheet_bank_loans_mock():
    cols = ["loan_id", "company_id", "loan_balance_krw", "total_equity_krw",
            "total_liabilities_krw", "company_value_proxy_krw", "attribution_factor",
            "company_emissions_tco2e", "attributed_emissions_tco2e", "note"]
    data = [
        ("L001", "C001", 500_000_000, 2_000_000_000, 4_000_000_000, 128.4),
        ("L002", "C002", 300_000_000, 1_700_000_000, 3_300_000_000, 94.2),
        ("L003", "C003", 800_000_000, 3_200_000_000, 4_800_000_000, 210.8),
        ("L004", "C004", 150_000_000, 500_000_000, 700_000_000, 45.6),
    ]
    rows = []
    for loan_id, cid, balance, equity, liab, emissions in data:
        proxy = equity + liab
        factor = round(balance / proxy, 4)
        attributed = round(emissions * factor, 1)
        rows.append(dict(loan_id=loan_id, company_id=cid, loan_balance_krw=balance,
                          total_equity_krw=equity, total_liabilities_krw=liab,
                          company_value_proxy_krw=proxy, attribution_factor=factor,
                          company_emissions_tco2e=emissions, attributed_emissions_tco2e=attributed,
                          note="mock 데이터 — MVP 시연용, 실제 여신·재무데이터 아님"))
    return cols, rows


# ────────────────────────── 17. portfolio_dashboard_mock ──────────────────────────
def sheet_portfolio_dashboard_mock():
    cols = ["segment_id", "region", "industry", "company_count", "total_loan_balance_krw",
            "avg_wadqs_before", "avg_wadqs_after", "expected_wadqs_improvement",
            "total_emissions_tco2e", "priority_rank", "ai_caption"]
    rows = [
        dict(segment_id="S001", region="경북 구미", industry="금속가공", company_count=23,
             total_loan_balance_krw=12_000_000_000, avg_wadqs_before=5.0, avg_wadqs_after=2.8,
             expected_wadqs_improvement=-2.2, total_emissions_tco2e=8200, priority_rank=1,
             ai_caption="구미 금속가공 기업군은 대출잔액 비중이 높고 데이터 품질 개선 여지가 큽니다."),
        dict(segment_id="S002", region="대구 달서", industry="표면처리", company_count=14,
             total_loan_balance_krw=8_500_000_000, avg_wadqs_before=5.0, avg_wadqs_after=3.1,
             expected_wadqs_improvement=-1.9, total_emissions_tco2e=6100, priority_rank=2,
             ai_caption="표면처리 업종은 탄소집약도가 높아 우선 관리가 필요합니다."),
        dict(segment_id="S003", region="경북 경산", industry="전자부품", company_count=18,
             total_loan_balance_krw=9_500_000_000, avg_wadqs_before=4.5, avg_wadqs_after=2.4,
             expected_wadqs_improvement=-2.1, total_emissions_tco2e=5300, priority_rank=3,
             ai_caption="전자부품 기업군은 전기 사용량 기반 데이터 확보 효과가 큽니다."),
        dict(segment_id="S004", region="경북 칠곡", industry="플라스틱 부품", company_count=9,
             total_loan_balance_krw=3_200_000_000, avg_wadqs_before=5.0, avg_wadqs_after=3.6,
             expected_wadqs_improvement=-1.4, total_emissions_tco2e=1900, priority_rank=4,
             ai_caption="칠곡 플라스틱부품 기업군은 표본 수가 적어 업종 평균 의존도가 높습니다."),
    ]
    return cols, rows


SHEETS = [
    ("README", sheet_readme),
    ("company_master", sheet_company_master),
    ("mydata_documents", sheet_mydata_documents),
    ("uploaded_files", sheet_uploaded_files),
    ("tax_invoices_receipts", sheet_tax_invoices_receipts),
    ("electricity_bills", sheet_electricity_bills),
    ("citygas_bills", sheet_citygas_bills),
    ("emission_factors", sheet_emission_factors),
    ("monthly_fuel_prices", sheet_monthly_fuel_prices),
    ("classification_rules", sheet_classification_rules),
    ("k_taxonomy_mapping", sheet_k_taxonomy_mapping),
    ("facility_keywords", sheet_facility_keywords),
    ("expected_results", sheet_expected_results),
    ("ai_outputs_mock", sheet_ai_outputs_mock),
    ("hitl_queue_mock", sheet_hitl_queue_mock),
    ("bank_loans_mock", sheet_bank_loans_mock),
    ("portfolio_dashboard_mock", sheet_portfolio_dashboard_mock),
]

# 시나리오 ID → 이 데이터셋에서 해당 시나리오를 실증하는 record_id
SCENARIO_COVERAGE = {
    "SCE001": "INV001 (경유 120L, 수량기반 자동계산)",
    "SCE002": "INV002 (경유 금액만 → 월별단가 역산)",
    "SCE003": "INV003 (휘발유 80L)",
    "SCE004": "ELEC001~004 (전기 kWh 자동계산)",
    "SCE005": "ELEC005 (전기 kWh 미기재 → 보완요청)",
    "SCE006": "GAS001~003 (도시가스 m³ 자동계산)",
    "SCE007": "GAS004 (도시가스 금액만 → 자동계산 제외)",
    "SCE008": "INV004 (LPG 외 1종 → HITL)",
    "SCE009": "INV006 (태양광 설비 설치 → K-택소노미 후보)",
    "SCE010": "INV005 (고효율 압축기 → 설비금융 리드)",
    "SCE011": "INV007 (전동지게차 리스료 → 리스금융 리드)",
    "SCE012": "INV008 (절삭유 → 제외/Scope3 후보)",
    "SCE013": "F004 (식비 영수증 → 자동 반려)",
    "SCE014": "INV009 (유지보수비 → 설비투자 불명확 HITL)",
    "SCE015": "INV010 (INV001과 동일 문서 중복 업로드)",
}


def build_workbook():
    wb = Workbook()
    wb.remove(wb.active)
    for name, builder in SHEETS:
        cols, rows = builder()
        ws = wb.create_sheet(title=name)
        ws.append(cols)
        for row in rows:
            ws.append([row.get(c) for c in cols])
    return wb


def main():
    p = argparse.ArgumentParser(description="감탄 합성데이터셋 생성기 (17개 시트)")
    p.add_argument("--out", default=DEFAULT_OUT, help="저장 경로 (.xlsx)")
    a = p.parse_args()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    wb = build_workbook()
    wb.save(a.out)

    print(f"[OK] {len(SHEETS)}개 시트 → {a.out}")
    for name, builder in SHEETS:
        _, rows = builder()
        print(f"     - {name}: {len(rows)}행")
    print(f"[OK] 시나리오 커버리지 {len(SCENARIO_COVERAGE)}/15")
    for sce, desc in SCENARIO_COVERAGE.items():
        print(f"     - {sce}: {desc}")


if __name__ == "__main__":
    main()
