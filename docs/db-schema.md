# iM-Bridge DB 스키마

> Supabase(PostgreSQL) · SQLAlchemy 직접 접속 · 정본: `db/models.py`
> 표기: **PK** 기본키 · **FK** 외래키 · **UQ** 유니크 · **IX** 인덱스 · NN NOT NULL

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
| emission_co2e | FLOAT | | tCO2e (결정론적 계산 결과) |
| confidence | FLOAT | | 0.0~1.0 |
| evidence | TEXT | | LLM 판단 근거 |
| method | VARCHAR(10) | | `rule` \| `llm` |
| mixed_item | INTEGER | default 0 | 1 = "외 1종" 혼합 |
| status | VARCHAR(20) | default 'auto' | auto · review_required · confirmed |
| classified_at | TIMESTAMPTZ | default now | |
| reviewed_at | TIMESTAMPTZ | | 담당자 확정/반려 시각 (review_required 건만 기록) |

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

## 참고
- 정본은 `db/models.py`. 초기화는 `python -m db.init_db`(테이블 생성 + 마스터 데이터 시드), 시연 데이터는 `python -m db.seed_mock`.
- `init_db`는 확정 스키마 외 잉여 테이블(`classification_results`, `monthly_unit_prices`, `portfolio_summaries`, `hitl_queue`)을 매 실행 시 DROP한다.
- `Base.metadata.create_all`은 신규 테이블만 생성하고 기존 테이블의 컬럼 추가는 반영하지 않는다(Alembic 미도입). 기존 테이블에 컬럼을 추가할 때는 `db/init_db.py`의 `migrate_columns()`에 멱등 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`를 추가해야 한다 — `classifications.reviewed_at`이 그 예시.

## 변경 이력
- 2026-07: `classifications.reviewed_at` 추가 — 관리자 대시보드 "검토 대기" 집계(오늘 확정/반려 건수)를 위해 담당자 확정/반려 시각을 기록. `PATCH /admin/classifications/{id}/confirm|reject`, `edit_classification`에서 기록.
