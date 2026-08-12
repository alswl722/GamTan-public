# 감탄(鑑炭) 합성데이터 제작 가이드

> 목적: 공모전 MVP에서 실제 영세 소부장 기업 전표를 확보하기 어려운 상황을 보완하기 위해, 실제 서비스 입력 구조와 유사한 합성데이터를 제작한다.  
> 합성데이터는 “그럴듯한 더미 데이터”가 아니라, 감탄 AI의 분류·계산·HITL·은행 대시보드 흐름을 검증하기 위한 테스트 데이터셋으로 설계한다.

---

## 0. 합성데이터 제작의 기본 방향

감탄의 핵심은 전표와 고지서를 읽어 기업의 탄소 데이터를 만들고, 이를 은행의 ESG 금융 판단에 활용 가능한 형태로 정리하는 것이다. 따라서 합성데이터도 단순히 숫자를 채우는 것이 아니라 아래 흐름을 검증할 수 있어야 한다.

```text
기업 기본정보
→ 마이데이터 확인 자료
→ 전기·연료·가스 관련 업로드 자료
→ AI 품목 분류
→ Scope 1/2 배출량 계산
→ PCAF 데이터 품질 평가
→ HITL 큐 분기
→ K-택소노미 후보 및 설비투자 리드 탐지
→ 은행 담당자 대시보드
→ 포트폴리오/금융배출량 시뮬레이션
```

합성데이터는 다음 세 가지 목적을 동시에 가져야 한다.

| 목적 | 설명 |
|---|---|
| 서비스 흐름 검증 | 기업이 어떤 데이터를 넣고, 감탄이 어떤 결과를 내는지 보여줌 |
| AI 파이프라인 검증 | 분류, 계산, 신뢰도, HITL 분기가 제대로 작동하는지 확인 |
| 발표 설득력 확보 | 영세 소부장 기업의 실제 업무 자료와 유사한 입력값을 기반으로 MVP가 작동함을 보여줌 |

---

## 1. 합성데이터 제작 원칙

### 1-1. 실제 증빙자료 구조를 닮게 만든다

합성데이터는 실제 세금계산서, 영수증, 전기요금 고지서, 도시가스 고지서에서 볼 수 있는 항목을 기준으로 만든다.

예를 들어 세금계산서라면 아래 항목이 들어가야 한다.

| 항목 | 필요성 |
|---|---|
| 작성일자 | 월별 집계 및 월별단가 적용 기준 |
| 거래처명 | 주유소, 가스사, 설비업체 등 거래 유형 판단 |
| 품목명 | 경유, 휘발유, LPG, 고효율 압축기 등 AI 분류 핵심 |
| 수량 | 활동량 계산 기준 |
| 단위 | L, kg, m³, kWh 등 배출계수 적용 기준 |
| 공급가액 | 금액 역산 및 증빙 금액 확인 기준 |
| 세액 | 세금계산서 구조 현실성 부여 |
| 합계금액 | 공급가액 + 세액 검증 |
| 비고 | 지게차용, 차량용, 설비 교체 등 맥락 제공 |

### 1-2. 자동계산 가능 데이터와 불확실 데이터를 섞는다

모든 데이터가 깔끔하면 AI Agent와 HITL 구조를 보여주기 어렵다. 합성데이터에는 아래 유형이 모두 포함되어야 한다.

| 유형 | 예시 | 기대 처리 |
|---|---|---|
| 명확한 자동계산 | 경유 120L | Scope 1 자동계산 |
| 금액역산 | 경유 수량 없음, 공급가액만 있음 | 월별단가로 L 추정 |
| 고지서 사용량 | 전기 3,000kWh | Scope 2 자동계산 |
| 단위 불명확 | LPG 외 1종 | HITL |
| 관계없는 자료 | 식비 영수증 | 자동 반려 |
| 설비투자 | 고효율 압축기 구입 | 배출량 제외, 설비금융 리드 |
| K-택소노미 후보 | 태양광 설비 설치 | K-택소노미 후보, 담당자 검토 |

### 1-3. 계산값을 미리 정답지로 만든다

AI가 낸 결과가 맞는지 확인하려면 `expected_results` 시트가 필요하다. 이 시트는 감탄 AI가 맞춰야 할 정답지 역할을 한다.

정답지에는 아래가 들어가야 한다.

| 항목 | 설명 |
|---|---|
| expected_scope | Scope 1, Scope 2, 제외, 검토필요 |
| expected_fuel_type | 경유, 휘발유, 전기, 도시가스, LPG 등 |
| expected_activity_amount | 예상 활동량 |
| expected_activity_unit | L, kWh, m³ 등 |
| expected_emissions | 예상 배출량 |
| expected_hitl | 사람검토 필요 여부 |
| expected_reason | 왜 그렇게 판단해야 하는지 |

---

## 2. 엑셀 파일 전체 시트 구성

합성데이터 엑셀은 아래 시트로 구성하는 것을 추천한다.

| 시트명 | 목적 | 중요도 |
|---|---|---|
| `README` | 데이터셋 설명, 제작 기준, 주의사항 | 필수 |
| `company_master` | 기업 기본정보 | 필수 |
| `mydata_documents` | 마이데이터로 확보되는 자료 목록 | 필수 |
| `uploaded_files` | 기업이 업로드한 파일 목록 | 필수 |
| `tax_invoices_receipts` | 세금계산서·영수증·거래명세서 데이터 | 필수 |
| `electricity_bills` | 전기요금 고지서 데이터 | 필수 |
| `citygas_bills` | 도시가스 고지서 데이터 | 권장 |
| `emission_factors` | 배출계수 기준표 | 필수 |
| `monthly_fuel_prices` | 월별 경유·휘발유 평균단가 | 필수 |
| `classification_rules` | Scope/연료 분류 기준표 | 필수 |
| `k_taxonomy_mapping` | K-택소노미 후보 매핑표 | 필수 |
| `facility_keywords` | 설비투자 키워드 사전 | 필수 |
| `expected_results` | 정답지 | 필수 |
| `ai_outputs_mock` | 감탄 AI 출력 예시 | 필수 |
| `hitl_queue_mock` | 사람검토 큐 예시 | 필수 |
| `bank_loans_mock` | 은행 여신 mock 데이터 | 선택/발표용 |
| `portfolio_dashboard_mock` | 은행 대시보드 mock 데이터 | 선택/발표용 |

---

## 3. 시트별 상세 설계

---

# 3-1. `README` 시트

## 목적

합성데이터가 어떤 기준으로 만들어졌는지 설명하는 시트다. 발표자료나 멘토 검토 시 데이터 신뢰성을 설명하는 근거로 사용한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| 항목 | 설명 항목명 | 데이터셋 목적 |
| 내용 | 상세 설명 | 전표·고지서 기반 탄소 산정 MVP 검증용 합성데이터 |

## 들어갈 내용 예시

| 항목 | 내용 |
|---|---|
| 데이터셋 목적 | 영세 소부장 기업의 실제 전표·고지서 구조를 반영한 감탄 MVP 검증용 합성데이터 |
| 기준기간 | 2025년 1월~12월 중 일부 월 |
| 대상기업 | 대구·경북 지역 제조업, 금속가공, 전자부품, 표면처리 등 가상 기업 |
| 주요 입력자료 | 세금계산서, 영수증, 전기요금 고지서, 도시가스 고지서, 마이데이터 확인자료 |
| 주요 검증항목 | Scope 1/2 분류, 배출량 계산, 데이터 품질 평가, HITL 분기, K-택소노미 후보 탐지 |
| 주의사항 | 본 데이터는 실제 기업 자료가 아닌 공모전 MVP 검증용 합성데이터임 |

---

# 3-2. `company_master` 시트

## 목적

기업별 기본정보를 저장한다. 감탄 리포트, 업종 비교, 지역 비교, 은행 대시보드의 기준 데이터가 된다.

## 권장 컬럼

| 컬럼명 | 데이터 형식 | 설명 | 예시 |
|---|---|---|---|
| company_id | 문자열 | 기업 고유 ID | C001 |
| company_name | 문자열 | 기업명 | 구미정밀 |
| business_number | 문자열 | 사업자등록번호 | 123-45-67890 |
| region | 문자열 | 지역 | 경북 구미 |
| industry | 문자열 | 업종명 | 금속가공 |
| ksic_code | 문자열 | 표준산업분류 코드 | C259 |
| employee_count | 숫자 | 종업원 수 | 18 |
| annual_revenue_krw | 숫자 | 연매출 | 2500000000 |
| is_sme | Y/N | 중소기업 여부 | Y |
| main_energy_type | 문자열 | 주 사용 에너지 | 전기, 경유 |
| has_electricity | Y/N | 전기 사용 여부 | Y |
| has_diesel | Y/N | 경유 사용 여부 | Y |
| has_gasoline | Y/N | 휘발유 사용 여부 | N |
| has_citygas | Y/N | 도시가스 사용 여부 | N |
| has_lpg | Y/N/UNKNOWN | LPG 사용 여부 | N |
| created_at | 날짜 | 데이터 생성일 | 2026-08-12 |

## 예시

| company_id | company_name | region | industry | employee_count | annual_revenue_krw | has_electricity | has_diesel | has_citygas | has_lpg |
|---|---|---|---|---:|---:|---|---|---|---|
| C001 | 구미정밀 | 경북 구미 | 금속가공 | 18 | 2500000000 | Y | Y | N | N |
| C002 | 대경부품 | 경북 경산 | 전자부품 | 12 | 1800000000 | Y | N | Y | N |
| C003 | 성서테크 | 대구 달서 | 표면처리 | 25 | 3200000000 | Y | Y | Y | UNKNOWN |
| C004 | 칠곡소재 | 경북 칠곡 | 플라스틱 부품 | 9 | 950000000 | Y | N | N | Y |

---

# 3-3. `mydata_documents` 시트

## 목적

기업이 마이데이터 동의로 자동 확인한 자료를 저장한다. 마이데이터는 기업 확인과 규모 파악에는 유용하지만, 탄소 계산 핵심값인 전기 kWh, 도시가스 m³, 세금계산서 상세 품목을 모두 대체하지 못한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| doc_id | 문서 ID | MD001 |
| company_id | 기업 ID | C001 |
| provider | 제공기관 | 국세청 |
| document_name | 문서명 | 사업자등록증명 |
| collected_by | 수집 방식 | 마이데이터 |
| collected_status | 수집 상태 | 확인완료 |
| key_fields | 주요 확인값 | 사업자번호, 기업명 |
| used_for | 활용 목적 | 기업 식별 |
| limitation | 한계 | 탄소 사용량 정보 없음 |

## 예시

| doc_id | company_id | provider | document_name | collected_status | used_for | limitation |
|---|---|---|---|---|---|---|
| MD001 | C001 | 국세청 | 사업자등록증명 | 확인완료 | 기업 식별 | 탄소 사용량 정보 없음 |
| MD002 | C001 | 국세청 | 부가가치세과세표준증명 | 확인완료 | 매출 규모 확인 | 품목별 에너지 사용량 없음 |
| MD003 | C001 | 국세청 | 표준재무제표증명 | 확인완료 | 재무정보 확인 | 은행 내부 여신 데이터와 별도 연동 필요 |
| MD004 | C001 | 중소벤처기업부 | 중소기업확인서 | 확인완료 | 중소기업 여부 확인 | 배출량 정보 없음 |
| MD005 | C001 | 한국전력공사 | 전기요금 납부내역 | 확인완료 | 전기 자료 보조 | kWh 포함 여부 확인 필요 |

---

# 3-4. `uploaded_files` 시트

## 목적

기업이 업로드한 파일 목록과 처리 상태를 저장한다. AI 자동 반려, 보완 요청, HITL 분기의 근거가 된다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| file_id | 파일 ID | F001 |
| company_id | 기업 ID | C001 |
| file_name | 파일명 | 2025_03_경유_세금계산서.pdf |
| file_type | 파일 형식 | PDF |
| document_type | 문서 유형 | 세금계산서 |
| period_month | 기준월 | 2025-03 |
| upload_source | 업로드 방식 | 기업 업로드 |
| parse_status | 파싱 상태 | 성공 |
| reject_status | 반려 여부 | N |
| reject_reason | 반려 사유 |  |
| linked_record_id | 연결된 전표/고지서 ID | INV001 |

## 예시

| file_id | company_id | file_name | document_type | period_month | parse_status | reject_status | reject_reason |
|---|---|---|---|---|---|---|---|
| F001 | C001 | 2025_03_경유_세금계산서.pdf | 세금계산서 | 2025-03 | 성공 | N |  |
| F002 | C001 | 2025_03_전기고지서.pdf | 전기고지서 | 2025-03 | 성공 | N |  |
| F003 | C003 | 2025_04_LPG_영수증.jpg | 영수증 | 2025-04 | 부분성공 | N | 품목·단위 불명확 |
| F004 | C002 | 식비영수증.jpg | 기타 | 2025-04 | 실패 | Y | 탄소계산과 무관한 파일 |

---

# 3-5. `tax_invoices_receipts` 시트

## 목적

연료 구매, 설비투자, 일반 소모품 구매 등 세금계산서·영수증·거래명세서 데이터를 저장한다. 감탄 AI의 품목 분류와 K-택소노미 후보 탐지의 핵심 입력값이다.

## 권장 컬럼

| 컬럼명 | 데이터 형식 | 설명 | 예시 |
|---|---|---|---|
| record_id | 문자열 | 전표 ID | INV001 |
| company_id | 문자열 | 기업 ID | C001 |
| source_file_id | 문자열 | 업로드 파일 ID | F001 |
| document_type | 문자열 | 세금계산서/영수증/거래명세서 | 세금계산서 |
| issue_date | 날짜 | 작성일자 | 2025-03-15 |
| supplier_name | 문자열 | 거래처명 | 구미에너지주유소 |
| supplier_business_number | 문자열 | 공급자 사업자번호 | 111-22-33333 |
| buyer_name | 문자열 | 공급받는자 | 구미정밀 |
| item_name | 문자열 | 품목명 | 경유 |
| specification | 문자열 | 규격 | 지게차용 |
| quantity | 숫자/null | 수량 | 120 |
| unit | 문자열/null | 단위 | L |
| unit_price_krw | 숫자/null | 단가 | 1413.66 |
| supply_amount_krw | 숫자 | 공급가액 | 169639 |
| vat_krw | 숫자 | 부가세 | 16964 |
| total_amount_krw | 숫자 | 합계금액 | 186603 |
| memo | 문자열 | 비고 | 3월 지게차 연료 |
| ocr_text | 문자열 | OCR 원문 일부 | 경유 120L 공급가액 169,639원 |

## 예시 데이터

| record_id | company_id | document_type | issue_date | supplier_name | item_name | specification | quantity | unit | supply_amount_krw | memo |
|---|---|---|---|---|---|---|---:|---|---:|---|
| INV001 | C001 | 세금계산서 | 2025-03-15 | 구미에너지주유소 | 경유 | 지게차용 | 120 | L | 169639 | 3월 지게차 연료 |
| INV002 | C001 | 영수증 | 2025-04-08 | 대구주유소 | 경유 |  |  |  | 280000 | 수량 없음, 금액만 있음 |
| INV003 | C002 | 세금계산서 | 2025-03-20 | 경산에너지 | 휘발유 | 업무차량 | 80 | L | 122831 | 업무차량 주유 |
| INV004 | C003 | 영수증 | 2025-04-05 | OO충전소 | LPG 외 1종 |  |  |  | 280000 | 품목·단위 불명확 |
| INV005 | C001 | 세금계산서 | 2025-05-02 | 대한기계 | 고효율 압축기 | 15kW | 1 | 대 | 5000000 | 노후 압축기 교체 |
| INV006 | C002 | 세금계산서 | 2025-05-10 | 솔라테크 | 태양광 설비 설치 | 20kW | 1 | 식 | 30000000 | 공장 지붕 태양광 |
| INV007 | C003 | 세금계산서 | 2025-05-15 | 전동물류 | 전동지게차 리스료 |  | 1 | 대 | 1200000 | 월 리스료 |
| INV008 | C004 | 세금계산서 | 2025-06-01 | 부품상사 | 절삭유 |  | 20 | L | 100000 | 생산 소모품 |

---

# 3-6. `electricity_bills` 시트

## 목적

전기 사용량 데이터를 저장한다. 전기 배출량은 금액이 아니라 실제 사용량 kWh 기준으로 산정한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| bill_id | 고지서 ID | ELEC001 |
| company_id | 기업 ID | C001 |
| source_file_id | 업로드 파일 ID | F002 |
| provider | 전력 공급기관 | 한국전력공사 |
| customer_number | 고객번호 | 1234567890 |
| site_name | 사업장명 | 구미정밀 본공장 |
| usage_month | 사용월 | 2025-03 |
| period_start | 사용기간 시작 | 2025-03-01 |
| period_end | 사용기간 종료 | 2025-03-31 |
| electricity_kwh | 전기사용량 | 3000 |
| billed_amount_krw | 청구금액 | 450000 |
| contract_type | 계약종별 | 산업용 |
| ocr_confidence | OCR 신뢰도 | 0.96 |

## 예시

| bill_id | company_id | usage_month | electricity_kwh | billed_amount_krw | contract_type |
|---|---|---|---:|---:|---|
| ELEC001 | C001 | 2025-03 | 3000 | 450000 | 산업용 |
| ELEC002 | C001 | 2025-04 | 2800 | 420000 | 산업용 |
| ELEC003 | C002 | 2025-03 | 2100 | 315000 | 일반용 |
| ELEC004 | C003 | 2025-04 | 5200 | 780000 | 산업용 |

## 처리 원칙

```text
전기 배출량은 전기요금 금액이 아니라 kWh 사용량을 기준으로 계산한다.
전기요금에는 기본요금, 계약조건, 계절·시간대 요금, 세금 등이 포함될 수 있어 금액 역산은 기본 계산에 사용하지 않는다.
전기요금 납부내역만 있고 kWh가 없는 경우에는 전기고지서 추가 제출 또는 사람검토로 이관한다.
```

---

# 3-7. `citygas_bills` 시트

## 목적

도시가스 사용량 데이터를 저장한다. 도시가스는 고지서의 실제 사용량 m³ 또는 Nm³를 우선 사용한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| bill_id | 고지서 ID | GAS001 |
| company_id | 기업 ID | C002 |
| source_file_id | 파일 ID | F010 |
| provider | 도시가스사 | 영남에너지서비스 |
| customer_number | 고객번호 | G123456 |
| site_name | 사업장명 | 대경부품 본사 |
| usage_month | 사용월 | 2025-03 |
| gas_usage_amount | 사용량 | 520 |
| gas_usage_unit | 단위 | m³ |
| billed_amount_krw | 청구금액 | 390000 |
| usage_type | 용도 | 산업용 |
| ocr_confidence | OCR 신뢰도 | 0.93 |

## 예시

| bill_id | company_id | usage_month | gas_usage_amount | gas_usage_unit | billed_amount_krw | provider |
|---|---|---|---:|---|---:|---|
| GAS001 | C002 | 2025-03 | 520 | m³ | 390000 | 영남에너지서비스 |
| GAS002 | C002 | 2025-04 | 480 | m³ | 360000 | 영남에너지서비스 |
| GAS003 | C003 | 2025-04 | 950 | m³ | 720000 | 대성에너지 |

## 처리 원칙

```text
도시가스는 고지서 사용량 m³ 또는 Nm³가 확인되는 경우에만 자동 계산한다.
청구금액만 있는 경우에는 요금 구조와 용도별 단가 차이로 인해 자동 역산하지 않고 보완 요청 또는 사람검토로 이관한다.
```

---

# 3-8. `emission_factors` 시트

## 목적

활동량을 배출량으로 변환하기 위한 배출계수 기준표다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| factor_id | 배출계수 ID | EF001 |
| fuel_type | 연료/에너지 유형 | 경유 |
| scope | Scope | Scope 1 |
| activity_unit | 활동량 단위 | L |
| emission_factor | 배출계수 | 2.616 |
| emission_unit | 배출계수 단위 | kgCO2/L |
| source_name | 출처명 | 내부 기준표 |
| valid_year | 적용연도 | 2025 |
| note | 비고 | MVP 기준 |

## 예시

| factor_id | fuel_type | scope | activity_unit | emission_factor | emission_unit | note |
|---|---|---|---|---:|---|---|
| EF001 | 전기 | Scope 2 | kWh | 0.4541 | kgCO2e/kWh | 전력 배출계수 |
| EF002 | 경유 | Scope 1 | L | 2.616 | kgCO2/L | 액체연료 |
| EF003 | 휘발유 | Scope 1 | L | 2.221 | kgCO2/L | 액체연료 |
| EF004 | 도시가스 | Scope 1 | m³ | 2.210 | kgCO2/m³ | LNG 기준 |
| EF005 | LPG | Scope 1 | kg | 3.000 | kgCO2/kg | MVP에서는 단위 불명확 시 HITL |

## 주의사항

```text
전력은 kgCO2e/kWh 기준으로 계산하고,
액체·가스 연료는 MVP에서는 주요 Scope 1/2 자동 분류와 계산 구조 검증에 초점을 둔다.
LPG는 프로판/부탄, kg/L/Nm³ 구분이 필요하므로 단위가 불명확한 경우 자동계산하지 않는다.
```

---

# 3-9. `monthly_fuel_prices` 시트

## 목적

경유·휘발유 전표에 수량이 없고 공급가액만 있는 경우 사용량을 추정하기 위한 월별 평균단가표다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| price_id | 단가 ID | FP001 |
| year_month | 기준월 | 2025-03 |
| fuel_type | 연료유형 | 경유 |
| unit_price_krw_per_l | L당 평균단가 | 1413.66 |
| price_basis | 금액 기준 | 공급가액 기준 |
| note | 비고 | 부가세 제외 |

## 2025년 월별 공급가액 기준 단가 예시

| year_month | gasoline_krw_per_l | diesel_krw_per_l |
|---|---:|---:|
| 2025-01 | 1553.90 | 1421.39 |
| 2025-02 | 1571.15 | 1449.10 |
| 2025-03 | 1535.39 | 1413.66 |
| 2025-04 | 1496.99 | 1375.65 |
| 2025-05 | 1487.68 | 1365.59 |
| 2025-06 | 1492.80 | 1368.57 |
| 2025-07 | 1515.98 | 1392.32 |
| 2025-08 | 1514.46 | 1396.13 |
| 2025-09 | 1508.98 | 1391.52 |
| 2025-10 | 1512.02 | 1397.11 |
| 2025-11 | 1561.95 | 1471.91 |
| 2025-12 | 1582.00 | 1500.45 |

## 금액역산 공식

```text
추정 사용량(L) = 공급가액 ÷ 해당 월 평균단가
추정 배출량(kgCO2e) = 추정 사용량 × 배출계수
```

## 예시

```text
2025년 3월 경유 공급가액 280,000원
월별 경유 평균단가 1,413.66원/L

추정 사용량 = 280,000 ÷ 1,413.66 = 198.07L
추정 배출량 = 198.07 × 2.616 = 518.14kgCO2
```

## 처리 원칙

```text
경유와 휘발유는 수량이 있으면 실제 구매수량을 우선 사용한다.
수량이 없고 공급가액만 있는 경우 월별 평균단가로 사용량을 추정한다.
다만 금액역산 데이터는 실제 활동자료보다 신뢰도가 낮으므로 데이터 품질점수를 낮게 부여한다.
전기와 도시가스는 금액역산을 기본 적용하지 않는다.
```

---

# 3-10. `classification_rules` 시트

## 목적

품목명과 거래처명을 기준으로 Scope 1/2, 연료유형, 자동계산 여부를 판단하는 기준표다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| rule_id | 규칙 ID | R001 |
| keyword | 탐지 키워드 | 경유 |
| target_field | 탐지 대상 필드 | item_name |
| carbon_category | 탄소 분류 | 경유 |
| scope | Scope | Scope 1 |
| calculation_method | 계산 방식 | 수량기반 |
| default_hitl | 기본 HITL 여부 | N |
| reason | 판단 근거 | 품목명이 경유이면 Scope 1 연료로 분류 |

## 예시

| rule_id | keyword | carbon_category | scope | calculation_method | default_hitl | reason |
|---|---|---|---|---|---|---|
| R001 | 경유 | 경유 | Scope 1 | 수량기반/금액역산 | N | 액체연료 직접연소 |
| R002 | 휘발유 | 휘발유 | Scope 1 | 수량기반/금액역산 | N | 액체연료 직접연소 |
| R003 | 전기요금 | 전기 | Scope 2 | kWh 기반 | N | 구매전력 사용 |
| R004 | kWh | 전기 | Scope 2 | kWh 기반 | N | 전력 사용량 단위 |
| R005 | 도시가스 | 도시가스 | Scope 1 | m³ 기반 | N | 가스 연료 사용 |
| R006 | LPG | LPG | Scope 1 후보 | 단위 확인 필요 | Y | 단위·성분 불명확 가능성 |
| R007 | 외 1종 | 검토필요 | 검토필요 | 계산 보류 | Y | 혼합 품목 |
| R008 | 절삭유 | 제외/Scope3 후보 | 제외 | 계산 제외 | N | MVP Scope 1/2 핵심 아님 |

---

# 3-11. `k_taxonomy_mapping` 시트

## 목적

전표 품목명에서 K-택소노미 후보 가능성이 있는 항목을 탐지하는 기준표다. 이 시트는 최종 적합성 판정표가 아니라, 은행 담당자 검토 대상으로 넘기기 위한 1차 스크리닝 표다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| kt_rule_id | 규칙 ID | KT001 |
| keyword | 키워드 | 태양광 |
| candidate_type | K-택소노미 후보유형 | 재생에너지 설비 |
| facility_investment_detected | 설비투자 여부 | Y |
| facility_type | 설비유형 | 태양광 설비 |
| finance_lead_type | 금융리드 유형 | 녹색여신 후보 |
| auto_confirm_allowed | 자동확정 가능 여부 | N |
| hitl_required | 담당자 검토 필요 | Y |
| evidence_rule | 판단근거 | 품목명에 태양광 포함 |

## 예시

| kt_rule_id | keyword | candidate_type | facility_investment_detected | facility_type | finance_lead_type | hitl_required |
|---|---|---|---|---|---|---|
| KT001 | 태양광 | 재생에너지 설비 | Y | 태양광 설비 | 녹색여신 후보 | Y |
| KT002 | ESS | 에너지저장장치 | Y | ESS | 녹색여신·설비금융 후보 | Y |
| KT003 | 전동지게차 | 저탄소 장비 전환 | Y | 전동지게차 | 리스금융 후보 | Y |
| KT004 | 고효율 압축기 | 에너지효율 개선 | Y | 압축기 | 설비금융 후보 | Y |
| KT005 | LED 조명 | 에너지효율 개선 | Y | 조명 | 설비금융 후보 | Y |
| KT006 | 히트펌프 | 에너지효율 개선 | Y | 열관리 설비 | 설비금융 후보 | Y |
| KT007 | 집진기 | 오염방지 및 관리 | Y | 대기방지시설 | 환경설비금융 후보 | Y |
| KT008 | 폐수처리설비 | 물 관리/오염방지 | Y | 수처리 설비 | 환경설비금융 후보 | Y |
| KT009 | 재활용 설비 | 순환경제 전환 | Y | 재활용 설비 | 녹색여신 후보 | Y |

## 주의사항

```text
K-택소노미 후보여부는 AI가 최종 적합성을 판정하는 값이 아니다.
감탄 AI는 품목명과 거래처명을 바탕으로 녹색경제활동 가능성이 있는 전표를 후보로 표시한다.
최종 K-택소노미 적합성 및 금융상품 승인 여부는 은행 담당자가 검토한다.
```

---

# 3-12. `facility_keywords` 시트

## 목적

설비투자 탐지를 위한 키워드 사전이다. K-택소노미 후보와 설비금융 리드 탐지에 활용한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| keyword_id | 키워드 ID | FK001 |
| category | 카테고리 | 에너지효율 |
| keyword | 키워드 | 고효율 압축기 |
| facility_type | 설비유형 | 압축기 |
| default_lead_type | 기본 금융리드 | 설비금융 후보 |
| risk_note | 주의사항 | 단순 수리인지 교체인지 확인 필요 |

## 예시

| keyword_id | category | keyword | facility_type | default_lead_type | risk_note |
|---|---|---|---|---|---|
| FK001 | 재생에너지 | 태양광 | 태양광 설비 | 녹색여신 후보 | 설치 목적 확인 필요 |
| FK002 | 에너지저장 | ESS | 에너지저장장치 | 녹색여신 후보 | 재생에너지 연계 여부 확인 필요 |
| FK003 | 전동화 | 전동지게차 | 운반장비 | 리스금융 후보 | 기존 경유 장비 대체 여부 확인 필요 |
| FK004 | 에너지효율 | 고효율 압축기 | 압축기 | 설비금융 후보 | 고효율 인증·교체 여부 확인 필요 |
| FK005 | 에너지효율 | LED | 조명 | 설비금융 후보 | 단순 소모품 구매와 구분 필요 |
| FK006 | 열관리 | 히트펌프 | 열관리 설비 | 설비금융 후보 | 사용처 확인 필요 |
| FK007 | 오염방지 | 집진기 | 대기방지시설 | 환경설비금융 후보 | 설비투자 규모 확인 필요 |
| FK008 | 수처리 | 폐수처리설비 | 수처리 설비 | 환경설비금융 후보 | 처리 대상 확인 필요 |
| FK009 | 보류 | 유지보수 | 불명확 | 검토필요 | 신규 설비투자인지 불명확 |
| FK010 | 보류 | 수리비 | 불명확 | 검토필요 | 감축효과 확인 어려움 |
| FK011 | 보류 | 공사비 | 불명확 | 검토필요 | 공사 내용 확인 필요 |

---

# 3-13. `expected_results` 시트

## 목적

AI가 생성해야 하는 정답값을 저장한다. 분류 정확도, 계산 정확도, HITL 분기 정확도를 평가하는 기준이다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| record_id | 원천 데이터 ID | INV001 |
| expected_document_type | 기대 문서유형 | 세금계산서 |
| expected_carbon_category | 기대 탄소분류 | 경유 |
| expected_scope | 기대 Scope | Scope 1 |
| expected_activity_amount | 기대 활동량 | 120 |
| expected_activity_unit | 기대 단위 | L |
| expected_emission_factor | 기대 배출계수 | 2.616 |
| expected_emissions_kgco2e | 기대 배출량 | 313.92 |
| expected_data_quality_score | 기대 데이터품질점수 | 2 |
| expected_hitl_required | 기대 HITL | N |
| expected_k_taxonomy_candidate | K-택소노미 후보 여부 | N |
| expected_facility_investment | 설비투자 여부 | N |
| expected_finance_lead_type | 금융리드 유형 |  |
| expected_reason | 판단 근거 | 품목명 경유, 수량 L 확인 |

## 예시

| record_id | expected_carbon_category | expected_scope | expected_activity_amount | expected_activity_unit | expected_emissions_kgco2e | expected_hitl_required | expected_k_taxonomy_candidate | expected_facility_investment | expected_finance_lead_type |
|---|---|---|---:|---|---:|---|---|---|---|
| INV001 | 경유 | Scope 1 | 120 | L | 313.92 | N | N | N |  |
| INV002 | 경유 | Scope 1 | 198.07 | L | 518.14 | N | N | N |  |
| INV004 | LPG 후보 | Scope 1 후보 |  |  |  | Y | N | N |  |
| INV005 | 배출량 계산 제외 | 제외 |  |  |  | Y | REVIEW | Y | 설비금융 후보 |
| INV006 | 배출량 계산 제외 | 제외 |  |  |  | Y | REVIEW | Y | 녹색여신 후보 |
| INV007 | 배출량 계산 제외 | 제외 |  |  |  | Y | REVIEW | Y | 리스금융 후보 |
| INV008 | 제외/Scope3 후보 | 제외 |  |  |  | N | N | N |  |
| ELEC001 | 전기 | Scope 2 | 3000 | kWh | 1362.30 | N | N | N |  |
| GAS001 | 도시가스 | Scope 1 | 520 | m³ | 1149.20 | N | N | N |  |

---

# 3-14. `ai_outputs_mock` 시트

## 목적

감탄 AI가 실제로 출력할 JSON/DB 결과를 mock 형태로 저장한다. 개발팀이 API 출력 구조를 맞추는 데 사용한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| output_id | 출력 ID | OUT001 |
| source_record_id | 원천 데이터 ID | INV001 |
| carbon_category | 탄소 분류 | 경유 |
| scope | Scope | Scope 1 |
| activity_amount | 활동량 | 120 |
| activity_unit | 단위 | L |
| emission_factor | 배출계수 | 2.616 |
| emissions_kgco2e | 배출량 | 313.92 |
| data_quality_score | 데이터 품질점수 | 2 |
| k_taxonomy_candidate | K-택소노미 후보 | N |
| k_taxonomy_candidate_type | 후보유형 |  |
| facility_investment_detected | 설비투자 탐지 | N |
| facility_investment_type | 설비유형 |  |
| finance_lead_type | 금융리드 유형 |  |
| confidence | AI 신뢰도 | 0.94 |
| evidence | 판단근거 | 품목명에 경유, 단위 L 확인 |
| hitl_required | HITL 여부 | false |
| hitl_reason | HITL 사유 |  |
| trace_plan | 계획 로그 | 전표 품목과 수량 확인 |
| trace_observation | 관찰 로그 | 경유 120L 확인 |
| trace_action | 행동 로그 | Scope 1 경유로 계산 |

## JSON 출력 예시

```json
{
  "source_record_id": "INV001",
  "carbon_category": "경유",
  "scope": "Scope 1",
  "activity_amount": 120,
  "activity_unit": "L",
  "emission_factor": 2.616,
  "emissions_kgco2e": 313.92,
  "data_quality_score": 2,
  "k_taxonomy_candidate": "N",
  "k_taxonomy_candidate_type": null,
  "facility_investment_detected": "N",
  "facility_investment_type": null,
  "finance_lead_type": null,
  "confidence": 0.94,
  "evidence": "품목명에 '경유'가 있고 수량 120L가 확인됨",
  "hitl_required": false,
  "hitl_reason": null
}
```

설비투자 전표 출력 예시:

```json
{
  "source_record_id": "INV005",
  "carbon_category": "배출량 계산 제외",
  "scope": "제외",
  "activity_amount": null,
  "activity_unit": null,
  "emission_factor": null,
  "emissions_kgco2e": null,
  "data_quality_score": null,
  "k_taxonomy_candidate": "REVIEW",
  "k_taxonomy_candidate_type": "에너지효율 개선",
  "facility_investment_detected": "Y",
  "facility_investment_type": "고효율 압축기",
  "finance_lead_type": "설비금융 후보",
  "confidence": 0.88,
  "evidence": "품목명에 '고효율 압축기'가 포함됨",
  "hitl_required": true,
  "hitl_reason": "K-택소노미 최종 적합성은 은행 담당자 검토 필요"
}
```

---

# 3-15. `hitl_queue_mock` 시트

## 목적

AI가 자동 확정하지 않고 은행 담당자 또는 검토자에게 넘기는 목록이다.

## HITL 대상 기준

| 조건 | 예시 |
|---|---|
| AI confidence 낮음 | 0.75 미만 |
| 품목명 불명확 | LPG 외 1종, 장비대, 공사비 |
| 단위 불명확 | LPG인데 kg/L/Nm³ 구분 없음 |
| 금액만 있고 역산 불가 | 전기요금 금액만 있음 |
| K-택소노미 후보 | 태양광, 고효율 설비, 전동지게차 |
| 설비투자 여부 불명확 | 유지보수비, 수리비 |
| 관계없는 파일 의심 | 식비, 사무용품 등 |

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| hitl_id | HITL ID | H001 |
| company_id | 기업 ID | C003 |
| source_record_id | 원천 데이터 ID | INV004 |
| issue_type | 이슈 유형 | 단위 불명확 |
| original_text | 원본문구 | LPG 외 1종 |
| ai_suggestion | AI 제안 | LPG 후보 |
| confidence | 신뢰도 | 0.61 |
| evidence | 판단근거 | LPG 키워드는 있으나 수량·단위 없음 |
| reviewer_action_needed | 담당자 조치 | 보완요청 |
| final_status | 처리상태 | 대기 |

## 예시

| hitl_id | company_id | source_record_id | issue_type | original_text | ai_suggestion | confidence | reviewer_action_needed | final_status |
|---|---|---|---|---|---|---:|---|---|
| H001 | C003 | INV004 | 단위 불명확 | LPG 외 1종 | LPG 후보 | 0.61 | 거래명세서 요청 | 대기 |
| H002 | C001 | INV005 | K-택소노미 후보 | 고효율 압축기 구입 | 에너지효율 개선 후보 | 0.88 | 설비투자 목적 확인 | 대기 |
| H003 | C002 | INV006 | K-택소노미 후보 | 태양광 설비 설치 | 재생에너지 설비 후보 | 0.92 | 녹색여신 검토 | 대기 |
| H004 | C002 | F004 | 관계없는 파일 | 식비영수증 | 탄소계산 무관 | 0.97 | 자동반려 확인 | 완료 |

---

# 3-16. `bank_loans_mock` 시트

## 목적

은행 대시보드에서 금융배출량 확장 가능성을 보여주기 위한 mock 여신데이터다. 실제 은행 내부 데이터가 아니므로 발표에서는 “시뮬레이션용 가정 데이터”라고 명시한다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| loan_id | 대출 ID | L001 |
| company_id | 기업 ID | C001 |
| loan_balance_krw | 대출잔액 | 500000000 |
| total_equity_krw | 자본총계 | 2000000000 |
| total_liabilities_krw | 부채총계 | 4000000000 |
| company_value_proxy_krw | 기업가치 대용값 | 6000000000 |
| attribution_factor | 귀속계수 | 0.0833 |
| company_emissions_tco2e | 기업 Scope 1/2 배출량 | 128.4 |
| attributed_emissions_tco2e | 추정 금융배출량 | 10.7 |
| note | 비고 | mock 데이터 |

## 계산식

```text
기업가치 대용값 = 자본총계 + 부채총계
귀속계수 = 은행 대출잔액 ÷ 기업가치 대용값
추정 금융배출량 = 기업 Scope 1/2 배출량 × 귀속계수
```

## 예시

| loan_id | company_id | loan_balance_krw | company_value_proxy_krw | attribution_factor | company_emissions_tco2e | attributed_emissions_tco2e |
|---|---|---:|---:|---:|---:|---:|
| L001 | C001 | 500000000 | 6000000000 | 0.0833 | 128.4 | 10.7 |
| L002 | C002 | 300000000 | 5000000000 | 0.0600 | 94.2 | 5.7 |
| L003 | C003 | 800000000 | 8000000000 | 0.1000 | 210.8 | 21.1 |

## 발표 주석

```text
※ 여신잔액, 귀속계수, 추정 금융배출량은 MVP 시연을 위한 mock 데이터입니다.
※ 실제 금융배출량 산정은 은행 내부 여신데이터 및 재무정보 연동 후 가능합니다.
```

---

# 3-17. `portfolio_dashboard_mock` 시트

## 목적

은행 담당자 대시보드에서 포트폴리오 단위로 데이터 품질, 탄소집약 업종, 보완 우선순위를 보여준다.

## 권장 컬럼

| 컬럼명 | 설명 | 예시 |
|---|---|---|
| segment_id | 세그먼트 ID | S001 |
| region | 지역 | 경북 구미 |
| industry | 업종 | 금속가공 |
| company_count | 기업 수 | 23 |
| total_loan_balance_krw | 총 대출잔액 | 12000000000 |
| avg_wadqs_before | 감탄 전 평균 데이터품질점수 | 5.0 |
| avg_wadqs_after | 감탄 후 평균 데이터품질점수 | 2.8 |
| expected_wadqs_improvement | 예상 개선폭 | -2.2 |
| total_emissions_tco2e | 총 배출량 | 8200 |
| priority_rank | 우선순위 | 1 |
| ai_caption | AI 브리핑 문장 | 구미 금속가공 기업군은 데이터 품질 개선 여지가 큼 |

## 예시

| segment_id | region | industry | company_count | total_loan_balance_krw | avg_wadqs_before | avg_wadqs_after | expected_wadqs_improvement | priority_rank | ai_caption |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| S001 | 경북 구미 | 금속가공 | 23 | 12000000000 | 5.0 | 2.8 | -2.2 | 1 | 구미 금속가공 기업군은 대출잔액 비중이 높고 데이터 품질 개선 여지가 큽니다. |
| S002 | 대구 달서 | 표면처리 | 14 | 8500000000 | 5.0 | 3.1 | -1.9 | 2 | 표면처리 업종은 탄소집약도가 높아 우선 관리가 필요합니다. |
| S003 | 경북 경산 | 전자부품 | 18 | 9500000000 | 4.5 | 2.4 | -2.1 | 3 | 전자부품 기업군은 전기 사용량 기반 데이터 확보 효과가 큽니다. |

---

## 4. 데이터 품질점수 설계

감탄은 PCAF 공식 인증 등급을 부여하는 서비스가 아니라, 데이터 출처별 신뢰도 차이를 설명하기 위해 내부적으로 데이터 품질점수를 부여한다.

## 4-1. 데이터 품질점수 기준

| 점수 | 데이터 유형 | 예시 | 감탄 처리 |
|---:|---|---|---|
| 1 | 검증된 보고배출량 | 외부 검증 완료 배출량 | MVP에서는 거의 없음 |
| 2 | 실제 활동자료 기반 | 전기 kWh, 경유 L, 도시가스 m³ | 가장 신뢰도 높은 자동계산 |
| 3 | 활동자료에 가까운 추정 | 경유/휘발유 금액역산 | 보조 추정값 |
| 4 | 기업 특성 기반 추정 | 업종·매출·종업원 기반 | 결손 보완용 |
| 5 | 업종 평균 기반 추정 | 업종 평균 배출량 | 기존 상태/Before 표현 |

## 4-2. WADQS 계산

WADQS는 전표별 데이터 품질점수를 배출량 비중으로 가중평균한 값이다.

```text
WADQS = Σ(배출량_i × 데이터품질점수_i) ÷ Σ(배출량_i)
```

## 예시

| 데이터 | 배출량 비중 | 품질점수 |
|---|---:|---:|
| 전기 kWh 기반 | 60% | 2 |
| 경유 금액역산 | 30% | 3 |
| 업종 평균 추정 | 10% | 5 |

```text
WADQS = 2×0.6 + 3×0.3 + 5×0.1 = 2.6
```

## 발표용 문장

```text
감탄은 전표별 데이터 품질점수를 부여하고, 배출량 비중을 기준으로 가중평균 데이터 품질점수(WADQS)를 계산합니다.
이를 통해 기업별 탄소 데이터가 기존 업종 평균 추정값 대비 얼마나 개선되었는지 보여줍니다.
```

---

## 5. 합성데이터에 반드시 포함할 시나리오

최소한 아래 시나리오는 포함해야 한다.

| 시나리오 ID | 시나리오 | 목적 |
|---|---|---|
| SCE001 | 경유 수량 L이 있는 세금계산서 | Scope 1 자동계산 검증 |
| SCE002 | 경유 수량 없이 금액만 있는 영수증 | 월별단가 역산 검증 |
| SCE003 | 휘발유 수량 L이 있는 영수증 | 연료 영수증 허용 검증 |
| SCE004 | 전기고지서 kWh 있음 | Scope 2 자동계산 검증 |
| SCE005 | 전기요금 납부내역만 있고 kWh 없음 | 보완요청 검증 |
| SCE006 | 도시가스 고지서 m³ 있음 | Scope 1 도시가스 계산 검증 |
| SCE007 | 도시가스 금액만 있음 | 자동계산 제외 검증 |
| SCE008 | LPG 외 1종 | HITL 검증 |
| SCE009 | 태양광 설비 설치 | K-택소노미 후보 탐지 검증 |
| SCE010 | 고효율 압축기 구입 | 설비금융 리드 검증 |
| SCE011 | 전동지게차 리스료 | 리스금융 리드 검증 |
| SCE012 | 절삭유 구매 | 제외/Scope3 후보 처리 검증 |
| SCE013 | 관계없는 식비 영수증 | 자동 반려 검증 |
| SCE014 | 유지보수비/공사비 | 불명확 설비투자 HITL 검증 |
| SCE015 | 동일 전표 중복 업로드 | 중복 제외 검증 |

---

## 6. 계산 규칙 요약

## 6-1. Scope 1

| 대상 | 계산 기준 |
|---|---|
| 경유 | L × 경유 배출계수 |
| 휘발유 | L × 휘발유 배출계수 |
| 도시가스 | m³ × 도시가스 배출계수 |
| LPG | 단위와 성분이 명확한 경우에만 계산, 아니면 HITL |

## 6-2. Scope 2

| 대상 | 계산 기준 |
|---|---|
| 전기 | kWh × 전력 배출계수 |

## 6-3. 금액역산

| 대상 | 처리 |
|---|---|
| 경유 | 공급가액 ÷ 월별 경유 평균단가 |
| 휘발유 | 공급가액 ÷ 월별 휘발유 평균단가 |
| 전기 | 금액역산 기본 적용 안 함 |
| 도시가스 | 금액역산 기본 적용 안 함 |
| LPG | 금액역산 기본 적용 안 함 |

---

## 7. AI 출력 필드 최종안

개발팀에 넘길 최종 출력 스키마는 아래와 같이 정리한다.

| 필드명 | 설명 | 예시 |
|---|---|---|
| source_record_id | 원천 데이터 ID | INV001 |
| document_type | 문서유형 | 세금계산서 |
| carbon_category | 탄소 분류 | 경유 |
| scope | Scope | Scope 1 |
| activity_amount | 활동량 | 120 |
| activity_unit | 단위 | L |
| calculation_method | 계산 방식 | 수량기반 |
| emission_factor | 배출계수 | 2.616 |
| emissions_kgco2e | 배출량 | 313.92 |
| data_quality_score | 데이터 품질점수 | 2 |
| k_taxonomy_candidate | K-택소노미 후보 여부 | N / REVIEW |
| k_taxonomy_candidate_type | 후보유형 | 에너지효율 개선 |
| facility_investment_detected | 설비투자 탐지 여부 | Y/N |
| facility_investment_type | 설비투자 유형 | 고효율 압축기 |
| finance_lead_type | 금융리드 유형 | 설비금융 후보 |
| confidence | AI 신뢰도 | 0.94 |
| evidence | 판단근거 | 품목명에 경유, 단위 L 확인 |
| hitl_required | 사람검토 여부 | true/false |
| hitl_reason | 사람검토 사유 | LPG 단위 불명확 |
| trace_plan | 계획 로그 | 품목명과 단위를 확인한다 |
| trace_observation | 관찰 로그 | 경유 120L 확인 |
| trace_action | 행동 로그 | Scope 1 경유로 계산한다 |

---

## 8. 합성데이터 검증 지표

합성데이터를 만든 뒤 아래 지표를 계산하면 발표에서 “진짜 돌아간다”는 근거로 쓸 수 있다.

| 지표 | 계산 방식 | 의미 |
|---|---|---|
| 분류 정확도 | AI 분류가 expected_results와 일치한 비율 | 품목 분류 성능 |
| 계산 오차율 | abs(AI 배출량 - 기대 배출량) / 기대 배출량 | 계산 정확도 |
| HITL 탐지율 | HITL 대상 중 실제 HITL로 분류된 비율 | 사람검토 분기 성능 |
| 자동반려 정확도 | 관계없는 파일을 반려한 비율 | 업로드 품질 관리 |
| K-택소노미 후보 탐지율 | 후보 전표를 올바르게 탐지한 비율 | 금융리드 탐지 성능 |
| WADQS 개선폭 | Before WADQS - After WADQS | 데이터 품질 개선 효과 |

## 발표용 검증 문장 예시

```text
합성데이터에는 자동계산, 금액역산, 사람검토, K-택소노미 후보, 관계없는 파일 반려 시나리오를 모두 포함했습니다.
이를 통해 감탄 AI의 분류 정확도, 계산 오차율, HITL 탐지율, K-택소노미 후보 탐지 여부를 검증했습니다.
```

---

## 9. 합성데이터 제작 순서

실제로 엑셀을 만들 때는 아래 순서로 진행한다.

```text
1. company_master에 가상 기업 4~6개 생성
2. 기업별 사용 에너지 유형 설정
3. mydata_documents에 기업별 자동 확인 자료 생성
4. uploaded_files에 업로드 파일 목록 생성
5. tax_invoices_receipts에 연료·설비·소모품 전표 생성
6. electricity_bills에 전기 kWh 데이터 생성
7. citygas_bills에 도시가스 m³ 데이터 생성
8. emission_factors와 monthly_fuel_prices 기준표 입력
9. classification_rules, k_taxonomy_mapping, facility_keywords 작성
10. expected_results에 정답값 계산
11. ai_outputs_mock에 AI 출력 예시 생성
12. hitl_queue_mock에 사람검토 대상 생성
13. bank_loans_mock에 mock 여신데이터 생성
14. portfolio_dashboard_mock에 은행 대시보드용 집계 데이터 생성
15. 계산값과 정답지 검증
```

---

## 10. 발표에서 합성데이터를 설명하는 문장

## 짧은 버전

```text
실제 영세기업 전표는 개인정보와 거래정보가 포함되어 확보가 어렵기 때문에, 실제 세금계산서·고지서 구조를 반영한 합성데이터를 제작했습니다.
합성데이터에는 전기 kWh, 경유·휘발유 구매전표, 도시가스 고지서, LPG 불명확 전표, 설비투자 전표를 포함해 감탄 AI의 분류·계산·HITL·금융리드 탐지 흐름을 검증했습니다.
```

## 상세 버전

```text
본 MVP에서는 실제 기업 전표를 직접 수집하는 대신, 실제 제조업 세금계산서와 전기·가스 고지서의 필드 구조를 반영한 합성데이터를 구성했습니다.
단순 더미 데이터가 아니라, 수량 기반 자동계산, 금액 기반 연료 사용량 추정, 전기·도시가스 사용량 기반 계산, LPG처럼 단위가 불명확한 사람검토 케이스, K-택소노미 후보가 되는 설비투자 전표까지 포함했습니다.
이를 통해 감탄 AI가 실제 서비스에서 마주칠 수 있는 입력 상황을 재현하고, 분류 정확도와 계산 오차율, HITL 분기, 금융리드 탐지 가능성을 검증했습니다.
```

---

## 11. 유의사항

### 11-1. 실제 기업명처럼 보이되, 실제 기업으로 오해되지 않게 한다

기업명은 `구미정밀`, `대경부품`, `성서테크`처럼 현실적인 이름을 쓰되, 실제 존재 기업과 혼동되지 않도록 한다.

### 11-2. 사업자등록번호는 가상값으로 만든다

실제 사업자번호를 사용하지 않는다.

예시:

```text
123-45-67890
111-22-33333
444-55-66666
```

### 11-3. 금융배출량 데이터는 mock임을 명시한다

은행 여신잔액, 귀속계수, 추정 금융배출량은 실제 데이터가 아니므로 발표자료와 대시보드 하단에 반드시 주석을 단다.

```text
※ 여신잔액, 귀속계수, 추정 금융배출량은 MVP 시연을 위한 mock 데이터입니다.
※ 실제 금융배출량 산정은 은행 내부 여신데이터 및 재무정보 연동 후 가능합니다.
```

### 11-4. K-택소노미는 최종 판정이 아니라 후보 탐지로 표현한다

```text
감탄 AI는 K-택소노미 적합성을 최종 확정하지 않고, 후보와 판단근거만 제시한다.
최종 판단은 은행 담당자가 수행한다.
```

### 11-5. 전기와 도시가스는 금액역산을 기본 적용하지 않는다

```text
전기와 도시가스는 요금 구조가 복잡하므로 금액만으로 사용량을 역산하지 않는다.
고지서의 실제 사용량 kWh, m³를 우선 사용하고, 금액만 있는 경우에는 보완 요청 또는 사람검토로 이관한다.
```

---

## 12. 최종 산출물 체크리스트

| 체크 항목 | 완료 여부 |
|---|---|
| 기업 4~6개 이상 생성 |  |
| 기업별 에너지 사용 유형 설정 |  |
| 마이데이터 자료 5종 이상 반영 |  |
| 세금계산서/영수증/거래명세서 데이터 포함 |  |
| 전기고지서 kWh 데이터 포함 |  |
| 도시가스 고지서 m³ 데이터 포함 |  |
| LPG 불명확 케이스 포함 |  |
| 경유/휘발유 금액역산 케이스 포함 |  |
| K-택소노미 후보 전표 포함 |  |
| 설비투자 키워드 전표 포함 |  |
| 관계없는 파일 자동반려 케이스 포함 |  |
| expected_results 정답지 포함 |  |
| ai_outputs_mock 포함 |  |
| hitl_queue_mock 포함 |  |
| bank_loans_mock 주석 포함 |  |
| portfolio_dashboard_mock 포함 |  |
| WADQS 계산 가능 |  |
| 발표용 설명 문장 포함 |  |

---

## 13. 한 줄 요약

```text
감탄 합성데이터는 실제 영세 제조기업의 세금계산서·고지서 구조를 반영해, Scope 1/2 탄소계산, PCAF 데이터 품질 개선, HITL 검토, K-택소노미 후보 탐지, 설비금융 리드까지 한 번에 검증하기 위한 MVP용 테스트 데이터셋이다.
```
