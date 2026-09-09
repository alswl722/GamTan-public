# 감탄 DB 스키마

> Supabase(PostgreSQL) · SQLAlchemy 직접 접속 · 정본: `db/models.py` · 마이그레이션: Alembic (`alembic/versions/`)
> 표기: **PK** 기본키 · **FK** 외래키 · **UQ** 유니크 · **IX** 인덱스 · **CK** CHECK 제약 · NN NOT NULL

이 문서는 두 세대의 스키마를 함께 담고 있다.

- **v0.1 코어 엔진 테이블** (§1~8) — 전표→탄소량 변환 파이프라인. 데모부터 지금까지 교체 없이 계속 사용 중.
- **v1 기관/PCAF 테이블** (§9~23) — 여신 포트폴리오 단위 금융배출량(PCAF Business Loans) 산정 레이어(§9~21)와 그 위의 관리자 승인요청·감사 로그·상품 참조 테이블(§15, §22~23, 2주차 추가)까지 포함. `financial_institutions`를 데이터 격리의 루트로 두고, 기존 v0.1 테이블(`vouchers`, `classifications`)에는 소속 기관을 가리키는 FK만 nullable로 얹었다(§24 참고).
- **소상공인 탄소중립포인트 트랙 테이블** (§25) — §1~23과 달리 **아직 구현 전, 계획 단계**. Alembic revision도 없다. 착수 여부·시점은 회계 확인 작업(data-plan.md §15.1)에 달려 있다.

## 1. `companies` — 기업
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| name | VARCHAR(100) | NN | 기업명 (예: ○○정밀) |
| industry_code | VARCHAR(20) | NN | 업종코드 (예: C251) |
| industry_name | VARCHAR(100) | | 업종명 |
| employee_count | INTEGER | | 직원 수 |
| revenue_krw | NUMERIC(20,0) | | 매출액 |
| region | VARCHAR(50) | | 지역 (예: 경북 구미시) |
| created_at | TIMESTAMPTZ | default now | |
| fuel_types_json | JSON | | 사장님이 연료 체크 단계에서 고른 값 `{diesel, gasoline, city_gas, lpg: "yes"\|"no"\|"unsure", electricity}`. null이면 미입력 — 결손 알림 필터 미적용(체크 안 한 연료는 결손 알림 대상에서 제외, §3 원칙8) |

## 2. `vouchers` — 전표 raw (세금계산서·전기 고지서)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| company_id | INTEGER | FK→companies.id, NN | |
| source | VARCHAR(20) | NN | `hometax` \| `kepco` |
| issue_date | TIMESTAMPTZ | | 발행일 |
| year | SMALLINT | NN | |
| month | SMALLINT | NN | |
| supplier_name | VARCHAR(100) | | 공급자 상호 |
| item_description | TEXT | | 품목명 ("지게차 경유 외 1종") |
| supply_amount_krw | NUMERIC(15,0) | | 공급가액 (부가세 제외) |
| raw_json | JSON | | 원본 |
| created_at | TIMESTAMPTZ | default now | |
| financial_institution_id | INTEGER | FK→financial_institutions.id | 어느 기관 동의·수집 경로에서 생성됐는지 (nullable, 0006에서 백필) |
| institution_borrower_id | INTEGER | FK→institution_borrowers.id | (nullable, 0006에서 백필) |

**IX** `ix_vouchers_company_year_month` (company_id, year, month)

## 3. `classifications` — 분류 결과
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| voucher_id | INTEGER | FK→vouchers.id, NN, UQ | |
| scope | SMALLINT | | 1 \| 2 \| 3 |
| category | VARCHAR(50) | | 고정연소·이동연소·간접배출 |
| fuel_type | VARCHAR(50) | | 경유·도시가스·전기 |
| amount_krw | NUMERIC(15,0) | | 분류된 공급가액 |
| activity_amount | FLOAT | | 물량 (L·kWh·m³) |
| activity_unit | VARCHAR(20) | | 단위 |
| emission_co2e | FLOAT | | kgCO2e (결정론적 계산 결과, 표시 시 ÷1000) |
| confidence | FLOAT | | 0.0~1.0 |
| evidence | TEXT | | LLM 판단 근거 |
| method | VARCHAR(10) | | `rule` \| `llm` |
| mixed_item | INTEGER | default 0 | 1 = "외 1종" 혼합 |
| status | VARCHAR(20) | default 'auto' | auto · review_required · confirmed |
| classified_at | TIMESTAMPTZ | default now | |
| reviewed_at | TIMESTAMPTZ | | 담당자 확정/반려 시각 (review_required 건만 기록) |
| classification_method | VARCHAR(10) | CK | `rule` \| `llm` \| `manual` — 기존 `method`와 분리해 관리자 수동 정정까지 표현 |
| activity_data_method | VARCHAR(30) | CK | `reported_quantity` \| `invoice_quantity` \| `spend_converted` \| `economic_estimate` \| `industry_estimate` |
| source_document_id | INTEGER | FK→source_documents.id | 이 분류의 근거 문서 (역추적용) |
| quantity_source | VARCHAR(20) | | `document` \| `calculated` \| `manual` |
| factor_id | INTEGER | FK→emission_factors.id | 사용된 배출계수 |
| factor_version | VARCHAR(20) | | |
| data_period_start | TIMESTAMPTZ | | |
| data_period_end | TIMESTAMPTZ | | |
| calculation_warning | JSON | | |

**CK** `ck_classifications_classification_method`, `ck_classifications_activity_data_method`

## 4. `emission_factors` — 배출계수 (환경부·GIR, 회계 담당 관리)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| fuel_type | VARCHAR(50) | NN | |
| scope | SMALLINT | NN | |
| category | VARCHAR(50) | | |
| factor_co2 | FLOAT | NN | kg CO2/단위 |
| factor_ch4 | FLOAT | default 0 | |
| factor_n2o | FLOAT | default 0 | |
| gwp_co2e | FLOAT | | CO2e 환산 계수 |
| unit | VARCHAR(20) | NN | L·kWh·m³ |
| source | VARCHAR(100) | | 출처 |
| valid_from | SMALLINT | | 유효 시작연도 |
| valid_to | SMALLINT | | 유효 종료연도 |

## 5. `unit_prices` — 환산단가 (월별, 공급가액 기준)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| fuel_type | VARCHAR(50) | NN | |
| year | SMALLINT | NN | |
| month | SMALLINT | NN | 월별 필수 (유가 월 변동) |
| unit_price_krw | NUMERIC(10,2) | NN | 원/단위 |
| unit | VARCHAR(20) | NN | L·m³·kWh |
| source | VARCHAR(100) | | |

**IX** `ix_unit_prices_fuel_year_month` (fuel_type, year, month)

## 6. `trace_logs` — 에이전트 판단 일지 (킬러씬 A 소스, 결선까지 불변)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| company_id | INTEGER | FK→companies.id, NN | |
| session_id | VARCHAR(36) | NN | 실행별 UUID |
| step_type | VARCHAR(20) | NN | 계획 \| 관찰 \| 행동 |
| tool_name | VARCHAR(50) | | 호출 도구명 |
| message | TEXT | NN | 타임라인 표시 문구 |
| detail_json | JSON | | tool input/output 원문 |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_trace_session` (session_id)

## 7. `llm_cache` — LLM 캐시 (전표 텍스트 해시 → 응답)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| text_hash | VARCHAR(64) | NN, UQ | SHA256 |
| item_description | TEXT | | 원문 (디버깅용) |
| llm_response | JSON | NN | Classification 스키마 그대로 |
| hit_count | INTEGER | default 0 | |
| created_at | TIMESTAMPTZ | default now | |
| last_used_at | TIMESTAMPTZ | default now | |

## 8. `industry_distributions` — 업종별 배출량 분포 (벤치마킹·이상치 검증, 도구④)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| industry_code | VARCHAR(20) | NN | 예: C251 |
| industry_name | VARCHAR(100) | | |
| scope | SMALLINT | NN | 1 \| 2 |
| emission_min_co2e | FLOAT | | 최소 |
| emission_median_co2e | FLOAT | | 중앙값 |
| emission_median_per_employee | FLOAT | | 인당 중앙값 |
| emission_max_co2e | FLOAT | | 최대 |
| revenue_basis_krw | NUMERIC(20,0) | | 정규화 기준 매출 |
| year | SMALLINT | NN | |
| source | VARCHAR(100) | | |

**IX** `ix_industry_dist_code_year` (industry_code, year)

---

## 9. `financial_institutions` — 금융기관 (v1 데이터 격리의 루트)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| name | VARCHAR(100) | NN | |
| reporting_currency | VARCHAR(3) | NN | ISO 4217, 예: KRW |
| tenant_key | VARCHAR(50) | NN, UQ | |
| created_at | TIMESTAMPTZ | default now | |

## 10. `institution_users` — 금융기관 소속 사용자 (역할 기반 권한의 기반)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| user_id | VARCHAR(100) | NN | |
| role | VARCHAR(20) | NN, CK | `admin` \| `analyst` \| `reviewer` \| `approver` \| `viewer` |
| active | BOOLEAN | default true | |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_institution_users_institution_user` (financial_institution_id, user_id) · **CK** `ck_institution_users_role`

## 11. `institution_borrowers` — 금융기관-차주 관계 (동의 범위 단위)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| company_id | INTEGER | FK→companies.id, NN | |
| external_customer_id | VARCHAR(100) | NN | 마이데이터 사업자등록번호 등 외부 식별자 |
| consent_status | VARCHAR(20) | NN, CK, default 'pending' | `pending` \| `active` \| `revoked` \| `expired` |
| consent_scope_json | JSON | | |
| consent_started_at | TIMESTAMPTZ | | |
| consent_ended_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | default now | |

**UQ** `uq_institution_borrowers_institution_external_id` (financial_institution_id, external_customer_id) · **CK** `ck_institution_borrowers_consent_status`

> 동의 범위 없이 기관 간 데이터를 공유하지 않는다는 게 이 테이블의 존재 이유 — `api/queries.py::resolve_institution_borrower()`가 `consent_status='active'` 건만 골라 새 전표/문서의 기관 귀속에 쓴다.

## 12. `portfolios` — 기관별 기업대출 포트폴리오 (산정 스냅숏 상위 단위)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| name | VARCHAR(100) | NN | |
| reporting_year | SMALLINT | NN | |
| reporting_date | TIMESTAMPTZ | | |
| reporting_currency | VARCHAR(3) | NN | |
| scope_mode | VARCHAR(30) | NN, CK | `supported_business_loans` \| `full_institution` |
| total_relevant_outstanding | NUMERIC(20,0) | | |
| reporting_date_events_json | JSON | | |
| status | VARCHAR(20) | NN, CK, default 'draft' | `draft` \| `calculated` \| `reviewed` \| `approved` \| `superseded` |
| version | INTEGER | NN, default 1 | |
| supersedes_portfolio_id | INTEGER | FK→portfolios.id | 재산정 시 이전 버전 참조 |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_portfolios_institution_year` (financial_institution_id, reporting_year) · **CK** `ck_portfolios_scope_mode`, `ck_portfolios_status`

## 13. `organizational_boundaries` — 차주 조직범위 기준정보
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| company_id | INTEGER | FK→companies.id, NN | |
| reporting_year | SMALLINT | NN | |
| boundary_type | VARCHAR(30) | NN, CK | `operational_control` \| `financial_control` \| `equity_share` |
| consolidation_scope | VARCHAR(20) | NN, CK | `consolidated` \| `separate` |
| included_entities_json | JSON | | |
| excluded_entities_json | JSON | | |
| description | TEXT | | |
| approved_by | VARCHAR(100) | | |
| approved_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_org_boundaries_company_year` (company_id, reporting_year) · **CK** `ck_org_boundaries_boundary_type`, `ck_org_boundaries_consolidation_scope`

## 14. `source_documents` — 원본 증빙 문서 (중복 적재 방지, 계산 결과 역추적)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| company_id | INTEGER | FK→companies.id, NN | |
| document_type | VARCHAR(50) | NN | `tax_invoice` \| `electric_bill` \| `gas_bill` \| `business_registration` \| `vat_tax_base` \| `financial_statement` \| `sme_certificate` \| `kepco_payment_history` 등 |
| source_system | VARCHAR(50) | | `upload:ocr` \| `upload:excel` \| `mydata:business-registration` 등 |
| document_date | TIMESTAMPTZ | | |
| period_start | TIMESTAMPTZ | | |
| period_end | TIMESTAMPTZ | | |
| file_hash | VARCHAR(64) | | SHA256, 중복 적재 방지 |
| original_filename | VARCHAR(255) | | |
| extracted_json | JSON | | OCR/엑셀/마이데이터 추출 결과 원문 |
| verification_status | VARCHAR(20) | default 'unverified' | |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_source_documents_company`, `ix_source_documents_file_hash` · **UQ** `uq_source_documents_company_file_hash` (company_id, file_hash) — 코드 레벨 SELECT-then-INSERT 중복 체크가 못 잡는 동시 업로드 레이스에 대한 최종 방어선

> 하이브리드 입력 파이프라인(마이데이터 5종 + 업로드 3종)의 공통 착지점. 에너지 관련 문서(세금계산서·전기고지서·도시가스고지서)는 여기 적재된 뒤 `vouchers`로 변환돼 기존 `classify_vouchers()`/`calc_engine.py` 파이프라인을 그대로 탄다. 표준재무제표증명은 `borrower_financials`에도 매핑되고, 나머지 KYB성 문서(사업자등록증명·부가세과세표준증명·중소기업확인서·전기요금납부내역)는 이 테이블에만 남는다.

> **계획됨 (미구현)** — 소상공인 탄소중립포인트 트랙(§25)을 위해 `contract_type`
> VARCHAR(50, nullable, 원문 예: "산업용(을) 고압A")과 `contract_type_class` VARCHAR(20,
> nullable, industrial\|commercial\|residential\|unknown)을 이 테이블에 추가 예정 —
> 전기고지서 파싱 단계에서 채운다. 아직 Alembic revision 없음. 근거: `docs/small-business-
> green-supply-data-plan.md` §7.1, `docs/small-business-green-supply-develop-plan.md` §2.1

## 15. `source_document_access_logs` — 원본문서 열람 감사 로그 (v1 2주차)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| source_document_id | INTEGER | FK→source_documents.id, NN | |
| accessed_by | VARCHAR(100) | NN | 담당자 식별자 — 별도 인증 체계 도입 전까지 문자열로만 받음 |
| accessed_at | TIMESTAMPTZ | default now | |

**IX** `ix_source_document_access_logs_document` (source_document_id)

> "분류를 확정/반려했다"는 조치 기록(`classifications.evidence` 누적, §3)과 "원본 증빙을 열람했다"는 접근 기록은 서로 다른 축이라 분리했다 — `SourceDocument` 자체엔 열람자·열람시각 컬럼이 없어 조회할 때마다 여기 한 행씩 쌓인다(`GET /admin/documents/{id}` 호출 시 자동 기록).

## 16. `pcaf_quality_rules` — PCAF Business Loans 데이터 품질표
PCAF Standard Part A Third Edition, Table 10.1-2(Annex, p.192)의 Option 1a/1b/2a/2b/3a/3b/3c 7종을 그대로 옮긴 참조 테이블.

| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| standard_version | VARCHAR(50) | NN | 예: "PCAF Part A Third Edition" |
| asset_class | VARCHAR(50) | NN | `business_loans_and_unlisted_equity` |
| option_code | VARCHAR(10) | NN, UQ | `1a` \| `1b` \| `2a` \| `2b` \| `3a` \| `3b` \| `3c` |
| quality_score | SMALLINT | NN, CK | PCAF Score 1(최고)~5(최저) |
| activity_data_basis | VARCHAR(30) | NN, CK | `verified_emissions` \| `unverified_emissions` \| `energy_consumption` \| `production` \| `revenue` \| `assets` \| `asset_turnover_ratio` |
| applies_to_scope3 | BOOLEAN | NN, default true | Option 2a만 false(각주 208 — 에너지 소비량 기반은 Scope 3 적용 불가) |
| description | TEXT | | |
| source_reference | TEXT | NN | 예: "PCAF Standard Part A, Table 10.1-2, Option 2b" |
| valid_from | SMALLINT | | |
| valid_to | SMALLINT | | |

**IX** `ix_pcaf_quality_rules_asset_class` · **CK** `ck_pcaf_quality_rules_activity_data_basis`, `ck_pcaf_quality_rules_quality_score`

> 분류 신뢰도(`classifications.confidence`)·HITL 상태와는 완전히 분리된 축 — "이 배출량이 얼마나 확신되는가"가 아니라 "이 배출량이 무엇을 근거로 산정됐는가"를 표준화한다.

## 17. `borrower_emission_inventories` — 차주 연간 Scope별 배출량 인벤토리
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| company_id | INTEGER | FK→companies.id, NN | |
| reporting_year | SMALLINT | NN | |
| organizational_boundary_id | INTEGER | FK→organizational_boundaries.id, NN | |
| scope_group | VARCHAR(10) | NN, CK | `scope_1` \| `scope_2` \| `scope_3` |
| scope2_method | VARCHAR(20) | CK | `location_based` \| `market_based` \| null |
| scope3_status | VARCHAR(20) | CK | `reported` \| `estimated` \| `not_reported` \| `not_calculated` \| `not_applicable` \| null |
| emission_tco2e | FLOAT | nullable | Scope 3 미산정 시 **null**(0 아님) — LLM 산수 금지·미산정을 0으로 처리하지 않는다는 원칙 |
| calculation_method_summary | TEXT | | |
| gwp_version | VARCHAR(20) | | |
| verified | BOOLEAN | default false | |
| verification_level | VARCHAR(20) | | |
| completeness_pct | FLOAT | | |
| candidate_quality_score | SMALLINT | | |
| candidate_quality_rule_id | INTEGER | FK→pcaf_quality_rules.id | |
| candidate_quality_basis_json | JSON | | |
| limitations_json | JSON | | |
| status | VARCHAR(20) | NN, CK, default 'draft' | `draft` \| `calculated` \| `reviewed` \| `approved` \| `superseded` |
| version | INTEGER | NN, default 1 | |
| supersedes_inventory_id | INTEGER | FK→borrower_emission_inventories.id | |
| input_snapshot_hash | VARCHAR(64) | | |
| approved_by | VARCHAR(100) | | |
| approved_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_inventories_company_year_scope` (company_id, reporting_year, scope_group) · **CK** `ck_inventories_scope_group`, `ck_inventories_scope2_method`, `ck_inventories_scope3_status`, `ck_inventories_status`

> `emission_tco2e`는 `db/pcaf_quality.py::aggregate_scope_emissions`(전표별 `classifications` → 연간 Scope 합산, kg→t)가 채운다 — `POST /borrowers/{company_id}/quality-assessments/{year}/evaluate`가 `candidate_quality_score`와 함께 매번 계산해 저장한다(v1 §4 "인벤토리 완전성 집계", 2주차 반영). 기존 `db/pcaf.py::_after_measured`(v0.1 사장님 리포트 `/pcaf/{id}`용, 연도 필터 없이 Scope 1·2 통합)와는 별개 계산 경로 — 후자는 재사용하지 않고 이 파일이 이미 하던 연도·Scope 분리 집계(§16 `assess_inventory_completeness`)와 같은 방식으로 새로 집계한다. Scope 3는 이 프로젝트가 데이터를 만들지 않아 항상 `emission_tco2e=null`, `scope3_status='not_calculated'`.

## 18. `inventory_gas_emissions` — 인벤토리의 가스별 배출량
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| inventory_id | INTEGER | FK→borrower_emission_inventories.id, NN | |
| gas_type | VARCHAR(10) | NN, CK | `CO2` \| `CH4` \| `N2O` \| `HFCs` \| `PFCs` \| `SF6` \| `NF3` |
| emission_mass | FLOAT | | |
| mass_unit | VARCHAR(20) | | |
| gwp_value | FLOAT | | |
| gwp_version | VARCHAR(20) | | |
| emission_co2e | FLOAT | | |
| included | BOOLEAN | default true | |
| exclusion_reason | TEXT | | 미확인 가스는 0이 아니라 제외 사유를 남긴다 |

**IX** `ix_gas_emissions_inventory` · **CK** `ck_gas_emissions_gas_type`

## 19. `business_loan_exposures` — 포트폴리오의 기업대출 익스포저
지원 조건: `asset_class=business_loans_and_unlisted_equity`, `company_type=private_company`, `loan_purpose=general_corporate_purpose`. 미충족 시 `included=false` + `exclusion_reason` 기록(비상장 중소기업 일반 목적 기업대출만 지원).

| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| portfolio_id | INTEGER | FK→portfolios.id, NN | |
| company_id | INTEGER | FK→companies.id, NN | |
| external_exposure_id | VARCHAR(100) | NN | |
| asset_class | VARCHAR(50) | NN | |
| outstanding_amount | NUMERIC(20,0) | NN | |
| currency | VARCHAR(3) | NN | |
| reporting_date | TIMESTAMPTZ | NN | |
| loan_purpose | VARCHAR(50) | | |
| company_type | VARCHAR(30) | | |
| included | BOOLEAN | default true | |
| exclusion_reason | TEXT | | |
| source_snapshot_json | JSON | | |
| created_at | TIMESTAMPTZ | default now | |

**UQ** `uq_business_loan_exposures_portfolio_external_id` (portfolio_id, external_exposure_id) · **IX** `ix_business_loan_exposures_company`

## 20. `borrower_financials` — 차주 재무정보
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| financial_institution_id | INTEGER | FK→financial_institutions.id, NN | |
| company_id | INTEGER | FK→companies.id, NN | |
| financial_year | SMALLINT | NN | |
| as_of_date | TIMESTAMPTZ | NN | |
| currency | VARCHAR(3) | NN | |
| total_equity | NUMERIC(20,0) | | |
| total_debt | NUMERIC(20,0) | | PCAF 방법론상 total debt — 총부채와 혼용 금지, `debt_definition`에 출처 고정 |
| debt_definition | TEXT | | |
| consolidation_scope | VARCHAR(20) | | |
| included_entities_json | JSON | | |
| source | VARCHAR(100) | | 예: `mydata:financial-statement` |
| verified | BOOLEAN | default false | |
| version | INTEGER | NN, default 1 | 재산정 시 새 버전 생성(§8.5 재산정 정책) |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_borrower_financials_company_year` (company_id, financial_year) · **UQ** `uq_borrower_financials_company_year_version` (company_id, financial_year, version) — 동시 요청이 같은 (기업,연도,버전) 중복 행을 만드는 레이스 방지

## 21. `fx_rates` — 환율
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| base_currency | VARCHAR(3) | NN | |
| quote_currency | VARCHAR(3) | NN | |
| rate | NUMERIC(20,8) | NN | |
| rate_date | TIMESTAMPTZ | NN | |
| rate_type | VARCHAR(20) | NN, CK | `closing` \| `average` \| `policy_defined` |
| source | VARCHAR(100) | | |
| created_at | TIMESTAMPTZ | default now | |

**IX** `ix_fx_rates_pair_date` (base_currency, quote_currency, rate_date) · **CK** `ck_fx_rates_rate_type`

## 22. `rate_approval_requests` — 우대금리·설비금융 안내 승인요청 큐 (v1 2주차)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| company_id | INTEGER | FK→companies.id, NN | |
| request_type | VARCHAR(20) | NN, CK, default 'rate_upgrade' | `rate_upgrade` \| `equipment_finance` |
| scope_group | VARCHAR(20) | | `scope_1` \| `scope_2` \| null(equipment_finance·0014 이전 과거 스냅샷) — 정식 엔진은 Scope별 독립 판정이라 한 기업이 두 Scope 모두 후보일 수 있다(0014 마이그레이션) |
| current_grade | SMALLINT | | 요청 생성 시점 PCAF 등급 스냅샷 — 이미 자격 충족 상태면 target_grade와 동일값 |
| target_grade | SMALLINT | | 결손을 채웠을 때의 예상 등급, 또는 이미 도달한 등급(스냅샷) |
| missing_summary | TEXT | | 필요 데이터 요약(생성 시점 고정) |
| matched_product_name | VARCHAR(200) | | 매칭된 `rate_products.product_name` 스냅샷(FK 아님) — "이미 대상" 상태 요청에서만 채워짐(0016) |
| disclaimer_text | TEXT | NN | 비보장 문구 — 생성 시점에 고정 저장(정책이 바뀌어도 과거 요청 문구는 그대로) |
| status | VARCHAR(20) | NN, CK, default 'pending' | `pending` \| `approved` \| `rejected` |
| reviewed_by | VARCHAR(100) | | |
| reviewed_at | TIMESTAMPTZ | | |
| review_note | TEXT | | |
| created_at | TIMESTAMPTZ | default now | |

**CK** `ck_rate_approval_requests_request_type`, `ck_rate_approval_requests_status` · **IX** `ix_rate_approval_requests_company`, `ix_rate_approval_requests_status`

> 기존 `GET /admin/rate-candidates`(§16 `pcaf_quality_rules`와는 무관, `db/pcaf.py::rate_upgrade_candidates`)는 읽기 전용 "안내 후보" 목록만 계산할 뿐 저장하지 않는다. 이 테이블은 사장님이 그 안내를 보고 실제로 만든 요청과, 은행 담당자의 승인/반려를 저장한다. 승인은 여신 결정이 아니다(§3 원칙6, 원칙9) — "안내 대상으로 확인했다"는 수동 확인이며, `current_grade`/`target_grade`/`missing_summary`는 이후 재산정과 무관하게 요청 당시 근거를 그대로 보존한다. `classifications`(분류 신뢰도) 기반 HITL 큐와는 데이터·엔드포인트가 완전히 분리돼 있다.

## 23. `rate_products` — 우대금리 참조 상품 (v1 2주차, 0016)
| 컬럼 | 타입 | 키/제약 | 설명 |
| --- | --- | --- | --- |
| id | INTEGER | PK | |
| product_name | VARCHAR(200) | NN | 예: "ESG Grow-Up 특별대출" |
| provider_name | VARCHAR(100) | NN | 예: "iM뱅크" |
| min_data_quality_score | SMALLINT | NN, CK | 이 점수 이하(=이 등급 이상 고품질)면 자격 충족(PCAF 1=최고~5=최저) |
| rate_discount_pct | NUMERIC(4,2) | NN | 우대금리 폭(%p) — 상품 공시 안내값, 확정 금리 아님 |
| eligibility_description | TEXT | NN | |
| source_reference | TEXT | NN | 실제 상품 공시 페이지 출처 |
| disclaimer_note | TEXT | | |
| created_at | TIMESTAMPTZ | default now | |

**CK** `ck_rate_products_min_data_quality_score`

> `pcaf_quality_rules`(§16)와 동일한 패턴 — 코드가 원 소스(`db/init_db.py::seed_rate_products`), 임의 수치를 지어내지 않고 실제 은행 상품의 공시 조건 중 이 프로젝트가 실제로 만드는 데이터(PCAF Scope 1·2 품질등급)로 증빙 가능한 티어만 시드한다. `db/rate_products.py::rate_product_status_for_company`가 `db/pcaf_quality.py::assess_borrower_emission_quality`의 `candidate_score`와 `min_data_quality_score`를 비교해 "eligible"(이미 자격 충족) 또는 "upgrade_needed"(등급 개선 필요, `db/pcaf_quality.py::quality_upgrade_candidate` 재사용)로 판정한다 — LLM 미호출, 결정론적 코드만.

---

## 24. 참고

- 정본은 `db/models.py`. 스키마 변경은 전부 Alembic 마이그레이션(`alembic/versions/`)으로 관리 — `Base.metadata.create_all` 직접 호출이나 `init_db.py`의 수동 `ALTER TABLE`은 더 이상 쓰지 않는다.
- 초기화: `alembic upgrade head`(스키마) + 마스터 데이터 시드는 `db/init_db.py`, 시연 데이터는 `db/seed_mock.py`.
- **공유 Supabase DB에 마이그레이션 적용 전 항상 사용자 확인을 받는다** — 여러 명이 같은 DB에 붙어 있어 `alembic upgrade/downgrade`가 곧바로 팀 전체에 영향을 준다.
- v0.1 테이블(`vouchers`, `classifications`)과 v1 테이블(`source_documents`, `institution_borrowers` 등)은 서로 nullable FK로만 연결돼 있다 — 기존 파이프라인을 건드리지 않고 기관 귀속·문서 출처를 얹는 방식(0006 백필로 기존 데모 데이터도 기본 기관에 소급 연결).
- PCAF 엔진은 현재 두 갈래로 존재한다: 임시 구현 `db/pcaf.py::company_pcaf_summary()`(구 1~5등급 방식, `ScenePcaf.tsx`가 아직 이걸 씀)와 정식 구현 `db/pcaf_quality.py`(Table 10.1-2 옵션 기반, `/borrowers/{company_id}/quality-assessments/{year}`로 노출되지만 프론트 미연결) — 교체 작업 남아 있음.
- `db/pcaf.py::rate_upgrade_candidates`(전체 기업 순회, 읽기 전용 안내 목록)는 단일 기업 판정 함수 `upgrade_candidate_for_company`로 리팩터링됐다 — `rate_approval_requests` 생성 시(§22) 동일 판정 로직을 재사용해 등급 스냅샷을 저장하기 위함(로직 중복 없음).

## 25. 계획됨 — 미구현 (소상공인 탄소중립포인트 트랙)

> 아래 3개 테이블은 §1~23과 달리 **아직 `db/models.py`에 없고 Alembic revision도 없다.**
> 정본은 `docs/small-business-green-supply-data-plan.md` §7.2~§7.4, 실행 계획은
> `docs/small-business-green-supply-develop-plan.md` §2.2·§7. 착수 조건(회계 확인 작업)은
> data-plan.md §15.1 참고 — 컬럼명·타입은 실제 구현 시 바뀔 수 있다.

### 25.1 `water_bills` (계획)
| 컬럼 | 설명 |
| --- | --- |
| id, company_id | |
| source_document_id | FK→source_documents |
| provider | 지자체 상수도사업본부명 |
| customer_number, site_addr | |
| period_start / period_end | |
| usage_amount_m3 | 당월 사용량 |
| prev_usage_amount_m3 | |
| base_fee_krw, usage_fee_krw, sewage_fee_krw, water_utilization_fee_krw, billed_amount_krw | |
| created_at | |

문서종류 어휘에 `water_bill` 추가 필요 — **단 DDL은 아니다(2026-08-22 정정).**
`source_documents.document_type`은 DB enum이 아니라 `VARCHAR(50)`이고 CHECK 제약도 없어
마이그레이션 없이 코드 레벨 어휘 목록만 고치면 된다(대상 파일은
`docs/small-business-green-supply-data-plan.md` §7.2 참고). 실제 고지서 서식 미검증(§14-2) —
이번엔 스키마만 먼저 준비하고 파싱 로직은 서식 확보 후 추가.

### 25.2 `carbon_neutral_point_applications` (계획)
| 컬럼 | 설명 |
| --- | --- |
| id, company_id | |
| application_type | `business` \| `household` — 이번 범위는 business만 |
| baseline_year, target_year | |
| baseline_usage_json, target_usage_json | `{"electricity_kwh": n, "water_m3": n, "city_gas_m3": n}` |
| reduction_rate_pct | 감탄 자체 예상치(공식 판정 아님, CLAUDE.md §5 원칙10) |
| eligible | bool |
| status | `draft` \| `submitted` \| `approved` \| `rejected` — draft까지만 감탄이 갱신, 이후는 사장님 수동 갱신 |
| draft_document_url | 자동 생성된 신청서 초안 파일 경로 |
| created_at | |

### 25.3 `carbon_neutral_point_enrollments` (계획)
| 컬럼 | 설명 |
| --- | --- |
| id, company_id | |
| enrolled, enrolled_at | |
| point_type | `cash` \| `green_card_point` \| `local_currency`(비전 단계) |
| source | `self_reported` \| `api_confirmed` — 대구시 API 연동 전까지는 self_reported만 |

## 변경 이력
- 2026-08-22: §25(계획됨) 신설 — 소상공인 탄소중립포인트 트랙의 미구현 테이블 3종
  (`water_bills`, `carbon_neutral_point_applications`, `carbon_neutral_point_enrollments`)
  및 `source_documents`(§14)에 추가 예정인 `contract_type`/`contract_type_class` 컬럼 반영.
  전부 계획 단계이며 Alembic revision 없음 — 정본은
  `docs/small-business-green-supply-data-plan.md` §7.
- 2026-08(2주차): `rate_products`(§23) 추가 + `rate_approval_requests`(§22)에 `matched_product_name` 컬럼 — 우대금리 카드를 "이미 대상"/"개선 필요" 두 상태로 나누며 실제 iM뱅크 상품(ESG Grow-Up 특별대출)을 참조 시드. `0016_rate_products.py` 마이그레이션. §22 표에 그동안 누락돼 있던 `scope_group` 컬럼(0014)도 같이 반영.
- 2026-08(2주차): §17 `borrower_emission_inventories.emission_tco2e`를 채우는 집계 로직(`aggregate_scope_emissions`) 추가 — 스키마 변경 없음, 계산 경로만 신규(§4 역할분담 "인벤토리 완전성 집계" 해소).
- 2026-08(2주차): `source_document_access_logs`(§15), `rate_approval_requests`(§22) 추가 — 승인요청 큐(HITL 큐와 분리)와 원본문서 열람 감사 로그(PR #28). `0011_rate_approval_and_access_log.py` 마이그레이션.
- 2026-08: v1 기관/PCAF 레이어(§9~21) 전면 추가, Alembic 도입 반영, PCAF 이원화 현황 명시.
- 2026-07: `classifications.reviewed_at` 추가 — 관리자 대시보드 "검토 대기" 집계(오늘 확정/반려 건수)를 위해 담당자 확정/반려 시각을 기록. `PATCH /admin/classifications/{id}/confirm|reject`, `edit_classification`에서 기록.
