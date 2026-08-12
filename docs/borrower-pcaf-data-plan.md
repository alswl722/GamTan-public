# 감탄 PCAF 차주 데이터 제품 전환 상세 계획서

```text
Status: authoritative
Last updated: 2026-08-05
Superseded by: 없음
Scope: 감탄의 PCAF 제품 범위, TO-BE 데이터·계산·체크리스트·운영 설계
```

> **구현 현황 포인터 (2026-08-12)** — 이 문서는 TO-BE 목표 설계로서 여전히 유효하다. 실제 진행 상황·주차별 완료조건은 `docs/v1-plan.md`, DB 스키마의 현재 정본 대조표는 `docs/db-schema.md`를 참고할 것. 이 문서가 그리는 설계 중 이미 구현된 부분:
> - §7이 정의하는 기관/포트폴리오/조직경계/차주 인벤토리/가스별 배출량/익스포저/재무정보/환율 스키마 — Alembic 마이그레이션(`alembic/versions/0001~0006`)으로 반영 완료.
> - PCAF Business Loans 데이터 품질 후보 규칙 엔진(Table 10.1-2 옵션 체계) — `db/pcaf_quality.py` + `pcaf_quality_rules` 테이블로 구현 완료(`docs/v1-plan.md` §5-1).
> - 하이브리드 데이터 입력(마이데이터 5종 + 업로드 3종) — `source_documents`/`vouchers` 경로로 구현 완료(`docs/v1-plan.md` §5-2). 단 이 문서가 전제하는 "차주 인벤토리(`borrower_emission_inventories`) 직접 적재"까지는 아직 안 갔다 — 그 연간 Scope 집계 로직 자체가 미구현.
> - 사장님 화면의 PCAF 리포트(`ScenePcaf.tsx`)는 아직 이 문서의 정식 엔진이 아니라 구 임시 엔진(`db/pcaf.py`)을 쓴다 — 교체 진행 중.

## 1. 문서 목적

이 문서는 현재 감탄을 PCAF 전체 금융배출량 산정 시스템으로 과도하게 확장하지 않고, 다음 제품으로 전환하기 위한 구현 계획을 정의한다.

> 중소기업의 전표·고지서에서 Scope 1·2 배출량과 산정 근거를 생성하고, PCAF 기업대출 산정에 사용할 수 있는 차주 데이터와 데이터 품질 후보를 은행에 제공하는 시스템

은행 전체 자산군의 공식 금융배출량과 PCAF 공시는 은행이 최종 책임진다. 감탄은 차주 데이터 생성, 품질 개선, 근거 추적을 핵심 책임으로 하되, `Business Loans and Unlisted Equity` 자산군 중 비상장 중소기업의 일반 목적 기업대출에 대해서는 실제 금융배출량 산정 기능을 제공한다. 동일 공식을 차주별 변수에 반복 적용하고 결과를 합산해 감탄에 등록된 기업대출 포트폴리오의 금융배출량을 계산한다.

---

## 2. 배경과 현재 문제

현재 감탄은 홈택스 전표와 전기 고지서를 수집한 뒤 품목을 분류하고, 다음 공식으로 기업 자체 배출량을 계산한다.

```text
활동량 = 구매금액 / 월별 단가
기업 배출량 = 활동량 × 배출계수
```

이 결과는 차주의 Scope 1 또는 Scope 2 배출량이다. PCAF Part A의 금융배출량은 은행의 금융 익스포저를 추가로 반영해야 한다.

```text
금융배출량 = 귀속계수 × 차주 배출량
```

현재 시스템의 주요 문제는 다음과 같다.

1. 기업 자체 Scope 1·2 합계를 금융배출량 또는 포트폴리오 배출량처럼 표현한다.
2. 프로젝트 내부 임시 규칙을 PCAF 1~5점처럼 표시한다.
3. LLM 분류 신뢰도, 사람 검토 상태, 활동자료 품질, PCAF 데이터 품질이 혼합돼 있다.
4. 실제 고지서 사용량과 구매금액 기반 사용량 추정이 화면에서 모두 실측으로 표현된다.
5. 기업에 정수 등급 하나를 부여하고 배출량으로 가중평균한다.
6. 조직경계, 보고연도, 배출계수 버전, GWP 버전, 검증 여부를 충분히 저장하지 않는다.
7. 대출잔액, 차주 재무정보, 귀속계수가 없으므로 공식 금융배출량을 계산할 수 없다.
8. PCAF 데이터 품질을 우대금리 자격과 직접 연결해 표현한다.

---

## 3. 제품 범위 결정

### 3.1 핵심 제품 범위

- 차주 기본정보와 보고연도 관리
- 전표·고지서 원본 및 추출값 관리
- 배출원 분류와 사람 검토
- Scope 1·2 활동자료 계산
- 차주 연간 Scope 1·2 인벤토리 생성
- 실제 자료, 추정자료, 산업평균 자료의 구성비 표시
- 데이터 완전성 평가
- PCAF 기업대출 방법론에 사용할 데이터 품질 후보 평가
- 평가 근거, 제한사항, 증빙자료 제공
- 은행 전달용 JSON 및 Excel 내보내기
- 결정론적 PCAF 체크리스트 자동점검
- AI를 이용한 보고서 증빙 검색, 설명 검토, 보완문구 작성
- 은행 담당자의 체크리스트 최종 승인과 감사기록
- 기존 기획·개발·데모 문서의 PCAF 용어와 제품 범위 동기화
- 금융기관·포트폴리오·익스포저 기준의 데이터 격리와 산정 스냅숏
- 조직경계·통화·기준일·재산정 정책 검증

### 3.2 금융배출량 산정 범위

- 자산군: `Business Loans and Unlisted Equity`
- 대상: 비상장 중소기업의 일반 목적 기업대출
- 입력: 대출잔액, 총자본, PCAF 방법론상 debt, 기준일, 통화
- 출력: 차주별 귀속계수, Scope 1·2 금융배출량, Scope 3 금융배출량, 대상 포트폴리오 합계
- 산식: `대출잔액 / (총자본 + PCAF 방법론상 debt) × 차주 배출량`
- 성격: 지원 자산군에 대한 PCAF 산식 기반 계산 결과이며, 은행 전체 자산군의 공식 공시 결과는 아님

### 3.3 제외 범위

- 은행 전체 여신원장 연동
- PCAF 10개 자산군 전체 구현
- 미지원 자산군을 포함한 은행 전체 포트폴리오 공식 커버리지 산정
- 공식 PCAF 공시 확정
- 외부 검증 또는 assurance
- PCAF 점수 기반 우대금리 자동판정
- Scope 3 전체 자동산정
- AI 단독의 PCAF 준수 여부 최종 판정

### 3.4 체크리스트 지원 모드

체크리스트는 제품 지원범위와 은행 전체 공시범위를 혼동하지 않도록 두 모드로 분리한다.

| 모드 | 목적 | 자동판정 범위 | 결과 명칭 |
|---|---|---|---|
| `business_loans_readiness` | 감탄이 지원하는 비상장 일반 목적 기업대출 점검 | 감탄 내부 데이터로 판정 가능한 항목 | PCAF 기업대출 준비도 점검 |
| `full_pcaf_dcl` | 은행 전체 관련 자산군의 Part A 점검 | 외부 자산군·전체 포트폴리오 데이터가 모두 있을 때만 실행 | PCAF DCL 검토 지원 |

`full_pcaf_dcl`은 미지원 자산군 데이터가 없거나 전체 관련 대출·투자잔액을 확인할 수 없으면 `insufficient_scope` 상태로 중단한다. 감탄 내부 기업대출 데이터만으로 전체 PCAF 준수 또는 전체 커버리지를 통과 처리하지 않는다.

---

## 4. 목표 아키텍처

```text
[원본 데이터]
홈택스 전표 / 전기·가스 고지서 / 수기 자료 / 외부 배출량 보고서
        ↓
[분류 계층]
룰·LLM 분류 / HITL / 문서 중복 검증
        ↓
[활동자료 계층]
실제 사용량 / 금액 환산 사용량 / 경제활동 추정 / 산업평균
        ↓
[차주 배출량 계층]
연간 Scope 1·2 인벤토리 / 조직경계 / 완전성 / 산정근거
        ↓
[PCAF 지원 계층]
Business Loans 데이터 품질 후보 / 제한사항 / 은행 검토 상태
        ↓
[전달 계층]
차주 화면 / 은행 관리자 화면 / JSON / Excel
        ↓
[기업대출 금융배출량 산정]
차주별 대출잔액 + 총자본·PCAF debt → 귀속계수 → 금융배출량 → 대상 포트폴리오 합계
        ↓
[PCAF 체크리스트 계층]
기업대출 준비도 또는 전체 DCL 모드 선택 → 범위 검증 → 규칙 엔진 자동판정
→ AI 증빙·서술 검토 → 은행 담당자 최종 승인 → 구분된 결과 출력
```

---

## 5. 핵심 용어와 화면 문구 변경

| 현재 표현 | 변경 표현 |
|---|---|
| PCAF 등급 | PCAF 데이터 품질 후보 |
| PCAF 계산 엔진 | 차주 배출량·품질평가 엔진 |
| 포트폴리오 금융배출량 | 차주 배출량 데이터 현황 |
| 전표 기반 실측 | 활동자료 기반 산정 또는 금액 기반 추정 |
| PCAF Before/After | 통계 추정 대비 활동자료 기반 개선 |
| PCAF 우대금리 대상 | 제거 또는 은행 상품 기준 별도 안내 |

모든 품질 후보 화면에는 다음 문구를 표시한다.

> 이 점수는 감탄이 보유한 데이터와 PCAF 기업대출 데이터 계층을 기준으로 산출한 후보입니다. 금융기관의 최종 검토가 필요합니다.

---

## 6. 데이터 품질 개념 분리

시스템은 다음 네 개의 품질 개념을 별도로 관리한다.

### 6.1 분류 신뢰도

- 질문: 전표 품목이 전기, 경유, 가스 등으로 올바르게 분류됐는가?
- 값: `0.0~1.0`
- 출처: 룰 또는 LLM
- 용도: HITL 우선순위
- PCAF 품질점수와 직접 연결하지 않는다.

### 6.2 활동자료 방법

- `reported_quantity`: 차주가 보고한 사용량
- `invoice_quantity`: 고지서·명세서에 기재된 실제 사용량
- `spend_converted`: 구매금액을 단가로 나눈 추정 사용량
- `economic_estimate`: 매출 등 차주 경제자료 기반 추정
- `industry_estimate`: 차주별 자료 없이 산업평균 사용

### 6.3 차주 인벤토리 완전성

- 보고기간 12개월 충족 여부
- 포함 사업장과 제외 사업장
- Scope 1 배출원별 산정 여부
- Scope 2 구매에너지별 산정 여부
- 결손월과 미산정 배출원
- 실제·추정·평균 자료 구성비

완전성은 PCAF 품질 후보와 분리해서 표시한다.

### 6.4 PCAF 데이터 품질 후보

- 적용 자산군: Business Loans and Unlisted Equity
- Scope 1·2와 Scope 3를 분리
- PCAF 표준 버전과 적용 규칙을 저장
- 차주 보고 배출량, 검증 여부, 활동자료, 경제자료, 산업평균 여부로 판정
- 은행 검토 전 상태는 `candidate`로 표시

---

## 7. 데이터 모델 변경

### 7.1 `classifications` 보완

기존 `method`는 분류방법만 나타내도록 의미를 명확히 한다.

추가 필드:

```text
classification_method   rule | llm | manual
activity_data_method    reported_quantity | invoice_quantity |
                        spend_converted | economic_estimate |
                        industry_estimate
source_document_id      원본 증빙 FK
quantity_source         document | calculated | manual
factor_id               적용 배출계수 FK
factor_version           배출계수 버전
data_period_start        활동자료 시작일
data_period_end          활동자료 종료일
calculation_warning      계산 경고 JSON
```

`confidence`는 계속 분류 신뢰도로만 사용한다.

기존 `vouchers`에는 `financial_institution_id`와 `institution_borrower_id`를 추가해 동일 차주 자료라도 어느 금융기관의 동의·수집 경로에서 생성됐는지 구분한다.

### 7.2 `source_documents` 신규

```text
id
financial_institution_id
company_id
document_type
source_system
document_date
period_start
period_end
file_hash
original_filename
extracted_json
verification_status
created_at
```

목적:

- 동일 문서 중복 적재 방지
- 계산 결과에서 원본까지 추적
- 증빙자료 보존정책 적용

### 7.3 `organizational_boundaries` 신규

차주 배출량의 조직범위와 재무정보의 연결범위를 비교하기 위한 기준정보다.

```text
id
financial_institution_id
company_id
reporting_year
boundary_type             operational_control | financial_control | equity_share
consolidation_scope       consolidated | separate
included_entities_json
excluded_entities_json
description
approved_by
approved_at
created_at
```

### 7.4 `borrower_emission_inventories` 신규

```text
id
financial_institution_id
company_id
reporting_year
organizational_boundary_id
scope_group               scope_1 | scope_2 | scope_3
scope2_method             location_based | market_based | null
scope3_status             reported | estimated | not_reported |
                          not_calculated | not_applicable | null
emission_tco2e
calculation_method_summary
gwp_version
verified
verification_level
completeness_pct
candidate_quality_score
candidate_quality_rule_id
limitations_json
status                    draft | calculated | reviewed | approved | superseded
version
supersedes_inventory_id
input_snapshot_hash
approved_by
approved_at
created_at
```

Scope 3 미산정은 `0`이 아니라 `emission_tco2e = null`과 명시적 `scope3_status`로 저장한다. Scope 2 location-based와 market-based는 서로 다른 행으로 관리한다.

### 7.5 `inventory_gas_emissions` 신규

```text
id
inventory_id
gas_type                  CO2 | CH4 | N2O | HFCs | PFCs | SF6 | NF3
emission_mass
mass_unit
gwp_value
gwp_version
emission_co2e
included
exclusion_reason
```

해당 기업 활동에서 배출되는 7대 온실가스를 지원한다. 현재 자동산정하지 못하는 가스는 0으로 간주하지 않고 미확인 또는 제외 사유를 남긴다.

### 7.6 `inventory_source_items` 신규

연간 인벤토리와 전표별 계산 결과를 연결한다.

```text
inventory_id
classification_id
emission_tco2e
activity_data_method
included
exclusion_reason
```

### 7.7 `pcaf_quality_rules` 신규

```text
id
standard_version
asset_class
scope_group
rule_code
reported_emissions_required
verification_required
activity_data_required
economic_data_required
quality_score
description
source_reference
valid_from
valid_to
```

PCAF Annex의 Business Loans 상세 데이터 품질표를 규칙 단위로 옮기고 원문 근거를 기록한다. 검증된 보고값·미검증 보고값·활동자료·경제자료를 단순화한 자체 규칙으로 대체하지 않는다.

### 7.8 `financial_institutions` 신규

```text
id
name
reporting_currency
tenant_key
created_at
```

### 7.9 `institution_users` 신규

```text
id
financial_institution_id
user_id
role                       admin | analyst | reviewer | approver | viewer
active
created_at
```

### 7.10 `institution_borrowers` 신규

```text
id
financial_institution_id
company_id
external_customer_id
consent_status             pending | active | revoked | expired
consent_scope_json
consent_started_at
consent_ended_at
created_at
```

`(financial_institution_id, external_customer_id)`에 유니크 제약을 둔다. 차주가 여러 은행과 거래하더라도 원본 문서와 산정 결과는 명시적 동의 범위 없이 기관 간 공유하지 않는다.

### 7.11 `portfolios` 신규

```text
id
financial_institution_id
name
reporting_year
reporting_date
reporting_currency
scope_mode                 supported_business_loans | full_institution
total_relevant_outstanding
reporting_date_events_json
status                     draft | calculated | reviewed | approved | superseded
version
supersedes_portfolio_id
created_at
```

### 7.12 `portfolio_asset_class_summaries` 신규

감탄이 직접 계산하지 않는 자산군을 포함해 전체 DCL 범위검사에 필요한 외부 집계값을 받는다.

```text
id
portfolio_id
asset_class
relevant_outstanding_amount
included_outstanding_amount
scope_1_2_financed_emissions
scope_3_financed_emissions
scope_3_status
weighted_quality_scope_1_2
weighted_quality_scope_3
calculation_methodology
source_system
source_snapshot_json
reviewed
created_at
```

외부 집계값은 감탄이 계산한 결과와 구분해 출처와 검토상태를 표시한다. `full_pcaf_dcl` 범위검사와 증빙에는 사용할 수 있지만 감탄 계산 결과로 표현하지 않는다.

### 7.13 `business_loan_exposures` 신규

```text
id
portfolio_id
company_id
external_exposure_id
asset_class
outstanding_amount
currency
reporting_date
loan_purpose
company_type
included
exclusion_reason
source_snapshot_json
created_at
```

`(portfolio_id, external_exposure_id)`에 유니크 제약을 둔다. 동일 차주의 여러 대출은 개별 익스포저로 보존하되 산정 시 차주·기준일·통화별 합계와 중복을 검증한다.

지원 조건:

- `asset_class = business_loans_and_unlisted_equity`
- `company_type = private_company`
- `loan_purpose = general_corporate_purpose`

지원 조건을 충족하지 않으면 다른 자산군 공식으로 억지 계산하지 않고 `unsupported_methodology`와 제외 사유를 기록한다.

### 7.14 `borrower_financials` 신규

```text
id
financial_institution_id
company_id
financial_year
as_of_date
currency
total_equity
total_debt
debt_definition
consolidation_scope
included_entities_json
source
verified
version
created_at
```

`total_debt`는 총부채와 혼용하지 않는다. PCAF 방법론에 사용하는 debt 정의와 재무제표 계정을 `debt_definition`에 고정하고 출처를 보존한다.

### 7.15 `fx_rates` 신규

```text
id
base_currency
quote_currency
rate
rate_date
rate_type                  closing | average | policy_defined
source
created_at
```

대출잔액과 재무정보를 포트폴리오 보고통화로 변환한다. 적용 환율, 기준일, 출처를 결과 스냅숏에 포함한다.

### 7.15.1 `emission_factor_adjustments` 신규

```text
id
emission_factor_id
adjustment_type            inflation
index_name                 CPI | PPI | GDP_DEFLATOR | other
base_year
target_year
adjustment_value
source
methodology
created_at
```

경제적 배출계수에 인플레이션 조정을 적용하면 사용 지수·기준연도·방법을 결과와 공시에 기록한다. 조정하지 않은 경우에도 적용 여부를 명시한다.

### 7.16 `financed_emission_results` 신규

```text
id
portfolio_id
exposure_id
inventory_id
borrower_financial_id
methodology_version
scope_group
scope2_method
denominator
attribution_factor
borrower_emissions_tco2e
financed_emissions_tco2e
quality_score
calculation_status         calculated | review_required | excluded | superseded
calculation_status_reason
input_snapshot_json
input_snapshot_hash
assumptions_json
warnings_json
calculated_at
created_at
```

Scope 1·2와 Scope 3 결과를 분리 저장한다. 통화변환, 조직경계, 기준일, 산정 입력과 방법론 버전을 스냅숏으로 고정해 과거 결과를 재현한다.

### 7.17 `recalculation_policies`와 `recalculation_events` 신규

```text
recalculation_policies:
  id, financial_institution_id, baseline_year, significance_threshold,
  threshold_unit, policy_text, version, approved_by, approved_at

recalculation_events:
  id, policy_id, portfolio_id, trigger_type, trigger_value,
  previous_portfolio_version, recalculated_portfolio_version,
  reason, approved_by, approved_at, created_at
```

### 7.18 `disclosure_documents`와 `disclosure_evidence_chunks` 신규

```text
disclosure_documents:
  id, portfolio_id, document_type, reporting_year, filename,
  file_hash, storage_key, status, created_at

disclosure_evidence_chunks:
  id, document_id, page_number, section_title, text,
  text_hash, embedding_reference, created_at
```

차주 전표·고지서인 `source_documents`와 은행 공시보고서를 분리한다. AI는 페이지 번호가 보존된 공시문서 chunk에서만 증빙을 검색한다.

### 7.19 `separate_emission_metrics` 신규

```text
id
portfolio_id
metric_type                biogenic_co2 | carbon_credits_retired |
                           carbon_credits_generated | avoided_emissions |
                           emission_removals
amount_tco2e
methodology
included_in_financed_emissions
source_snapshot_json
created_at
```

생물기원 CO2, 탄소배출권, 회피배출, 제거량을 Scope 1·2·3 금융배출량과 분리한다. `included_in_financed_emissions`가 true면 체크리스트 실패 또는 검토 대상으로 처리한다.

### 7.20 `pcaf_checklist_rules` 신규

PCAF 공시 체크리스트 항목과 자동판정 조건을 버전별로 관리한다.

```text
id
checklist_version
standard_version
supported_mode             business_loans_readiness | full_pcaf_dcl | both
item_code
section
requirement_level          requirement | recommendation
title
description
automation_level           full | partial | manual
condition_json
required_evidence_json
failure_message
ai_review_instruction
active
created_at
```

### 7.21 `pcaf_checklist_runs` 신규

```text
id
portfolio_id
mode                       business_loans_readiness | full_pcaf_dcl
reporting_year
checklist_version
standard_version
status                     running | insufficient_scope | review_required |
                           approved | superseded
scope_validation_json
started_at
completed_at
approved_by
approved_at
```

### 7.22 `pcaf_checklist_results` 신규

```text
id
run_id
rule_id
internal_status            pass | fail | review_required | not_applicable |
                           insufficient_scope
submitted_answer           yes | no | null
evaluated_value_json
evidence_json
failure_reason
ai_comment
ai_model
ai_reviewed_at
reviewer_comment
reviewed_by
reviewed_at
rule_version
created_at
```

내부 상태와 제출용 Yes/No를 분리한다. `review_required`와 `insufficient_scope`는 사람이 확인하거나 필요한 외부 데이터를 제공하기 전 제출 답변으로 자동 변환하지 않는다.

---

## 8. 계산 엔진 변경

### 8.1 차주 배출량 계산

기존 결정론적 구조는 유지한다.

```text
실제 활동자료 방식:
배출량 = 실제 사용량 × 배출계수

금액 환산 방식:
추정 사용량 = 공급가액 / 기준 단가
배출량 = 추정 사용량 × 배출계수
```

추가 출력:

```json
{
  "activity_amount": 1000,
  "activity_unit": "kWh",
  "activity_data_method": "invoice_quantity",
  "factor_id": 12,
  "factor_version": "2025",
  "gwp_version": "AR5",
  "gas_emissions": {
    "CO2": 0,
    "CH4": 0,
    "N2O": 0,
    "HFCs": null,
    "PFCs": null,
    "SF6": null,
    "NF3": null
  },
  "co2e": 450,
  "scope2_method": "location_based",
  "warnings": ["냉매·공정가스 미확인"]
}
```

7대 가스 중 현재 데이터로 확인하지 못한 가스는 `0`이 아니라 `null`과 미확인 경고로 처리한다. Scope 2는 location-based와 market-based를 구분하며 REC·PPA·녹색프리미엄 등 계약수단과 적용 계수 근거를 별도로 저장한다.

### 8.2 연간 인벤토리 집계

```text
기업·보고연도·Scope별 배출량
= 포함된 계산 결과의 합계
```

동시에 다음을 집계한다.

- 실제 활동자료 배출량과 비율
- 금액 환산 배출량과 비율
- 경제자료 추정 배출량과 비율
- 산업평균 배출량과 비율
- 결손월
- 미산정 배출원

### 8.3 PCAF 품질 후보

새 함수 경계:

```python
classify_activity_data_method(...)
assess_inventory_completeness(...)
assess_borrower_emission_quality(...)
build_quality_evidence(...)
```

반환 예시:

```json
{
  "standard": "PCAF Part A Third Edition",
  "asset_class": "Business Loans and Unlisted Equity",
  "scope_group": "scope_1_2",
  "candidate_score": 3,
  "status": "candidate",
  "rule_code": "BL-DQ-OPTION-2B",
  "basis": [
    "차주의 실제 전력·연료 사용자료 사용",
    "공인 배출계수 적용"
  ],
  "limitations": [
    "제3자 검증 없음",
    "공정배출 미확인",
    "냉매배출 미확인"
  ],
  "completeness_pct": 82.5,
  "bank_review_required": true
}
```

### 8.4 기업대출 금융배출량 산정

비상장 중소기업의 일반 목적 기업대출만 지원하며, 동일 공식을 모든 지원 차주에 반복 적용한다.

```text
분모 = 총자본 + PCAF 방법론상 debt
IF 분모 <= 0:
    계산 중단
    calculation_status = review_required
    calculation_status_reason = non_positive_denominator
    귀속계수·금융배출량 = null
ELSE:
    귀속계수 = 은행 대출잔액 / 분모
    금융배출량 = 귀속계수 × 차주 배출량
```

`분모 > 0`은 계산 함수가 직접 강제하는 불변조건이다. 0 또는 음수인 분모를 임의 보정하거나 절댓값으로 바꾸거나 귀속계수를 0으로 저장해서는 안 된다.

검증 규칙:

- 대출잔액, 총자본, PCAF debt가 모두 있어야 한다.
- 분모가 0 이하이면 계산하지 않는다.
- 대출잔액과 재무정보의 통화를 일치시킨다.
- 통화가 다르면 승인된 환율정책과 `fx_rates`를 적용하고 환율 스냅숏을 저장한다.
- 대출 기준일, 재무연도, 배출량 보고연도를 표시한다.
- 시점 차이가 있으면 경고한다.
- 차주 배출량 조직경계와 재무정보 연결범위를 비교한다.
- 연결범위가 불일치하면 자동 확정하지 않고 `review_required`로 보낸다.
- 귀속계수와 모든 중간값을 저장한다.
- Scope 1·2와 Scope 3를 분리 계산한다.
- 지원 조건을 충족한 차주별 결과만 합산한다.
- 제외된 대출잔액과 제외 사유를 별도로 집계한다.
- 결과를 은행 전체 자산군의 공식 공시값으로 표시하지 않는다.
- 일반적인 총부채(total liabilities)와 구분되는 PCAF 방법론상 정의된 `total_debt`를 사용한다.
- 귀속계수가 1을 초과하면 임의로 1로 자르지 않고 데이터와 금융구조를 검토한다.
- 동일 익스포저 중복, 동일 차주의 복수 대출, 공동대출 여부를 검증한다.

포트폴리오 합계:

```text
지원 기업대출 포트폴리오 금융배출량
= Σ 차주별 금융배출량
```

데이터 품질 가중평균:

```text
포트폴리오 가중 데이터 품질 점수
= Σ(차주별 품질점수 × 차주별 대출잔액) / Σ 차주별 대출잔액
```

배출량이 아니라 대출잔액으로 가중한다.

### 8.5 산정 스냅숏과 재산정

- 산정 실행 시 익스포저, 재무정보, 차주 인벤토리, 환율, 배출계수, GWP, 방법론 버전을 하나의 입력 스냅숏으로 고정한다.
- 승인된 결과는 원본 입력이 수정돼도 덮어쓰지 않는다.
- 수정 계산은 새 버전을 생성하고 이전 결과를 `superseded`로 연결한다.
- 기준연도 재산정은 승인된 `recalculation_policy`와 중요성 임계치를 적용한다.
- 이전 결과, 재산정 결과, 촉발 사유, 승인자를 감사기록에 남긴다.

---

## 9. 기업대출 공식의 파라미터화 설계

### 9.1 공통 공식

지원 자산군 안에서는 계산구조를 하나로 고정하고 차주별 입력값만 교체한다.

```text
IF denominator <= 0:
    계산 중단
    calculation_status = review_required
    calculation_status_reason = non_positive_denominator
    attribution_factor·financed_emissions = null
ELSE:
    귀속계수 = outstanding_amount / denominator
    금융배출량 = 귀속계수 × borrower_emissions
```

비상장기업의 분모:

```text
denominator = total_equity + total_debt
```

### 9.2 계산 입력 계약

```text
exposure_id
external_exposure_id
company_id
asset_class
company_type
loan_purpose
outstanding_amount
exposure_currency
reporting_date
total_equity
total_debt
financial_currency
financial_year
debt_definition
financial_consolidation_scope
emissions_boundary_id
borrower_scope_1_2
borrower_scope_3
scope3_status
emissions_year
fx_rate
fx_rate_date
fx_rate_source
quality_score_scope_1_2
quality_score_scope_3
```

### 9.3 계산 결과 계약

```text
denominator
attribution_factor
financed_scope_1_2
financed_scope_3
total_financed_emissions
calculation_status
calculation_status_reason
quality_score_scope_1_2
quality_score_scope_3
methodology_version
assumptions
warnings
```

### 9.4 구현 인터페이스

```python
class BusinessLoanInput:
    outstanding_amount: Decimal
    total_equity: Decimal
    total_debt: Decimal
    borrower_scope_1_2: Decimal
    borrower_scope_3: Decimal | None
    scope3_status: str
    financial_consolidation_scope: str
    emissions_boundary_id: int


def calculate_private_business_loan(input: BusinessLoanInput) -> Result:
    denominator = input.total_equity + input.total_debt
    if denominator <= Decimal("0"):
        return Result(
            denominator=denominator,
            attribution_factor=None,
            financed_scope_1_2=None,
            financed_scope_3=None,
            calculation_status="review_required",
            calculation_status_reason="non_positive_denominator",
        )

    attribution_factor = input.outstanding_amount / denominator
    return Result(
        denominator=denominator,
        attribution_factor=attribution_factor,
        financed_scope_1_2=attribution_factor * input.borrower_scope_1_2,
        financed_scope_3=(
            attribution_factor * input.borrower_scope_3
            if input.borrower_scope_3 is not None
            else None
        ),
        calculation_status="calculated",
        calculation_status_reason=None,
    )
```

통화 변환, 일반 입력 검증, 반올림은 계산 함수 바깥의 전처리·출력 계층에서 명시적으로 수행한다. 다만 `denominator > 0`은 0 나눗셈과 잘못된 음수 귀속을 막는 계산 불변조건이므로 계산 함수 안에서도 반드시 재검증한다. 내부 계산은 충분한 정밀도의 `Decimal`을 사용한다.

전처리 계층은 다음을 통과한 입력만 계산 함수에 전달한다.

- 지원 자산군·기업유형·대출목적
- 익스포저 중복검사
- PCAF debt 정의 확인
- 통화변환과 환율 출처 확인
- 보고 기준일·재무연도·배출량연도 검사
- 재무 연결범위와 배출량 조직경계 정합성
- Scope 3 상태와 값의 일관성

### 9.5 확장 경계

다음 조건에서는 변수만 바꿔 계산하지 않는다.

- 상장기업: EVIC 분모 전략 필요
- 특정 목적 대출: 프로젝트·부동산·차량 등 해당 자산군 판정 필요
- 유동화상품: 기초자산과 구조화상품 방법론 필요
- 국채·지방정부채: 별도 분모와 배출량 기준 필요

미지원 사례는 `unsupported_methodology`로 반환한다. 향후 자산군은 공통 인터페이스 아래 별도 방법론 모듈로 추가한다.

---

## 10. API 변경

### 10.0 금융기관·포트폴리오

```text
POST /financial-institutions/{institution_id}/portfolios
GET  /financial-institutions/{institution_id}/portfolios/{portfolio_id}
POST /portfolios/{portfolio_id}/fx-rates
POST /financial-institutions/{institution_id}/recalculation-policies
POST /portfolios/{portfolio_id}/recalculation-events
```

모든 API는 인증 사용자의 `financial_institution_id`와 대상 리소스의 소유기관이 일치하는지 검사한다.

### 10.1 차주 배출량

```text
GET  /borrowers/{company_id}/emission-inventories/{year}
POST /borrowers/{company_id}/emission-inventories/{year}/calculate
GET  /borrowers/{company_id}/emission-inventories/{year}/sources
```

### 10.2 품질평가

```text
GET  /borrowers/{company_id}/quality-assessments/{year}
POST /borrowers/{company_id}/quality-assessments/{year}/evaluate
```

### 10.3 내보내기

```text
GET /borrowers/{company_id}/exports/{year}.json
GET /borrowers/{company_id}/exports/{year}.xlsx
```

### 10.4 기업대출 익스포저와 금융배출량

```text
POST /portfolios/{portfolio_id}/business-loan-exposures
POST /portfolios/{portfolio_id}/asset-class-summaries
POST /portfolios/{portfolio_id}/financed-emissions/calculate
GET  /portfolios/{portfolio_id}/financed-emissions
GET  /portfolios/{portfolio_id}/financed-emissions/coverage
GET  /portfolios/{portfolio_id}/data-quality
```

`asset-class-summaries`는 미지원 자산군의 외부 계산 결과를 전체 DCL 범위검사용으로 적재하며, 감탄 계산 결과와 API 응답에서 명확히 구분한다.

### 10.5 PCAF 체크리스트

```text
POST /portfolios/{portfolio_id}/pcaf-checklists/run
POST /portfolios/{portfolio_id}/disclosure-documents
GET  /portfolios/{portfolio_id}/pcaf-checklists/{run_id}
GET  /portfolios/{portfolio_id}/pcaf-checklists/{run_id}/items/{item_code}
POST /portfolios/{portfolio_id}/pcaf-checklists/{run_id}/items/{item_code}/ai-review
PATCH /portfolios/{portfolio_id}/pcaf-checklists/{run_id}/items/{item_code}/approve
GET  /portfolios/{portfolio_id}/pcaf-checklists/{run_id}/export.xlsx
```

AI 검토 API는 규칙 엔진의 판정값을 변경하지 않는다. 증빙 후보, 설명의 부족한 부분, 보완문구 초안만 결과에 추가한다.

체크리스트 실행 요청에는 `mode`가 필수다.

```json
{
  "mode": "business_loans_readiness",
  "checklist_version": "pcaf-part-a-third-edition-2025-12-internal"
}
```

`full_pcaf_dcl` 모드는 전체 관련 자산군과 잔액을 검증한 뒤 실행한다. 범위가 부족하면 HTTP 성공 응답 안에 `status=insufficient_scope`와 부족한 자산군·데이터 목록을 반환하며 체크리스트를 통과 처리하지 않는다.

내보내기 파일명과 표지는 모드별로 구분한다.

```text
business-loans-readiness-YYYY.xlsx
full-pcaf-dcl-review-support-YYYY.xlsx
```

내부 준비도 파일에는 `PCAF 공식 제출양식 또는 assurance가 아님`을 표시한다.

기존 `/pcaf/{company_id}`는 즉시 삭제하지 않고 한 차례 호환 응답을 제공한 뒤 폐기한다.

---

## 11. 화면 변경

### 11.1 차주 화면

표시 항목:

- 보고연도
- Scope 1, Scope 2, 총배출량
- 산정된 배출원과 미산정 배출원
- 실제·추정·산업평균 구성비
- 데이터 완전성
- PCAF 데이터 품질 후보
- 후보 판정근거
- 제한사항
- 추가로 제출하면 개선되는 자료

예시:

```text
PCAF 데이터 품질 후보: Score 3
실제 활동자료 기반: 78%
금액 환산자료: 12%
산업평균 추정: 10%
완전성: 82.5%

제한사항
- 공정배출 미확인
- 냉매배출 미확인
- Scope 3 미산정
- 제3자 검증 없음
```

### 11.2 은행 관리자 화면

- 등록 차주 수
- 연간 인벤토리 완료 차주 수
- 실제 활동자료 비율
- 품질 후보 분포
- 검토대기 차주
- 증빙 누락 현황
- 미산정 배출원
- Scope 3 상태별 차주 수
- 조직경계·재무 연결범위 불일치
- 환율·기준일 경고
- 기업대출 준비도와 전체 DCL 모드 구분

은행 대출잔액이 연결되지 않았다면 포트폴리오 PCAF 가중점수를 표시하지 않는다.

### 11.3 기업대출 금융배출량 화면

- 대출잔액
- 총자본·PCAF debt
- 귀속계수
- 차주 배출량
- 차주별 금융배출량
- 지원 기업대출 포트폴리오 합계
- 대출잔액 기준 가중 데이터 품질 점수
- 포함·제외 대출잔액과 사유
- 입력 시점 차이 경고
- 지원 자산군 범위 표시
- Scope 3 미산정은 0이 아닌 미산정 상태로 표시
- Scope 2 location-based와 market-based 구분
- 귀속계수 100% 초과·기준일 불일치·조직경계 불일치 경고

---

## 12. 은행 전달용 데이터 패키지

### 12.1 JSON 필수 필드

```text
borrower_identifier
reporting_year
organizational_boundary
scope_1_tco2e
scope_2_tco2e
scope_3_status
scope_2_location_based_tco2e
scope_2_market_based_tco2e
gas_coverage
calculation_methods
data_quality_candidate
quality_rule
completeness
verification_status
emission_factors
gwp_version
limitations
evidence_references
organizational_boundary
financial_consolidation_scope
fx_rate_snapshot
calculation_snapshot_hash
```

### 12.2 Excel 시트

1. 차주 기본정보
2. 연간 Scope 1·2 인벤토리
3. 활동자료 목록
4. 배출계수와 GWP
5. 데이터 품질 후보
6. 완전성 및 제한사항
7. 증빙자료 목록
8. 기업대출 금융배출량 산정
9. 조직경계·재무 연결범위
10. 통화·환율·기준일
11. 재산정 정책과 이력
12. 체크리스트 준비도 결과

---

## 13. 파일별 예상 변경

### 백엔드

- `db/models.py`: 신규 테이블과 필드
- `alembic/`: 운영 가능한 스키마 마이그레이션 신규 도입
- `db/init_db.py`: 신규 설치용 초기화만 담당하도록 축소
- `db/calc_engine.py`: 산정방법, 계수 버전, 가스별 결과
- `db/pcaf.py`: 임시 점수 제거, 호환 래퍼로 축소
- `db/borrower_inventory.py`: 연간 인벤토리 신규
- `db/pcaf_quality.py`: 품질 후보 평가 신규
- `db/financed_emissions.py`: 기업대출 귀속계수·금융배출량·포트폴리오 집계 신규
- `db/portfolio.py`: 금융기관·포트폴리오·외부 자산군 요약 관리
- `db/pcaf_checklist.py`: 체크리스트 규칙 판정과 결과 저장 신규
- `db/security.py`: 기관별 접근권한과 리소스 소유권 검사
- `db/recalculation.py`: 기준연도 재산정 정책·이벤트 처리
- `db/fx.py`: 환율정책·환산·스냅숏 처리
- `api/routers/borrower_emissions.py`: 인벤토리 API
- `api/routers/quality.py`: 품질평가 API
- `api/routers/exports.py`: JSON·Excel 내보내기
- `api/routers/financed_emissions.py`: 익스포저·산정·커버리지 API
- `api/routers/portfolios.py`: 포트폴리오·외부 자산군 요약 API
- `api/routers/pcaf_checklist.py`: 실행·검토·승인·내보내기 API
- `api/routers/disclosure_documents.py`: 공시문서 적재·페이지 증빙 API
- `api/agent/orchestrator.py`: 도구명과 트레이스 문구 변경
- `api/agent/tools.py`: 체크리스트 실행·증빙 검색·보완문구 작성 도구
- `api/agent/pcaf_evidence.py`: 보고서 증빙 검색과 구조화된 AI 출력

### 프론트엔드

- `web/components/ScenePcaf.tsx`: 품질 후보 화면으로 개편
- `web/components/admin/DashboardShell.tsx`: 차주 데이터 현황
- `web/components/admin/GradeDonut.tsx`: 후보 점수 분포
- `web/components/LiveTraceFeed.tsx`: 도구명 정정
- `web/components/admin/PcafChecklistWorkspace.tsx`: 항목별 판정·증빙·승인 화면
- `web/lib/api.ts`: 신규 API 타입과 호출

### 문서와 테스트

- `docs/db-schema.md`: 신규 스키마
- `docs/pcaf-plan.md`: 과거 MVP 구현계획으로 명시하고 신규 설계 링크 추가
- `docs/v1-plan.md`: 정본 설계를 2026년 8월 실행순서·담당·완료조건으로 구체화
- `docs/demo-plan.md`: 화면명·품질 후보·금융배출량·우대금리 표현 수정
- `docs/db-schema.md`: 현행 AS-IS와 목표 TO-BE 설계 구분
- `CLAUDE.md`: 기존 임시 PCAF 등급·전표 실측·우대금리·금융배출량 정의 교체
- `README.md`: 제품 정의와 지원 자산군·제외 범위 수정
- `tests/test_calc_engine.py`: 활동자료 방법별 테스트
- `tests/test_borrower_inventory.py`: 연간 집계
- `tests/test_pcaf_quality.py`: 후보 규칙
- `tests/test_financed_emissions.py`: 기업대출 산정과 포트폴리오 합계
- `tests/test_pcaf_checklist.py`: 규칙 판정과 상태 변환
- `tests/test_pcaf_checklist_ai.py`: AI가 판정값을 변경하지 않는 계약
- `tests/test_tenant_security.py`: 기관 간 데이터 격리
- `tests/test_recalculation.py`: 기준연도 재산정과 버전 보존
- `tests/test_fx.py`: 환율·기준일·출처 검증
- `tests/test_migrations.py`: Alembic 업·다운 및 데이터 보존
- `tests/test_exports.py`: JSON·Excel 필수 필드

---

## 14. 테스트 계획

### 14.1 활동자료 계산

- 실제 kWh, L, Nm3
- 구매금액 기반 환산
- 단위 불일치
- 배출계수 미등록
- 중복 문서
- 정정·음수 전표
- 7대 가스별 값·미확인 상태
- Scope 2 location-based와 market-based
- REC·PPA 등 계약수단 근거

### 14.2 연간 인벤토리

- 12개월 완전 데이터
- 결손월
- 일부 사업장 제외
- Scope별 합계
- 실제·추정 구성비
- 동일 문서 중복 제외
- Scope 3 `null + 상태` 처리
- 조직경계 버전과 포함 법인
- 승인 결과 수정 시 새 버전 생성

### 14.3 품질 후보

- 검증된 차주 보고 배출량
- 미검증 차주 보고 배출량
- 물리적 활동자료 기반 계산
- 경제활동자료 기반 추정
- 산업평균 추정
- 혼합 데이터
- HITL 상태와 품질점수 분리
- Scope 1·2와 Scope 3 분리

### 14.4 기업대출 금융배출량 산정

- 정상 비상장기업
- 분모 0 또는 음수
- 통화 불일치
- 기준일 불일치
- 결과 재현성
- 입력 없는 경우 미계산
- 여러 차주의 포트폴리오 합계
- 대출잔액 기준 품질점수 가중평균
- 미지원 대출 목적 제외
- 제외 잔액과 사유 집계
- 일반적인 총부채와 PCAF debt 정의 혼용 차단
- 조직경계와 재무 연결범위 불일치
- 동일 익스포저 중복 차단
- 동일 차주의 복수 대출 합산
- 공동대출 경고
- 귀속계수 100% 초과 시 검토 전환
- Scope 3 미산정을 0으로 합산하지 않음
- Scope 2 방식별 금융배출량

### 14.5 회귀 테스트

- 전표 수집
- 룰·LLM 분류
- HITL
- 관리자 확정·반려
- 배출량 결정론적 계산
- 트레이스 로그

### 14.6 PCAF 체크리스트

- 필수 데이터 충족 시 `pass`
- 필수 데이터 누락 시 `fail`
- 서술 판단이 필요한 경우 `review_required`
- 비적용 사유가 있으면 `not_applicable`
- `not_applicable`의 제출 변환은 `No + non-applicable`
- Scope 1·2와 Scope 3 데이터 품질 점수 분리 검사
- 커버리지 분모·분자 및 제외 사유 검사
- 기준연도 재산정 정책과 중요성 임계치 검사
- 회피배출·제거·탄소배출권 분리 검사
- AI 검토 전후에 규칙 엔진 판정값 불변
- 담당자 승인 전 `review_required` 항목 제출 차단
- 규칙 버전이 바뀌어도 과거 실행 결과 재현
- 2025년 5월 DCL과 제3판 내부 체크리스트 혼용 방지
- 기업대출 준비도 모드와 전체 DCL 모드 분리
- 전체 자산군 데이터 부족 시 `insufficient_scope`
- 외부 자산군 요약이 모두 검토된 경우에만 전체 DCL 범위검사 통과
- 외부 자산군 요약과 감탄 계산 결과의 출처 구분
- 내부 준비도 출력물의 비공식 고지
- 공시문서 증빙의 페이지 번호 보존

### 14.7 보안·버전·마이그레이션

- 다른 금융기관 사용자의 포트폴리오 접근 차단
- 역할별 읽기·검토·승인 권한
- 원본 문서 다운로드 감사로그
- AI 전달 전 민감정보 마스킹
- 승인된 산정 스냅숏 불변성
- 재산정 전후 결과 연결
- 환율 기준일·출처 재현
- Alembic 신규 설치·업그레이드·롤백
- 마이그레이션 중 기존 전표·분류 결과 보존

---

## 15. 단계별 실행 순서와 완료조건

### Phase 0. 문서 정합성 및 표현 리스크 제거

작업:

- 이 문서를 PCAF 제품·기술 설계의 정본으로 지정
- 기존 문서의 역할을 정본·현행설명·과거기록으로 분류
- `CLAUDE.md`의 제품 정의와 개발지침 동기화
- `docs/pcaf-plan.md`에 과거 MVP 구현계획 및 신규 개발 사용 금지 표시
- `docs/demo-plan.md`의 데모 장면과 문구 동기화
- `docs/db-schema.md`에 현행 AS-IS 표시와 목표 설계 링크 추가
- `README.md`의 제품 정의와 지원범위 동기화
- PCAF 공식 등급처럼 보이는 문구 수정
- 금융배출량 오표기 수정
- 우대금리 직접 연결 제거
- 저장소 전체에서 충돌 용어 검색 및 잔여 항목 검토

완료조건:

- 모든 개발 문서가 이 계획서를 PCAF 설계 정본으로 참조한다.
- 과거 계획은 현재 요구사항처럼 읽히지 않도록 상태와 날짜가 표시된다.
- 자체 Scope 1·2와 금융배출량이 명확히 구분된다.
- 모든 후보 점수에 은행 검토 필요 문구가 있다.
- `PCAF 2등급 확정`, `전표 기반 실측`, `PCAF 등급 우대금리`, `대출정보 없는 금융배출량` 표현이 활성 문서에 남아 있지 않는다.

### Phase 1. 데이터 기반 구축

작업:

- 금융기관·사용자·포트폴리오·익스포저 데이터 모델
- 조직경계·차주 재무정보·환율·재산정 데이터 모델
- 인벤토리·가스별 배출량·산정 스냅숏 데이터 모델
- 문서, 인벤토리, 품질규칙 테이블 추가
- Alembic 도입, 마이그레이션과 규칙 시드

완료조건:

- 배출량 결과에서 원본 문서·배출계수·GWP·조직경계·환율·재무정보까지 역추적할 수 있다.
- 금융기관별 데이터가 논리적으로 격리되고 포트폴리오 ID가 실제 테이블과 연결된다.

### Phase 2. 계산과 인벤토리

작업:

- 활동자료 방법 구분
- 7대 가스별·CO2e 계산과 미확인 상태
- Scope 2 location-based·market-based 구분
- 연간 Scope 1·2 집계
- Scope 3 상태모델
- 완전성 평가

완료조건:

- 기업·연도·Scope별 인벤토리가 재현 가능하게 생성된다.
- 미산정 Scope와 가스를 0으로 오인하지 않는다.

### Phase 3. PCAF 품질 후보

작업:

- Business Loans 품질규칙 구현
- 후보 점수, 근거, 제한사항 출력
- 기존 임시 등급 제거

완료조건:

- 모든 후보 점수에 적용 규칙과 증빙 근거가 있다.
- LLM confidence와 PCAF 품질 후보가 완전히 분리된다.

### Phase 4. 화면과 전달 포맷

작업:

- 차주·관리자 화면 개편
- JSON·Excel 내보내기

완료조건:

- 은행이 감탄 UI 없이도 차주 데이터를 자체 PCAF 시스템에 입력할 수 있다.

### Phase 5. 기업대출 금융배출량 산정

작업:

- 기업대출 입력 계약과 산정 인터페이스
- 차주별 귀속계수와 금융배출량 계산
- 지원 차주 결과 합산
- 대출잔액 기준 품질점수 가중평균
- 포함·제외 잔액과 경고 표시
- 통화·기준일·조직경계·debt 정의 검증
- 중복·복수대출·귀속계수 이상값 처리

완료조건:

- 대출잔액·총자본·PCAF debt가 있는 지원 대상 차주만 결과가 생성된다.
- 계산식, 입력값, 중간값, 제한사항이 모두 표시된다.
- 감탄에 등록된 지원 기업대출 포트폴리오 합계가 차주별 결과의 합과 일치한다.
- 승인 결과의 입력 스냅숏을 재현할 수 있다.

### Phase 6. PCAF 체크리스트 자동화

작업:

- 결정론적 체크리스트 규칙 엔진
- 기업대출 준비도와 전체 DCL 모드 분리
- 전체 범위 충족 여부 사전검사
- AI 증빙 검색·설명 검토·보완문구 도구
- 담당자 승인 워크플로
- DCL Excel 내보내기
- 체크리스트 버전 관리

완료조건:

- 모든 자동판정 항목에 규칙 버전과 데이터 증빙이 있다.
- AI는 판정값을 수정할 수 없고, 설명과 증빙 후보만 추가한다.
- 검토필요 항목은 담당자 승인 전 제출할 수 없다.
- 평가 결과에서 Yes/No의 근거를 재현할 수 있다.
- 미지원 자산군 데이터가 없으면 전체 DCL을 통과시키지 않는다.

### Phase 7. 보안·권한·재산정

작업:

- 금융기관 tenant 격리와 역할 기반 접근제어
- 원본 문서 암호화·마스킹·다운로드 감사로그
- AI 입력 최소화와 민감정보 제거
- 산정 스냅숏과 승인 결과 불변성
- 기준연도 재산정 정책과 이벤트

완료조건:

- 다른 금융기관 데이터에 접근할 수 없다.
- AI에는 작업에 필요한 최소 정보만 전달된다.
- 승인된 결과를 수정하면 새 버전과 재산정 이력이 생성된다.

### Phase 8. 검증과 문서화

작업:

- 단위·통합·회귀 테스트
- API 및 데이터 사전
- 시연 시나리오

완료조건:

- 동일 입력과 동일 규칙 버전에서 동일 결과를 재현한다.
- 기존 분류·HITL 흐름이 깨지지 않는다.

---

## 16. 최종 완료 정의

다음 조건을 모두 충족하면 제품 전환이 완료된 것으로 본다.

1. 감탄 결과가 차주 자체 배출량인지 금융배출량인지 명확히 구분된다.
2. 실제 사용량, 금액 환산, 경제활동 추정, 산업평균을 구분한다.
3. 기업·보고연도별 Scope 1·2 인벤토리를 생성한다.
4. 조직경계, 산정범위, 결손, 제한사항을 제공한다.
5. PCAF 품질 후보는 Business Loans 규칙과 근거를 갖는다.
6. LLM 신뢰도와 PCAF 품질 후보가 분리된다.
7. 품질 후보를 공식 등급 또는 우대금리 자격으로 표현하지 않는다.
8. 은행 전달용 JSON·Excel을 생성한다.
9. 기업대출 금융배출량은 지원 조건과 필수 입력을 충족할 때만 계산한다.
10. 모든 결과가 원본 문서, 배출계수, 규칙 버전까지 추적 가능하다.
11. 지원 기업대출 포트폴리오 합계가 차주별 결과의 합과 일치한다.
12. 데이터 품질 가중평균은 대출잔액을 기준으로 계산한다.
13. 체크리스트의 자동판정은 결정론적 규칙 엔진이 수행한다.
14. AI는 증빙 검색·서술 검토·보완문구 작성만 담당한다.
15. 검토필요 항목은 은행 담당자가 최종 승인한다.
16. 모든 체크리스트 결과에 표준·체크리스트·규칙 버전이 기록된다.
17. 활성 문서가 동일한 제품 범위·용어·산정책임을 설명한다.
18. 과거 문서는 폐기 또는 기록 상태가 명확히 표시된다.
19. 기업대출 준비도와 은행 전체 DCL 검토가 구분된다.
20. 전체 관련 자산군 데이터가 없으면 전체 DCL은 `insufficient_scope`로 중단된다.
21. 금융기관·포트폴리오·익스포저 관계가 데이터 모델에 존재한다.
22. Scope 3 미산정과 미확인 온실가스를 0으로 처리하지 않는다.
23. Scope 2 location-based와 market-based가 구분된다.
24. 조직경계·재무 연결범위·통화·기준일·debt 정의가 검증된다.
25. 귀속계수 이상값과 익스포저 중복은 자동 통과하지 않는다.
26. 기준연도 재산정 정책과 이전·이후 결과가 보존된다.
27. 승인된 결과의 입력 스냅숏과 방법론 버전을 재현할 수 있다.
28. 금융기관 간 데이터 격리와 역할 기반 승인이 적용된다.
29. 스키마 변경은 Alembic 마이그레이션으로 관리된다.

---

## 17. 향후 확장

기업대출 방법론과 은행 데이터 연동이 검증된 뒤에만 다음을 검토한다.

1. 상장기업 기업대출의 EVIC 분모 전략
2. Scope 3 수집·추정
3. 미지원 자산군을 포함한 은행 전체 포트폴리오 가중 데이터 품질
4. 미지원 자산군을 포함한 은행 전체 포트폴리오 커버리지
5. 상업용 부동산·프로젝트 파이낸스 등 추가 자산군
6. 향후 공식 제3판 DCL 발행 시 제출양식과 규칙 업데이트

---

## 18. PCAF 체크리스트 자동화 상세 설계

### 18.1 설계 원칙

체크리스트 판정은 다음 책임 분리를 따른다.

| 주체 | 책임 |
|---|---|
| 결정론적 코드 | 정형 데이터 조건 검사, 상태 판정, 제출 차단 |
| AI | 보고서 증빙 검색, 설명 충분성 검토, 불일치 탐지, 보완문구 초안 |
| 은행 담당자 | `review_required`와 비적용 항목의 최종 승인 |

AI가 단독으로 `Yes/No`를 결정하거나 코드의 `pass/fail` 값을 수정할 수 없도록 한다.

### 18.2 내부 판정 상태

```text
pass
  필수 데이터와 증빙 조건을 모두 충족

fail
  필수 데이터 또는 조건이 명확하게 누락

review_required
  설명의 충분성, 공시 문맥, 적용범위 등 사람 판단 필요

not_applicable
  해당 활동이 없고 비적용 사유가 기록됨

insufficient_scope
  전체 DCL 판정에 필요한 자산군·포트폴리오 데이터가 부족함
```

제출용 변환:

| 내부 상태 | 제출 답변 |
|---|---|
| `pass` | Yes |
| `fail` | No + 실패·제외 사유 |
| `review_required` | 담당자 승인 전 미확정 |
| `not_applicable` | No + `non-applicable` |
| `insufficient_scope` | 제출 변환 금지 |

### 18.3 자동판정 대상

다음 항목은 코드가 데이터베이스와 계산 결과를 이용해 판정한다.

`business_loans_readiness`에서는 아래 항목 중 기업대출 지원범위에 해당하는 조건만 판정한다. `full_pcaf_dcl`에서는 먼저 은행의 전체 관련 자산군과 총 대출·투자잔액이 제공됐는지 검사하고, 부족하면 후속 항목을 통과시키지 않는다.

#### 포트폴리오 커버리지

- 전체 관련 기업대출잔액 존재
- 산정에 포함된 기업대출잔액 존재
- 커버리지 비율 계산
- 제외 익스포저와 제외 사유 기록
- 미지원 자산군이 지원 포트폴리오에 혼입되지 않았는지 검사

```text
coverage_pct
= included_outstanding_amount / total_relevant_outstanding_amount × 100
```

#### 절대 금융배출량

- Scope 1·2 금융배출량 존재
- Scope 3 상태와 배출량 존재 여부
- Scope 1·2와 Scope 3 분리
- 산업·자산군별 집계
- 단위 tCO2e
- 계산 방법론 버전 기록

#### 데이터 품질

- Scope 1·2 후보 점수 존재
- Scope 3 점수 별도 존재 여부
- 대출잔액 가중평균 사용
- 각 점수의 적용 규칙과 근거 존재

#### 기준연도와 재산정

- 기준연도 등록
- 재산정 정책 등록
- 중요성 임계치 등록
- 재산정 실행 이력 보존

#### 회피배출·제거·탄소배출권

- 금융배출량에서 탄소배출권을 차감하지 않음
- 회피배출과 제거량을 Scope 1·2·3 인벤토리와 분리
- 관련 값을 보고한 경우 방법론과 근거 존재

### 18.4 부분 자동판정 대상

다음 항목은 코드가 기본 조건을 검사하고 AI와 담당자가 서술을 검토한다.

- 제외 사유가 충분히 구체적인가
- 보고서의 조직경계 설명이 데이터 범위와 일치하는가
- 변동분석이 주요 증감 원인을 설명하는가
- 데이터 한계와 개선계획이 구체적인가
- 공시 문구와 시스템 계산값이 일치하는가

코드는 문서 존재, 필수 필드, 수치 일치 여부를 검사한다. AI는 문장 의미와 설명의 충분성을 검토하고 `ai_comment`를 추가한다. 최종 상태 변경은 담당자 승인 API만 허용한다.

### 18.5 AI 도구 계약

AI 에이전트에 다음 도구를 제공한다.

```text
run_pcaf_checklist(portfolio_id, reporting_year, checklist_version)
get_checklist_item(run_id, item_code)
get_calculation_evidence(run_id, item_code)
search_disclosure_evidence(run_id, item_code, document_id)
compare_disclosure_value(run_id, item_code, document_id)
draft_checklist_justification(run_id, item_code)
request_human_review(run_id, item_code, reason)
```

AI 도구 출력은 구조화한다.

```json
{
  "item_code": "COVERAGE-02",
  "evidence_candidates": [
    {
      "document_id": 12,
      "page": 34,
      "summary": "기업대출 커버리지 72.4%를 설명"
    }
  ],
  "consistency": "mismatch",
  "system_value": 72.4,
  "document_value": 80.0,
  "missing_explanation": [
    "제외 대출잔액",
    "제외 사유"
  ],
  "suggested_comment": "...",
  "requires_human_review": true
}
```

AI 출력에는 최종 `pass/fail` 필드를 허용하지 않는다.

### 18.6 버전 관리

현재 확보한 문서에는 시점 차이가 있다.

- `pcaf-dcl-2025-05`: 2025년 5월 Disclosure Checklist 원문
- `pcaf-part-a-third-edition-2025-12`: 2025년 12월 제3판 Chapter 6 기반 내부 체크리스트

두 규칙 세트를 혼용하지 않는다. 모든 실행 결과에 다음을 기록한다.

```text
checklist_version
standard_version
rule_version
methodology_version
```

초기 구현은 제3판 Chapter 6 기반 내부 체크리스트를 기본으로 한다. 2025년 5월 DCL은 원문 제출양식 참고와 과거 비교를 위해 별도 보존한다. PCAF가 제3판용 공식 DCL을 배포하면 새 버전 규칙을 추가하고 기존 실행 결과는 그대로 유지한다.

제3판 Chapter 6 기반 내부 결과의 공식 명칭은 `PCAF Part A Third Edition Readiness Assessment`로 한다. `Disclosure Checklist`, `DCL`, `PCAF approved`, `assured`라는 표현을 내부 준비도 결과에 사용하지 않는다.

### 18.7 AI 처리 실패 원칙

- AI 호출 실패가 체크리스트 코드 판정을 변경하지 않는다.
- AI 실패 시 해당 항목은 기존 `pass/fail` 또는 `review_required`를 유지한다.
- 문서 검토가 필요한 항목은 AI 실패 시 자동 통과시키지 않는다.
- 오류 유형과 재시도 이력을 저장한다.
- 최종 제출은 담당자 승인 없이 진행하지 않는다.

### 18.8 체크리스트 완료조건

1. 동일 데이터와 동일 규칙 버전에서 동일 판정이 나온다.
2. 모든 판정에 사용 데이터와 규칙 근거가 있다.
3. AI 호출 여부와 무관하게 코드 판정이 재현된다.
4. AI는 판정값을 수정할 권한이 없다.
5. 보고서 수치와 시스템 수치 불일치를 탐지한다.
6. `review_required` 항목은 담당자 승인 전 내보내기를 차단한다.
7. 승인·반려·수정 이력이 감사로그에 남는다.
8. 체크리스트 버전 간 규칙과 결과가 분리된다.
9. 기업대출 준비도 결과를 은행 전체 DCL 통과로 표시하지 않는다.
10. 전체 범위 데이터가 부족하면 `insufficient_scope`로 종료한다.
11. 내부 준비도 출력물에 비공식·비보증 고지가 표시된다.

---

## 19. 문서 정합성 관리 계획

### 19.1 문서 우선순위

PCAF 관련 내용이 충돌하면 다음 우선순위를 적용한다.

1. `docs/borrower-pcaf-data-plan.md`: 제품 범위와 TO-BE 기술설계 정본
2. `CLAUDE.md`: 현재 개발 원칙과 실행지침
3. `docs/v1-plan.md`: 정본을 기반으로 한 현재 v1 실행계획
4. `docs/db-schema.md`: 현재 구현된 AS-IS 데이터 구조
5. `docs/demo-plan.md`: 정본을 기반으로 한 시연 범위
6. `docs/pcaf-plan.md`: 과거 MVP 구현기록

하위 문서가 상위 문서의 제품 정의를 재정의하지 못한다.

### 19.2 문서별 수정계획

#### `CLAUDE.md`

- `계산·PCAF 등급`을 `차주 배출량·PCAF 품질 후보`로 변경
- 매출추정 5등급 대 전표 실측 2~3등급 구도 제거
- 사용량 기반 산정과 금액 환산 추정 구분
- 차주 자체 Scope 1·2와 은행 금융배출량 구분
- 기업대출 금융배출량의 지원 조건과 입력 명시
- 데이터 품질 후보와 우대금리 직접 연결 제거
- 체크리스트는 코드 판정, AI 보조, 담당자 승인 구조로 변경
- 기존 데모 장면과 도구 이름 갱신

#### `docs/pcaf-plan.md`

- 문서 상단에 작성일과 `과거 MVP 구현계획` 상태 표시
- 현재 PCAF 요구사항이나 신규 구현지침으로 사용하지 않는다고 명시
- 임시 등급 규칙이 공식 PCAF 규칙이 아님을 표시
- 새 정본 계획서 링크 추가
- 구현 당시의 역사적 맥락은 보존하고 신규 설계로 조용히 덮어쓰지 않음

#### `docs/v1-plan.md`

- 정본 설계에서 v1에 실제 구현할 범위만 추출
- `business_loans_readiness`까지만 v1 범위로 고정
- 완료된 이상신호 알림은 유지하고 중복 구현하지 않음
- 기존 PCAF 등급 상승 역산을 누락자료·완전성 개선 안내로 교체
- 주차별 담당·검증·완료조건을 정본 용어와 일치시킴
- 기준 브랜치와 pull 기준 커밋을 기록

#### `docs/demo-plan.md`

- `PCAF Before/After` 장면을 `차주 배출량 데이터 개선` 장면으로 변경
- 전표 기반 결과 전체를 실측이라고 부르지 않음
- 공식 PCAF 등급처럼 보이는 정수 표현 제거
- 단일 기업대출 금융배출량 또는 지원 포트폴리오 합계의 입력 조건 표시
- 우대금리 자동대상 문구 제거
- 체크리스트 자동점검과 담당자 승인 장면 추가 여부 결정

#### `docs/db-schema.md`

- 현재 스키마가 AS-IS임을 문서 상단에 표시
- `db/models.py`가 현재 구현 정본임을 유지
- TO-BE 스키마는 이 계획서의 데이터 모델 절을 참조하도록 연결
- 실제 마이그레이션 완료 후에만 신규 테이블을 현행 스키마로 반영
- 계획과 구현을 한 문서에서 혼합하지 않음

#### `README.md`

- 감탄의 한 문장 제품 정의 추가
- 지원 자산군과 대상 차주 표시
- 공식 은행 전체 PCAF 공시 시스템이 아니라는 경계 명시
- 주요 문서와 실행방법 링크 정리

### 19.3 문서 상태 표준

각 주요 문서 상단에 다음 메타데이터를 둔다.

```text
Status: authoritative | current-as-is | active-plan | historical | deprecated
Last updated: YYYY-MM-DD
Superseded by: 문서 경로 또는 없음
Scope: 문서가 책임지는 내용
```

권장 상태:

| 문서 | 상태 |
|---|---|
| `docs/borrower-pcaf-data-plan.md` | `authoritative` |
| `CLAUDE.md` | `current-as-is` |
| `docs/v1-plan.md` | `active-plan` |
| `docs/db-schema.md` | `current-as-is` |
| `docs/demo-plan.md` | `active-plan` |
| `docs/pcaf-plan.md` | `historical` |

### 19.4 충돌 검사

문서 수정 후 저장소 전체에서 다음 표현을 검색한다.

```text
PCAF 2등급
PCAF 3등급
전표 기반 실측
PCAF 우대금리
우대금리 대상
매출 추정 5등급
포트폴리오 금융배출량
PCAF 등급 산정기
```

검색 결과를 모두 기계적으로 삭제하지 않는다. 과거 기록 문서에서는 상태 표시와 주석으로 맥락을 보존할 수 있다. 활성 문서와 화면 문구에서는 새 정의와 충돌하는 표현을 제거한다.

### 19.5 문서 정합성 완료조건

1. PCAF 제품 범위의 정본이 하나다.
2. 문서마다 상태와 책임범위가 명확하다.
3. 현재 구현과 목표 설계가 혼합되지 않는다.
4. 공식 점수·실측·금융배출량·우대금리 용어가 일관된다.
5. 체크리스트 자동화에서 코드·AI·담당자 역할이 동일하게 설명된다.
6. 지원 기업대출 자산군과 미지원 자산군의 경계가 동일하다.
7. 과거 MVP 계획은 기록으로 보존되지만 신규 개발지침으로 오해되지 않는다.

---

## 20. 보안·개인정보·운영 설계

### 20.1 기관별 데이터 격리

- 모든 포트폴리오·익스포저·체크리스트·내보내기 요청은 금융기관 tenant에 귀속한다.
- API는 URL의 ID만 신뢰하지 않고 인증 사용자와 리소스의 `financial_institution_id`를 비교한다.
- 관리자도 명시적으로 허용된 기관 범위만 조회한다.
- 기관 간 데이터 격리 테스트를 필수 회귀테스트로 둔다.

### 20.2 역할 기반 권한

| 역할 | 권한 |
|---|---|
| `analyst` | 자료 입력·산정 실행 |
| `reviewer` | 결과·증빙 검토와 의견 |
| `approver` | 인벤토리·금융배출량·체크리스트 최종 승인 |
| `viewer` | 승인된 결과 읽기 |
| `admin` | 사용자·정책 관리, 승인권 자동 포함 금지 |

산정자와 승인자를 분리할 수 있도록 한다.

### 20.3 원본 문서 보호

- 홈택스 전표, 고지서, 재무자료, 대출잔액 원본은 저장 시 암호화한다.
- 파일 해시와 접근기록을 저장한다.
- 원본 다운로드는 별도 권한과 감사로그를 요구한다.
- 보존기간과 파기정책을 금융기관·차주 동의 범위에 맞춰 설정한다.
- 내보내기 파일에는 필요한 최소 데이터만 포함한다.

### 20.4 AI 데이터 최소화

- AI에는 체크리스트 항목 검토에 필요한 발췌문과 비식별 식별자만 전달한다.
- 사업자번호, 계좌, 대출계약번호, 개인식별정보는 마스킹한다.
- 원본 전체 문서를 기본적으로 외부 모델에 전송하지 않는다.
- AI 호출 입력·출력·모델·시각·사용목적을 감사로그에 남긴다.
- AI 실패 또는 사용 거부 시 결정론적 체크와 사람 검토만으로 진행할 수 있어야 한다.

### 20.5 스냅숏과 변경불가성

- 승인된 인벤토리와 금융배출량 결과는 수정하지 않는다.
- 입력 정정은 새 버전 산정과 `supersedes` 관계를 생성한다.
- 체크리스트는 특정 포트폴리오·인벤토리·산정 버전을 참조한다.
- 내보내기 파일에 스냅숏 해시와 생성시각을 포함한다.

### 20.6 마이그레이션

- 운영 스키마 변경은 Alembic revision으로 관리한다.
- `db/init_db.py`의 임의 DROP·ALTER에 운영 마이그레이션을 의존하지 않는다.
- 업그레이드 전 백업과 데이터 검증 절차를 둔다.
- 마이그레이션 테스트에서 기존 전표·분류·HITL·트레이스 데이터 보존을 확인한다.
- 파괴적 변경은 단계적 컬럼 추가, 백필, 읽기 전환, 구 컬럼 제거 순서로 수행한다.
