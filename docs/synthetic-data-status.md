# 시연/동작에 필요한 합성 데이터 현황

```text
Status: working-note
Last updated: 2026-08-12
Scope: 감탄 시연·검증에 필요한 합성 데이터의 제작 현황과 남은 작업
```

> 이 문서는 회계·도메인 담당이 "무엇을 더 만들어야 하는가"를 추적하기 위한 현황판이다.
> DB 실적재 건수는 이 세션에 DB 접속 정보(`DATABASE_URL`)가 없어 재검증하지 못했다 —
> 표시된 DB 건수는 이전 확인 시점 기준이며, 코드/파일 상태만 이번에 직접 재확인했다.

---

## ① 시연용 전표 — `db/seed_mock.py` (○○정밀, DB 적재: 33건 · 이전 확인 기준)

- `/mock/hometax`, `/mock/kepco`가 그대로 반환하는 실제 소스
- 2025년 12개월치, 킬러씬 요소 전부 구현됨:
  - 3~5월 도시가스 결손 (`db/seed_mock.py:53-76`, 결손 감지 시나리오 트리거)
  - 7월 "지게차 경유 외 1종" 이상치(평월 대비 ~3.2배, `:87-97`, 자가검증 시나리오)
  - "경유 외 1종", "유류대금", "동절기 난방유" 등 비정형 표현 혼재
- **상태: 정상 — 시연 그대로 사용 가능.** 이번 세션에서 손대지 않음.

---

## ② 분류 강건성 테스트용 합성전표 — `db/synth_generator.py` → `data/synth_vouchers_300.csv`

- 파라미터형 생성기(`--count --gap --anomaly --seed`), `data/감탄_데이터준비_샘플.xlsx`의
  `전표_샘플` 표현을 앵커링 소스로 사용(`--from-excel`)
- **2026-08-12: 300건 생성 완료** — `python -m db.synth_generator --count 300 --companies 9 --from-excel --seed 42 --out data/synth_vouchers_300.csv`
  - 9개 기업, 데모 기업(○○정밀)만 결손(3·4·5월 도시가스)·이상치(7월 경유 ×3.2) 시나리오 포함, 나머지 8개 기업은 정상 12개월
  - git 커밋 완료(`신규-대량전표 300건`)
- **용도가 다름**: DB `vouchers`(시연 33건)와 별개 — 트랙B 분류 정확도 검증용이지 시연 데이터가 아님
- **상태: 파일은 있으나 DB엔 미적재.** 검증(3단계, 8/4~8/10) 착수 시 적재 여부 결정 필요 — 지금은 결정 보류.

---

## ③ 회계 마스터데이터 — `data/감탄_데이터준비_샘플.xlsx` → `db/excel_loader.py`

- 배출계수·환산단가(월별) 시트를 여기서 읽어 `db/init_db.py`가 적재
- **2026-08-12 재검증 결과** (`db.excel_loader` 함수 직접 호출, 이 세션에서 확인):
  - `load_emission_factors()` → **5건** (Excel에서 정상 파싱, 하드코딩 폴백 아님)
  - `load_unit_prices()` → **48건** (경유·휘발유 12개월 + LPG 프로판/부탄 12개월 등, `월별단가` 시트 정상 사용)
  - `load_classification_rules()` → **58건** (기존 50 + 신규 8, 아래 참고)
  - `load_expected_results()` → **50건** (기존 41 + 신규 9)
- **2026-08-12 확장**: `전표_샘플`·`분류_기준표_확장`·`기대_결과` 3개 시트에 K-택소노미/설비투자/HITL
  시나리오 9건(I042~I050, R051~R058) 추가 — 태양광·ESS·전동지게차·히트펌프·집진기·폐수처리설비·
  재활용설비(참고분류)·유지보수비 불명확(HITL)·동일 전표 중복 업로드. `scripts/extend_data_sample.py`로
  재현 가능(재실행 시 `data/감탄_데이터준비_샘플_원본백업.xlsx`는 덮어쓰지 않음).
  `배출계수`·`월별단가` 시트는 원본 그대로 — 이미 이 세션에서 확인한 정밀도가 더 높아 손대지 않음.
- **신규 참고용 시트 8개 추가** (`company_master`, `mydata_documents`, `uploaded_files`,
  `k_taxonomy_mapping`, `facility_keywords`, `hitl_queue_mock`, `bank_loans_mock`,
  `portfolio_dashboard_mock`, `README_확장내역`) — **주의: `db/excel_loader.py`는 이 신규
  시트를 읽지 않는다.** 5개 지정 시트(`전표_샘플`/`분류_기준표_확장`/`배출계수`/`월별단가`/`기대_결과`)만
  로더 대상이며, 신규 시트는 참고·발표용 자료다. DB에 반영하려면 별도 로더 함수를 코드로
  구현해야 한다(이번엔 코드 미변경, 문서화만).
- **확인 필요(재확인 권장)**: 위 5건/48건/58건/50건은 파일 기준 정확치. **DB에 실제 반영됐는지**는
  `python -m db.init_db` 재실행 여부에 달려있음 — 아래 ④ 참고.

---

## ④ PCAF 품질규칙 — `pcaf_quality_rules` 테이블 (`db/models.py`)

- **db/init_db.py에는 아직 `seed_pcaf_quality_rules` 함수가 없음** — 이 세션에서 `db/init_db.py`
  원문을 직접 확인한 결과, 현재 시드 대상은 `배출계수`·`환산단가`·`업종분포` 3종뿐이다.
  PCAF 품질규칙 시드는 `docs/v1-plan.md`·`docs/borrower-pcaf-data-plan.md`에 **계획**으로만
  존재하고(§7.7 `pcaf_quality_rules` 테이블 정의는 `db/models.py`에 있음), 실제 시드 함수·데이터는
  아직 코드로 구현되지 않았다.
- **DB 실적재 0건**이라는 이전 확인은 위 사실과 일치함(애초에 채울 코드가 없으니 0건이 당연).
- **필요 작업 (코드, 이번 세션 범위 밖)**: `db/init_db.py`에 `seed_pcaf_quality_rules()` 추가
  → PCAF Part A Business Loans 데이터 품질표(§7.7 규칙 단위) 원문 옵션을 시드해야 함.

---

## ⑤ 기타 (DB 상태, 이전 확인 기준 — 이 세션에서 재검증 못함)

| 테이블 | 상태 | 비고 |
| --- | --- | --- |
| `industry_distributions` | 4건 | `db/init_db.py::seed_industry_distributions`, 하드코딩·목업(Excel 소스 없음) |
| `llm_cache` | 6건 | 캐시 웜업 부분적 — `scripts/warm_cache.py`로 사전 적재하는 정식 기능 |
| `trace_logs` | 10건 | 에이전트 실행 시 생성됨 |
| `financial_institutions` | 확인 필요 | v1 신규 테이블 |
| `organizational_boundaries` | **0건 (추정)** | 0건이면 PCAF 품질평가 API(`POST /evaluate`)가 조직경계 없이 409 에러 발생 — 시연 전 최소 1건 등록 필요 |

---

## 결론 — 다음에 할 일

**이번 세션에서 완료됨:**
- [x] 분류 강건성 테스트 전표 300건 생성 (`data/synth_vouchers_300.csv`)
- [x] 회계 마스터 엑셀에 K-택소노미·설비투자·HITL·중복업로드 시나리오 9건 확장
      (`data/감탄_데이터준비_샘플.xlsx`, 원본은 `_원본백업.xlsx`로 보존)
- [x] 배출계수(5)·월별단가(48)·분류규칙(58)·기대결과(50) 정상 파싱 재확인

**아직 필요함 (실행/코드 — 이 세션 범위 밖):**
- [ ] `python -m db.init_db` 재실행 — DB에 최신 배출계수·환산단가(확장분 포함) 반영.
      이 세션엔 `DATABASE_URL`이 없어 직접 실행 불가, 사용자 환경에서 실행 필요
- [ ] `db/init_db.py`에 `seed_pcaf_quality_rules()` 함수 신규 구현 (현재 코드에 없음)
- [ ] `organizational_boundaries` 최소 1건 등록 (PCAF 품질평가 API 409 방지)
- [ ] `synth_vouchers_300.csv`의 DB 적재 여부는 3단계 검증(8/4~8/10) 착수 시 결정
- [ ] 신규 8개 참고 시트(`company_master` 등)를 실제 DB에 반영하려면 별도 로더 코드 필요 —
      현재는 순수 참고·발표 자료
