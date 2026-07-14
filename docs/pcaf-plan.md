# 도구②(전표 분류)·도구③(계산+PCAF) 구현 계획 — 프론트 실데이터화

## Context

`web/components/SceneClassify.tsx`(장면③)와 `web/components/ScenePcaf.tsx`(장면④)가 완전히 하드코딩된 배열/숫자를 보여주고 있다. 원인은 백엔드에 도구②(룰+LLM 분류)와 도구③(결정론적 계산+PCAF 등급)이 전혀 구현되어 있지 않기 때문(`api/agent/tools.py`에 TODO만 존재, `llm_cache`/`classifications` 테이블 모두 0건). 오늘은 스프린트 D7("도구 4종 순차 E2E") 목표일이라 이 두 도구를 실제로 구현해 장면③④를 실데이터로 바꾼다.

조사로 확정된 사항:
- `data/*.xlsx`의 `분류_기준표_확장` 시트(50개 룰)를 룰 엔진 입력으로 쓴다. 키워드는 콤마 구분, `자동처리` 컬럼은 5종(자동분류/검토후분류/사람검토/자동제외/참고분류).
- `기대_결과` 시트는 100건이 아니라 **40건만** 채워져 있다 — 계산 엔진 단위테스트 fixture로 이 40건을 쓴다.
- "외 1종" 혼합 품목은 **주 품목 100% 귀속** (분할 없음) — R028/R029 원칙, I001/I023으로 검증됨.
- 전기(kWh)·LPG 단가가 `기대_결과`의 암시적 가정과 어긋남(전기 ~2.1배, LPG ~11~14%) — **현재 엑셀(배출계수 시트) 단가를 그대로 쓰고, 소스 문구·PR 설명에 회계 확인 필요로 플래그만 남긴다.** 단위테스트는 이 오차를 감안해 연료별로 허용오차를 다르게 둔다.
- **도구②(전표 분류) LLM은 Claude가 아니라 Gemini로 변경** (`google-genai` SDK, `gemini-2.5-flash`, `.env`의 `GEMINI_API_KEY` — 키는 사용자가 직접 입력). `requirements.txt`에 `anthropic`은 두고 `google-genai`를 추가(에이전트 오케스트레이터는 8월에 별도 결정, 이번엔 분류만 Gemini로 변경). CLAUDE.md §3 LLM 스택 문구를 이 범위로 갱신한다.
- **PCAF 1~5등급 산정 공식이 프로젝트 어디에도 없어 이번에 새로 설계**(아래 §PCAF 설계). 회계 담당 확인 전까지 임시안으로 코드에 명시.
- 데모 기업 `○○정밀`의 실제 DB id = `2` (프론트 `COMPANY_ID`와 일치, 별도 조치 불필요).

## 아키텍처 개요

```
전표(voucher)
  → [룰 엔진] 분류_기준표_확장 50개 키워드 매칭 (db/excel_loader.load_classification_rules)
      ├─ 자동분류/자동제외/참고분류 → 즉시 확정 (LLM 미사용)
      └─ 검토후분류/사람검토/미매칭 → [LLM 분류] Gemini 호출 (api/agent/llm_classify.py, llm_cache 래핑)
  → Classification row 저장 (scope/category/fuel_type/amount_krw/method/confidence/evidence/status)
  → [계산 엔진] activity_amount = amount_krw ÷ unit_price, emission_co2e = activity_amount × factor
    (db/calc_engine.py, 순수 함수 + Pydantic 검증 + 단위테스트)
  → Classification row에 activity_amount/activity_unit/emission_co2e 채워 갱신

PCAF 집계 (읽기 전용, 저장된 Classification 사용)
  → db/pcaf.py: 등급 산정 + 결손월 industry_distributions 평균으로 온더플라이 보정
  → GET /pcaf/{company_id}
```

## 신규/변경 파일

### 1. `db/excel_loader.py` (변경 — 함수 추가)
- `load_classification_rules(path) -> list[dict]`: `분류_기준표_확장` 시트 50행 파싱. 반환 키: `rule_id, priority, scope(1|2|None), category, fuel_type, auto_action, needs_review(bool), mixed_item(bool), quality_grade, include_keywords(list[str]), exclude_keywords(list[str]), reasoning, example`. 키워드는 `,` split 후 strip.
- `load_expected_results(path) -> list[dict]`: `기대_결과` 시트 40행 파싱(빈 행 스킵) → 계산 엔진 테스트 fixture. 반환 키: `voucher_id, item, scope, fuel, amount_krw, activity_amount, unit, factor, expected_emission_kgco2e, needs_review, reason`.

### 2. `api/agent/rules.py` (신규)
- `match_rule(item_description: str, rules: list[dict]) -> dict | None`: priority 오름차순 → rule_id 오름차순으로 정렬된 rules에서, `include_keywords` 중 하나라도 부분일치 AND `exclude_keywords`가 하나도 매치 안 되는 첫 규칙 반환. 매치 없으면 `None`.
- 모듈 로드 시 `load_classification_rules()`를 1회 호출해 정렬된 리스트를 캐싱(회계가 엑셀을 바꾸면 프로세스 재시작으로 반영 — 기존 excel_loader 패턴과 동일 수준).

### 3. `api/agent/llm_classify.py` (신규)
- `classify_with_llm(session, item_description, amount_krw) -> dict`: CLAUDE.md 고정 스키마(`raw_text, scope, category, fuel_type, amount_krw, mixed_item, confidence, evidence`)로 응답받는 Gemini 호출.
  - `hashlib.sha256(item_description.encode()).hexdigest()`로 `llm_cache.text_hash` 조회 → 있으면 `hit_count+=1, last_used_at=now()` 후 즉시 반환(**Gemini 미호출**, 캐시 정식 기능).
  - 캐시 미스: `google.genai` client, `gemini-2.5-flash`, `response_mime_type: application/json` + JSON 스키마 강제(google-genai의 `response_schema`)로 구조화 출력.
  - 프롬프트: 고정 스키마 설명 + Scope1(이동연소/고정연소)·Scope2(간접배출) 정의 + "지게차 경유 외 1종" 예시 + 룰 매칭에서 힌트가 있으면 포함(`rule_hint` optional 파라미터로 확장 — 룰이 애매하다고 표시한 경우 그 reasoning도 프롬프트에 포함).
  - JSON 파싱 실패 시 1회 재시도(CLAUDE.md 규칙) → 그래도 실패하면 `confidence=0.0, status="review_required"`로 HITL.
  - 성공 시 `llm_cache`에 신규 insert.

### 4. `db/calc_engine.py` (신규 — 순수 함수, DB 세션 불필요)
- Pydantic 모델 `ClassifiedItemInput`(fuel_type, scope, amount_krw, year, month) — 입력 검증.
- `index_unit_prices(rows) -> dict[(fuel_type, year, month), float]`, `index_emission_factors(rows) -> dict[(fuel_type, scope), dict]` — DB에서 조회한 `UnitPrice`/`EmissionFactor` 전체 행(각 60·5건, 작으므로 매번 전체 로드 OK)을 인덱싱.
- `compute_emission(item: ClassifiedItemInput, price_index, factor_index) -> dict`: `activity_amount = amount_krw / unit_price`, `emission_co2e_kg = activity_amount * factor_co2`(또는 gwp_co2e), 단위 없거나(scope=None/제외) 매칭 실패 시 `activity_amount=0, emission_co2e=0`을 명시적으로 반환(예외 대신 — 제외 케이스는 정상 흐름).
- 가격/계수 미존재(진짜 데이터 갭)는 예외를 던져 상위에서 HITL로 전환하도록 함.

### 5. `db/pcaf.py` (신규 — PCAF 등급 설계, 임시안)
**등급 정의 (회계 확인 전 임시안, 코드 주석에 명시):**
| 등급 | 조건 |
|---|---|
| 2 | (미사용 — 전표에 실측 물량(L/kWh) 필드가 없어 MVP에서 도달 불가, 향후 확장 자리만 남김) |
| 3 | 실제 전표 존재 + 금액→물량 환산(spend-based) — 정상 분류된 대부분의 케이스 |
| 4 | 분류는 됐으나 `status="review_required"`(HITL 미확정) |
| 5 | 결손월(voucher 자체가 없음) — `industry_distributions` 업종 평균으로 온더플라이 보정 |

- `company_pcaf_summary(session, company_id) -> dict`:
  1. 저장된 `Classification` 전체 조회 (scope 1·2만, 제외 항목 스킵)
  2. `api/queries.get_coverage()` 재사용해 fuel×month 결손 목록 획득
  3. 결손 월은 `IndustryDistribution`(이미 존재하는 함수 `get_distribution` 재사용)의 `emission_median_co2e`를 12개월 배분(÷12)해 등급5로 가산
  4. Scope1/Scope2 합산 배출량(tCO2e) + emission_co2e 가중평균 등급(반올림, 1~5 클립) 산출
  5. "Before" 기준선: `company.revenue_krw` 기반 — 기존 `IndustryDistribution`에 매출 정규화 지표가 있으면 사용, 없으면 `emission_median_per_employee * employee_count`로 근사(항상 등급 5, 실측 아님이므로 계산은 참고용 텍스트만)
  6. 벤치마킹 문구: 동종업종 min/median/max 대비 위치(%) 계산해 반환

### 6. `api/agent/tools.py` (변경 — TODO 자리 채움)
- `classify_vouchers(session, company_id)`: 회사의 미분류 전표(voucher_id가 `classifications`에 없는 것) 순회 → `match_rule` → 자동분류/자동제외/참고분류는 즉시 Classification 생성, 나머지는 `classify_with_llm` 호출 → `compute_emission`으로 activity_amount/emission_co2e 채움 → confidence < 0.7 이면 `status="review_required"`, 아니면 `"auto"` → 세션에 add & commit. 이미 분류된 voucher는 스킵(재실행 안전).
- `calculate_pcaf(session, company_id)`: `db/pcaf.py`의 `company_pcaf_summary` 호출 래퍼.

### 7. `api/routers/classify.py` (신규)
- `POST /classify/{company_id}` → `classify_vouchers` 실행 후 결과 목록 반환.
- `GET /classify/{company_id}` → 저장된 Classification을 voucher와 join해 `{raw, scope, category, fuel, amount, confidence, evidence, hitl, method}` 리스트로 반환 (scope 1/2 + HITL 항목만 — 제외/참고분류는 응답에서 필터링, 감사용으로는 DB에 남아있음).

### 8. `api/routers/pcaf.py` (신규)
- `GET /pcaf/{company_id}` → `calculate_pcaf` 호출, `{before: {grade, emission_tco2e}, after: {grade, scope1, scope2, total}, benchmark: {industry_name, percentile_text}}` 반환.

### 9. `api/main.py` (변경) — 두 라우터 `include_router` 추가.

### 10. `web/components/SceneClassify.tsx` (변경)
- 하드코딩 `ROWS` 제거. `useEffect`로 `GET /classify/{COMPANY_ID}` 조회 → 결과 없으면 "AI 분류 실행" 버튼(장면①의 `connect()` 패턴 재사용) → 클릭 시 `POST /classify/{COMPANY_ID}` → 재조회.
- "제외" 카테고리 항목은 리스트에서 필터링(기존 UI가 scope 1|2만 다루므로), scope 1/2 + HITL만 표시.

### 11. `web/components/ScenePcaf.tsx` (변경)
- 하드코딩 숫자 제거. `useEffect`로 `GET /pcaf/{COMPANY_ID}` 조회해 Before/After 등급·배출량·벤치마킹 문구를 렌더링. 분류 미실행 시(after 데이터 없음) "③ 먼저 실행하세요" 안내 표시.

### 12. `requirements.txt` (변경) — `google-genai`, `pytest` 추가.

### 13. `tests/test_calc_engine.py` (신규)
- `load_expected_results()`의 40건을 fixture로 `compute_emission` 결과와 비교. 경유/도시가스/휘발유/LPG는 tight tolerance(반올림 오차 수준), **전기는 알려진 단가 불일치를 반영해 넉넉한 tolerance(또는 별도 마킹으로 스킵 + 사유 주석)**로 assert.

### 14. `.env` (변경) — `GEMINI_API_KEY=` 빈 값 라인 추가(사용자가 직접 채움). 기존 `DATABASE_URL`은 손대지 않음.

### 15. `CLAUDE.md` (변경) — §3 LLM 행: "전표 분류(도구②)는 Gemini API(google-genai, gemini-2.5-flash)로 변경. 에이전트 오케스트레이터(8월 예정)는 별도 결정 전까지 기존 Claude API tool use 문구 유지"로 갱신.

## 담당 분담 (2인)

도구②(분류)와 도구③(계산+PCAF)은 "Classification row에 무엇을 채우는가"만 합의하면 서로 다른 파일이라 병렬 작업 가능. 유일한 실제 의존점은 `classify_vouchers()`가 계산 결과(activity_amount/emission_co2e)를 채우는 한 지점뿐.

### 개발자 A — 도구② 분류 파이프라인 (룰 + Gemini + 캐시)
- `db/excel_loader.py`: `load_classification_rules()` 함수만 추가
- `api/agent/rules.py` (신규) — 룰 매칭 엔진
- `api/agent/llm_classify.py` (신규) — Gemini 호출 + `llm_cache` 래핑
- `api/agent/tools.py` — `classify_vouchers()` (B의 `compute_emission()`이 아직 없으면 스텁으로 두고 먼저 통합, 나중에 실제 함수로 교체)
- `api/routers/classify.py` (신규) — `POST`/`GET /classify/{company_id}`
- `requirements.txt`(`google-genai`), `.env`(`GEMINI_API_KEY`)
- `web/components/SceneClassify.tsx` 연동
- `CLAUDE.md` §3 LLM 스택 문구(Gemini 관련 부분만)

### 개발자 B — 도구③ 계산 엔진 + PCAF
- `db/excel_loader.py`: `load_expected_results()` 함수만 추가 (A와 같은 파일이지만 다른 함수라 충돌 거의 없음)
- `db/calc_engine.py` (신규) — 순수 계산 함수 + Pydantic 검증. **시그니처를 가장 먼저 확정해서 A에게 공유** (`compute_emission(item, price_index, factor_index) -> dict`)
- `db/pcaf.py` (신규) — PCAF 등급 산정(임시안)
- `api/agent/tools.py` — `calculate_pcaf()`
- `api/routers/pcaf.py` (신규) — `GET /pcaf/{company_id}`
- `requirements.txt`(`pytest`), `tests/test_calc_engine.py`
- `web/components/ScenePcaf.tsx` 연동

### 공동
- `api/main.py` 라우터 등록 — 둘 다 건드리는 파일이라 마지막에 같이 머지하거나, 먼저 끝낸 쪽이 먼저 등록 후 다른 사람은 자기 라우터만 추가
- 통합 테스트(검증 방법 2~4번)는 두 파이프라인이 다 붙은 뒤 같이 확인

## 제외 범위 (이번엔 안 함)
- 에이전트 오케스트레이터(Claude tool use 루프) 자체 — D8~9 별도 작업.
- PCAF 등급 회계 최종 확인 — 이번엔 임시안으로 진행, 코드 주석에 명시.
- 전기/LPG 단가 정정 — 회계에게 플래그만, 엑셀 자체는 안 고침.

## 검증 방법
1. `pytest tests/test_calc_engine.py -v` — 40건 정답지 대비 계산 엔진 검증.
2. `uvicorn api.main:app --reload` 기동 후 `curl -X POST localhost:8000/classify/2` → 33건 전표가 분류되는지, `유류대금`(HITL 대상)이 `review_required`로 빠지는지 확인.
3. `curl localhost:8000/pcaf/2` → grade/emission 값이 채워지는지 확인.
4. `npm run dev`(web) → 사장님 화면 장면③에서 "AI 분류 실행" 클릭 후 evidence·HITL 뱃지가 실제 문구로 뜨는지, 장면④ 숫자가 하드코딩 52.0/38.4가 아닌 계산값으로 바뀌는지 브라우저에서 확인.
