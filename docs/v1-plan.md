# 감탄 v1.0 개발 계획 — PCAF 정식 기반 + ESG 안내 레이어 (병합판)

```text
Status: active-plan
Last updated: 2026-08-13
Superseded by: 없음
Merge note: 2026-08-05판(PCAF Business Loans 정식 산정)과 2026-08-09판(ESG 우대금리·K택소노미)을
            층위로 분리해 병합. feat/db-alembic-migration 브랜치의 기 구현 스키마를 기반 레이어로
            채택하고, 그 위에 안내 레이어를 얹는다.
Scope: 2026년 8월 v1 구현·검증·시연 일정
```

> **진행 현황 (2026-08-12)**
> - §1 D0(`feat/db-alembic-migration` → `dev` 병합) **완료**.
> - 1주차 B 항목(PCAF 품질 후보 규칙 엔진) **완료·병합** — PR #25(`feat/pcaf-quality-rules` → `dev`)
>   `dev` 병합 완료. 상세는 §5-1 참고.
> - 1주차 A 항목(하이브리드 데이터 입력: 마이데이터 5종·연료체크·문서업로드) **완료·병합** — PR #26
>   (`feat/hybrid-data-input-pipeline` → `dev`) `dev` 병합 완료. 상세는 §5-2 참고.
> - 2주차 B 항목(승인요청 큐 + 원본문서 접근 감사 로그) **완료·병합** — PR #28(`dev` 병합),
>   리뷰 지적 2건 수정 PR #29(`dev` 병합) 포함. 상세는 §6-1 참고.
> - PR #28 리뷰 대응 중 발견된 pre-existing 테스트 실패 3건(`test_rules.py` 카운트·I050
>   케이스, `test_alembic_migration.py` 백필 누락) **완료·병합** — PR #30. 상세는 §6-2 참고.
> - 2주차 B "owner 안내 요청 버튼" 잔여 항목 **완료·병합** — PR #31(`ScenePcaf.tsx` 실데이터 연동).
> - `borrower_emission_inventories` 연간 Scope 배출량 집계(1주차 완료조건에서 이월됐던 항목)
>   **완료·병합** — PR #32(`db/pcaf_quality.py::aggregate_scope_emissions`). 상세는 §6-3 참고.
> - 개발자 A: 사장님 앱 홈 화면 + 기업 선택기 + 마이데이터 CSV 실연동 **완료·병합** — PR #33.
> - 개발자 A: OCR mock → 실제 PDF 텍스트 추출 교체 **완료·병합** — PR #34, §5-3 참고.
>   §5-2에서 "OCR은 결정론적 mock"이라 남겼던 전제가 실물 데이터 확인(텍스트 레이어 PDF임을
>   확인)으로 해소됨.
> - 개발자 B: Tier 2 조기 착수 — 품질 이슈 로그(업로드 반려·실패 이력) + 감사 대응 근거
>   패키지(기업·기간별 시계열 원자료 조회, CSV 내보내기) **완료·병합** — PR #37.
>   상세는 §7-1 참고. CSV만 우선 구현, PDF 서술형 감사보고서는 범위 밖.
> - 개발자 B: 2주차 A 항목(K택소노미·설비투자 필드) 백엔드만 대신 착수 — `Classification`에
>   4개 필드 추가, 회계 매핑표(Excel)와 기존 룰 매칭(R051~R058, R031, R032)을 연결
>   **완료·병합** — PR #39(`feat/k-taxonomy-equipment-fields` → `dev`). 상세는 §6-5 참고.
> - 개발자 A: 2주차 A 항목의 남은 프론트 2건 — K택소노미 리드 리스트(관리자)와
>   `ScenePcaf.tsx` 정식 엔진(`db/pcaf_quality.py`) 교체 — **완료·병합**. PR #41(리드
>   리스트), PR #42(정식 엔진 교체 — 조직경계 자동 생성 + 사장님용 리포트 래퍼 + 프론트
>   재설계), 후속 UI 다듬기 PR #40·#43~#47(우대금리 후보 판정 정식 엔진 정렬 포함).
>   **2주차 Tier 1이 전부 끝났다.** 상세는 §6-6 참고.
> - `dev` 최신 기준 `pytest` 225 passed, 3 skipped(회귀 없음).
> - ~~`test_backfill_assigns_default_institution_to_all_existing_vouchers` 실패~~ —
>   **해소.** 원인 조사 결과 코드 버그가 아니라 공유 Supabase DB에 스크립트 경로 밖에서
>   수동으로 만들어진 테스트 전표 1건(company_id=10 "임시기업", "태양광 설비 설치",
>   `institution_borrowers`엔 정상 귀속이 있었음)이 원인 — 그 귀속값으로 UPDATE 백필해
>   해결(사용자 확인 후 진행). PR #30과 달리 코드 수정은 불필요했음.

> 기준 브랜치: `dev` (병합 대상: `feat/db-alembic-migration`)
>
> 결선 목표: 2026년 8월 말 (1박 2일 결선 해커톤)
>
> 팀 구성: 풀스택 개발자 2명(A·B) + 회계·도메인 1명(데이터 작업 중)

---

## 0. 왜 병합인가

`docs/borrower-pcaf-data-plan.md`(PCAF Business Loans 정식 금융배출량 산정)와 이 대화에서 설계한 ESG 우대금리·K택소노미 연계 기능은 **실제로 상충하지 않는다.** 구 계획이 명시적으로 금지한 건 "AI가 등급을 근거로 우대금리를 자동 보장하는 것"이지, "우대금리 안내를 아예 하지 않는 것"이 아니다. 구 계획의 대체 문구를 다시 보면:

> "실제 활동자료 비율과 인벤토리 완전성을 높이기 위해 부족한 문서·월·배출원을 안내한다. 이 안내는 PCAF 점수 상승이나 우대금리 자격을 보장하지 않는다."

이건 이번 대화에서 정한 "우대금리는 안내까지만, 승인은 사람"이라는 원칙과 **같은 방향**이다. 차이는 구 계획이 더 보수적으로 우대금리 언급 자체를 피했다는 정도다. 따라서:

- **기반 레이어(이미 구현됨, 건드리지 않음)**: `feat/db-alembic-migration`의 금융기관·포트폴리오·조직경계·차주 인벤토리·익스포저 스키마, PCAF Business Loans 규칙기반 데이터 품질 후보
- **안내 레이어(이 대화에서 신규 설계, 위에 얹음)**: K택소노미·설비투자 스크리닝, 하이브리드 데이터입력, 우대금리·설비금융 "안내"(비보장 명시), 관리자 플로우 재구성, 창의성 기능

두 레이어는 서로 다른 질문에 답한다. 기반 레이어는 "이 데이터가 PCAF 기준으로 얼마나 신뢰할 만한가"를, 안내 레이어는 "이 데이터로 무엇을 안내할 수 있는가"를 다룬다.

---

## 1. 통합 착수 — D0 (가장 먼저 할 일)

**✅ 완료 (2026-08-12 이전).** `feat/db-alembic-migration`은 `dev`에 병합됐고, 마이그레이션·기존
테스트 4종(`test_alembic_migration.py`, `test_tenant_isolation.py`, `test_inventory_versioning.py`,
`test_exposure_unique_constraint.py`)이 통과함을 확인했다. 아래 절차는 기록용으로 남긴다.

```bash
git checkout dev
git merge feat/db-alembic-migration   # 6개 커밋: Alembic·기관/포트폴리오/인벤토리/익스포저 스키마
# 충돌 시 db/models.py, api/main.py 우선 검토 후 팀 확인
git log --oneline -10                 # 병합 확인
alembic upgrade head                  # 빈 DB에서 마이그레이션 성공 확인
```

병합 후 기존 `voucher`·`classification` 데이터가 보존되는지, 기관 귀속 필드 백필이 정상 적용됐는지 확인한다(이미 `18422d0` 커밋에 관련 테스트가 있으니 `pytest tests/test_alembic_migration.py tests/test_tenant_isolation.py tests/test_inventory_versioning.py tests/test_exposure_unique_constraint.py`로 재확인).

---

## 2. v1 제품 정의

> 감탄은 중소기업의 세금계산서·전기고지서·도시가스고지서를 AI 에이전트가 읽어 PCAF Business Loans 기준의 차주 데이터 품질 후보와 Scope 1·2 인벤토리를 생성하고(기반 레이어), K-택소노미 적합성·설비투자 여부를 함께 판별해 은행의 우대금리·설비금융 안내로 연결하는(안내 레이어) 시스템이다.

### 확정 스코프

**Tier 0 (이미 완료 — 재작업 금지)**

- Alembic 마이그레이션, 금융기관·사용자·기관-차주·포트폴리오 테이블
- 조직경계·원본문서·차주 인벤토리·가스별 배출량 테이블
- 기업대출 익스포저·차주 재무정보·환율 테이블
- voucher·classification 기관 귀속 필드, tenant 격리

**Tier 1 (필수 — 이번 달 반드시)**

1. 검증 3수치 확정 (분류 정확도, 트랙A MAPE, 트랙B 실물대조 오차)
2. PCAF Business Loans 품질 후보 규칙 엔진 (구 2주차 계획 채택 — 임시 1~5등급 대신 규칙기반)
3. 하이브리드 데이터 입력: 공공 마이데이터 5종 + 파일 업로드(OCR) 3종 + 연료 유형 체크 → 차주 인벤토리 테이블에 적재
4. 대량 전표 / 홈택스 엑셀 업로드
5. K-택소노미 스크리닝 필드 + 설비투자 탐지 필드 (LLM 분류 출력 확장, classification 테이블에 추가 컬럼)
6. 관리자 플로우: HITL 큐 / 승인요청 큐 분리, 포트폴리오 뷰 (화면별 상세는 `docs/owner-admin-flow-spec.md` 은행 담당자 §2~5 참고 — 단 그 문서의 히트맵·Top10·감사패키지는 Tier 2~3 항목이라 이 Tier 1 범위엔 포함 안 됨)
7. 감사 로그 (기존 트레이스 로그 + 원본문서 접근 로그 확장)

**Tier 2 (여유 되면)**

8. 우대금리·설비금융 "안내" — 데이터 완전성·K택소노미 적합성 기준, **PCAF 등급 상승이나 자격을 보장하지 않는다는 문구 필수 동반** (사장님 화면 상세: `docs/owner-admin-flow-spec.md` 기업 §4-1·§4-3)
9. 되묻는 HITL / 청중별 통역 / PCAF 데이터 품질 실시간 지표화(초안→확정 알림) / 탄소 신용카드(QR) (되묻는 HITL 관련 미결정 논의는 `docs/hitl-owner-action.md` 참고)

**Tier 3 (자를 후보, 비전 슬라이드로만)**

10. 기업대출 금융배출량(귀속계수) 계산 — 은행 포트폴리오 집계용, 구 3주차 계획대로 진행 여부는 시간 보고 결정
11. `business_loans_readiness` 체크리스트 — 시간 되면 4주차
12. 월간 AI 브리핑, 장비개선 시뮬레이터, 지역집중 리스크 히트맵, 그린 임팩트 예금 — 히트맵·연동 우선순위 Top10·감사 대응 근거 패키지의 화면 상세 설계는 `docs/owner-admin-flow-spec.md` 은행 담당자 §5·§8에 있음(아직 이 Tier 배정 자체가 바뀐 건 아님)

### v1 제외 범위

- **PCAF 점수 기반 우대금리 자동판정** — AI가 등급만으로 금리를 확정하지 않는다 (기반 레이어 원칙 그대로 승계)
- Scope 3 전체 자동산정
- 상장기업 EVIC 방식, 부동산·PF·차량 등 타 자산군
- 은행 전체 자산군의 공식 PCAF 공시 확정, 외부 assurance
- 성과·감축률 기반 기업 스코어링 (배정 우선순위는 데이터 완전성만)
- 리빗 방식의 공급사별 개별 계정 연동(스크래핑)

---

## 3. 핵심 설계 원칙 (두 판 공통, 불변)

1. LLM은 분류·추출·증빙 탐색·설명 초안에만 사용한다. 배출량·귀속계수·품질 후보 판정은 결정론적 코드로 계산한다.
2. 처리 순서: 룰/키워드 매칭 먼저 → 애매한 건만 LLM → confidence 미달 → HITL 큐.
3. 오케스트레이터는 코드 우선이다. 실행 순서는 결정론적이고, 판단이 필요한 지점만 LLM을 호출한다.
4. 모든 판단에 evidence를 남긴다. HITL 이력, AI 자동반려 이력, 원본문서 접근 이력을 감사 로그로 보존한다.
5. 실패를 목업으로 숨기지 않는다. 오류·재검토 상태를 그대로 노출한다.
6. **우대금리·설비금융 안내는 등급·데이터 완전성 개선을 제안할 뿐, 자격이나 등급 상승을 보장하지 않는다.** 최종 승인은 은행 담당자가 한다.
7. 배정·아웃리치 우선순위는 데이터 완전성 지표만 사용한다. 감축 실적 기반 순위는 금지한다.
8. 연료 유형은 기업이 직접 체크한다. 체크하지 않은 연료의 결손은 알림 대상에서 제외한다.
9. 미산정 Scope와 미확인 가스는 0으로 합산하지 않는다.
10. 승인된 인벤토리·품질 후보는 덮어쓰지 않고 새 버전으로 재산정한다.
11. 다른 금융기관의 데이터에 접근할 수 없다 (tenant 격리).

---

## 4. 역할 분담

|                 | 담당                                                                                                                                           |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **개발자 A**    | 사장님 플로우: 하이브리드 데이터입력(마이데이터·업로드·연료체크) → 차주 인벤토리 적재 → K택소노미/설비투자 스크리닝 → 안내 레이어 화면         |
| **개발자 B**    | 기반 레이어 완성 + 관리자 플로우: PCAF 품질 후보 규칙 엔진, 인벤토리 완전성 집계, HITL 큐/승인요청 큐, 포트폴리오 뷰, 감사 로그                |
| **회계·도메인** | K-택소노미 매핑표·설비 키워드 사전·"외 1종" 배분규칙(선행, 개발 착수 전제) → PCAF Business Loans 품질 규칙 검수 → 정답지 라벨링 → 발표자료·Q&A |

공용 파일(`db/models.py`, `api/main.py`, Alembic revision, LLM 출력 스키마)은 작업 전 담당을 한 명으로 지정한다. 이미 `feat/db-alembic-migration`에서 `db/models.py`에 330줄이 추가돼 있으므로, 신규 컬럼(K택소노미·설비투자 필드)은 그 위에 추가하는 마이그레이션으로 작성한다(새 revision 파일, 기존 revision 수정 금지).

---

## 5. 1주차 (병합 직후 ~ 1주) — 기반 완성 + 안내 레이어 착수

### 목표

병합된 기반 스키마 위에서 PCAF 품질 후보 규칙 엔진을 완성하고, 안내 레이어의 데이터 입력 구조에 착수한다.

| 담당    | 작업                                                                                                                                                                       | 검증                                                               | 상태 |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ---- |
| 공통 D0 | §1 병합 절차 수행                                                                                                                                                          | 마이그레이션·기존 테스트 4종 통과                                  | ✅ 완료 |
| B       | `pcaf_quality_rules` 시드와 규칙 엔진, Scope 1·2/Scope 3 품질 후보 분리, 완전성과 품질 후보 분리                                                                           | PCAF 원문 규칙별 골든 케이스                                       | ✅ 완료 — PR #25 `dev` 병합(§5-1) |
| A       | 공공 마이데이터 5종 Mock, 연료 유형 체크 UI, 파일 업로드(OCR mock) 3종, 홈택스 엑셀 파서 → `source_documents`/`vouchers`(기존 파이프라인 재사용) + `borrower_financials`(표준재무제표증명)에 매핑 | 업로드 데이터가 `source_documents`/`vouchers`/`borrower_financials`에 정확히 적재되는지 확인 | ✅ 완료 — PR #26 `dev` 병합(§5-2) |
| 회계    | K택소노미 100개 활동 매핑표, 설비 키워드 사전, "외 1종" 배분규칙 확정 —**개발 착수 전제조건**                                                                              | —                                                                  | 진행 예정 |

### 1주차 완료조건

- `feat/db-alembic-migration` 병합 완료, 기존 데이터 보존 확인 — ✅ 완료
- PCAF 품질 후보가 규칙 코드·근거와 함께 산정된다 (임시 1~5등급 표기 제거) — ✅ 완료. 단 `ScenePcaf.tsx`(사장님 리포트 화면)는 아직 구 엔진 `db/pcaf.py::company_pcaf_summary()`를 쓴다 — 정식 엔진(`db/pcaf_quality.py`)으로 교체는 2주차 A 항목으로 이월, 아직 미착수(§6 참고).
- 하이브리드 입력 데이터가 기존 차주 인벤토리 스키마에 정합적으로 적재된다 — ✅ **완료.** A의 1주차 구현(`source_documents`→`vouchers`, §5-2)에 이어, `borrower_emission_inventories`를 채우는 연간 Scope 집계 로직도 PR #32(§6-3)로 완료돼 최종적으로 두 경로 모두 정합적으로 적재된다.

### 5-1. PCAF 품질 후보 규칙 엔진 — 구현 상세 (PR #25)

`db/pcaf.py`(Classification 기반 임시 1~5등급)는 그대로 두고, `db/pcaf_quality.py`를 새로
추가해 PCAF Standard Part A Third Edition, Table 10.1-2(Annex p.192) 원문 옵션 체계를
새 스키마(`BorrowerEmissionInventory`, `PcafQualityRule`) 기준으로 병행 구현했다.

- **원문 대조 결과 바로잡은 점**: 최초 시도는 Scope 1·2와 Scope 3에 별도 규칙셋을 두는
  구조였으나, 원문은 하나의 옵션 체계(1a/1b/2a/2b/3a/3b/3c)를 Scope 1·2·3에 공통 적용하고
  Option 2a(energy_consumption)만 각주 208에 의해 Scope 3에 적용 불가하다. 이 구조 오류를
  발견한 뒤 모델·마이그레이션(`0007_pcaf_quality_rules.py` 재작성)·시드 데이터·
  `db/pcaf_quality.py`·`api/routers/quality.py`·테스트를 전부 원문 기준으로 재작업했다.
- **분류 신뢰도(HITL)와 PCAF 데이터 품질 점수는 완전히 분리된 축**(§6.1) — `db/pcaf_quality.py`의
  함수들은 `Classification.confidence`/`status`를 입력으로 받지 않는다.
- **API**: `GET/POST /borrowers/{company_id}/quality-assessments/{year}[/evaluate]`.
  `status`는 항상 `candidate` — 은행 담당자 승인 전 자동 확정 없음(원칙6).
  조직경계 미등록 시 목업 대신 409로 명확히 실패(원칙5).
- **회계 검수 필요 사항** (원문이 이 프로젝트 데이터로 완전히 특정하지 못하는 지점):
  전표 수량 유무만으로 Option 2a(에너지소비량)와 2b(생산량)를 구분할 수 없어 보수적으로
  2b(Score 3)로 취급했고, 금액 환산은 Option 3a(매출 기반, Score 4)로 취급했다. 회계 담당이
  이 매핑을 최종 검수해야 한다.
- **부수 반영**: 스코프 밖에서 발견한 `Company.fuel_types_json` drift(원칙8 "연료 유형은
  기업이 직접 체크")를 이번 PR에 정식 반영(`0008_company_fuel_types.py`).
- 테스트: `tests/test_pcaf_quality.py`(16개 골든 케이스), 전체 `pytest` 통과, Supabase 실제 적용 확인.
- PR: https://github.com/noeyish/GamTan/pull/25 (`feat/pcaf-quality-rules` → `dev`, **병합 완료**)

### 5-2. 하이브리드 데이터 입력 파이프라인 — 구현 상세 (PR #26)

기획 회의에서 확인된 사실 정정(마이데이터 5종은 전부 KYB/재무 프로필용이고 배출량 계산에 쓰이는
세금계산서·전기고지서·도시가스고지서는 마이데이터가 아니라 항상 업로드로만 들어온다)을 반영해,
"마이데이터 5종 + 업로드 3종"을 완전히 분리된 두 경로로 구현했다.

- **경로 분리**:
  - 마이데이터 5종(`business-registration`, `vat-tax-base`, `financial-statement`,
    `sme-certificate`, `kepco-payment-history`, `api/mydata_kyb_mock.py::collect_mydata()`)은
    전부 KYB/재무 프로필용 — 표준재무제표증명만 `borrower_financials`에 매핑되고 나머지는
    `source_documents`에만 적재된다. 계산 파이프라인과 무관.
  - 업로드 3종(세금계산서 OCR/엑셀 택1, 전기요금고지서, 도시가스고지서,
    `api/document_ingestion.py::ingest_uploaded_document()`)은 `source_documents` → **에너지
    관련 타입만** `vouchers`로 변환 → **기존 v0.1 `classify_vouchers()`/`calc_engine.py` 파이프라인을
    수정 없이 그대로 재사용**한다. 새 계산 로직을 만들지 않았다.
- **연료 유형 체크**: 사장님이 고른 값을 `Company.fuel_types_json`에 저장(`PATCH
  /owner/{company_id}/fuel-types`), 순수함수 `db/document_requirements.py::required_documents()`가
  이 값을 문서별 필수/선택/해당없음으로 변환 — 프론트(`SceneUpload.tsx`)와 결손 감지 필터
  (`api/queries.py::get_coverage()`)가 둘 다 이 함수를 참조해 로직이 갈라지지 않는다.
- **OCR은 당시 결정론적 mock**(`db/document_extraction.py::extract_document()`) —
  파일 바이트의 SHA 해시로 시드해 항상 같은 입력엔 같은 결과를 내는 합성 데이터였다.
  **PR #34로 실제 PDF 텍스트 추출로 교체됨 — 상세는 §5-3.**
- **기관 귀속**: `api/queries.py::resolve_institution_borrower()`가 `consent_status='active'`인
  `institution_borrowers` 레코드를 찾아 새 `source_documents`/`vouchers`에 채운다 — 동의 철회
  기업의 신규 업로드가 계속 쌓이는 걸 막는다.
- **동시성 방어**: `source_documents`에 `(company_id, file_hash)` 유니크 제약, `borrower_financials`에
  `(company_id, financial_year, version)` 유니크 제약을 걸어(`0010_upload_dedup_constraints.py`)
  앱 레벨 SELECT-then-INSERT 중복 체크가 못 잡는 동시 업로드(더블클릭·재시도) 레이스를 DB 레벨에서
  막는다. 개발 중 자체 회귀 테스트로 `session.get()`의 autoflush가 방어 로직보다 먼저 예외를
  터뜨리는 타이밍 버그를 발견해 수정했다.
- **킬러씬 보호**: ○○정밀 데모 시나리오(3~5월 도시가스 결손, 7월 경유 이상치)는 새 연료체크
  UI가 기본값을 잘못 추론해 깨지지 않도록, `SceneUpload.tsx`가 마운트 시 기존 `coverage` 응답에서
  연료 기본값을 역추론하는 방어 로직을 둔다.
- **범위 밖으로 남긴 것**: `borrower_emission_inventories`(연간 Scope 집계) 적재는 하지 않음 — 위
  1주차 완료조건 참고. K택소노미·설비투자 필드 확장은 2주차(§6) 그대로 유지.
- 테스트: `test_document_requirements.py`, `test_resolve_institution_borrower.py`,
  `test_document_extraction.py`, `test_hometax_excel_parser.py`, `test_document_ingestion.py`,
  `test_mydata_kyb_mock.py`, `test_owner_document_upload.py`, `test_owner_fuel_types.py`,
  `test_owner_coverage.py`, `test_mock_mydata_router.py` 등 신규, 전체 `pytest` 통과.
- PR: https://github.com/noeyish/GamTan/pull/26 (`feat/hybrid-data-input-pipeline` → `dev`, **병합 완료**)

### 5-3. 실제 PDF 텍스트 추출로 OCR mock 교체 (PR #34)

회계 담당 업로드 서류(`data/업로드서류/`)가 스캔 이미지가 아니라 reportlab로 그린 텍스트
레이어 PDF라는 게 확인돼, pdfplumber로 문서종류·날짜·금액·수량을 그대로 읽을 수 있음이
드러났다(OCR·비전 모델 불필요) — §5-2에서 남겨뒀던 "OCR mock" 전제가 실물 데이터
확인으로 바뀐 경우.

- `db/document_text_extractor.py` 신규: PDF 텍스트에서 문서종류·날짜·금액·수량을 정규식으로
  파싱. 기대한 문서종류와 실제 내용이 다르면(엉뚱한 칸에 업로드) 명확히 실패, 저품질 스캔처럼
  금액이 판독 불가로 가려진 경우도 값을 지어내지 않고 실패시킨다(CLAUDE.md 실패 가시성 원칙).
- `db/document_extraction.py`: 실 추출을 우선하고, `year`/`month`가 명시적으로 주어졌을 때만
  기존 해시 기반 합성 mock으로 폴백(테스트·임의 파일 업로드 편의는 유지).
- `api/document_ingestion.py`, `api/routers/owner.py`: `year`/`month`가 선택값으로 전환 —
  문서에서 읽어낸 값을 응답에 실어 보낸다. 파싱 실패는 422로 안내.
- `web/components/SceneUpload.tsx`: 월별 업로드 UI를 여러 파일 일괄 업로드로 교체(월 선택
  드롭다운 제거), 응답으로 받은 월을 배지에 표시. 실패 사유(화질 불량·잘못된 칸 등)를 실제
  메시지로 노출. "빠진 데이터" 경고 배너 제거.
- `requirements.txt`에 `pdfplumber`(실 추출)·`reportlab`(생성기 재현) 추가.
- 테스트: 신규 `test_document_text_extractor.py` + 기존 3개 갱신, 전체 `pytest` 174 passed.
  실제 생성 PDF로 브라우저 end-to-end 검증(여러 파일 동시 업로드 → 각 파일 실제 날짜 정확히
  인식, 저품질 스캔·중복 업로드 실패 메시지 정상 노출).
- PR: https://github.com/noeyish/GamTan/pull/34 (`feat/upload-real-pdf-extraction` → `dev`, **병합 완료**)

---

## 6. 2주차 — K택소노미·설비투자 + 관리자 플로우

> **진행 현황**: `dev`에는 이미 관리자 대시보드 HITL 큐(대량처리·필터·변경이력/감사로그 탭 —
> `63f9202`, `c8e4082`, `17b398b`)와 등급 상승 역산 API skeleton(`e7c229c`, `0f920b3`)이
> 병합 계획보다 앞서 반영돼 있다. B 항목("승인요청 큐(우대금리·설비금융, 비보장 문구)"를
> 기존 HITL 큐와 명확히 분리)은 PR #28·#29로 완료·병합됐다. 이어서 owner 쪽 버튼 UI(PR #31),
> pre-existing 테스트 3건 정리(PR #30), 인벤토리 집계(PR #32)까지 마무리됐다 — 상세는
> §6-1·§6-2·§6-3. **2주차 Tier 1이 전부 끝났다** — K택소노미·설비투자 필드(원래 A 담당)는
> 개발자 B가 대신 백엔드만 착수해 완료(§6-5, PR #39). 남은 프론트 2건(리드 리스트,
> `ScenePcaf.tsx` 정식 엔진 교체)도 완료됐다(§6-6, PR #41 + 후속).

| 담당 | 작업                                                                                                                                  | 검증                                                  | 상태 |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---- |
| A/B  | K택소노미·설비투자 필드를 classification 테이블에 추가(신규 Alembic revision), LLM 분류 프롬프트 확장 여부 검토. ~~결손 감지에 연료유형 필터 반영~~은 PR #26에서 선행 완료(`api/queries.py::get_coverage()`) | 기존 classification 회귀 테스트 통과 + 신규 필드 검증 | ✅ 완료 — PR #39 병합(§6-5). LLM 프롬프트 확장은 불필요로 결론 |
| A    | K택소노미 리드 리스트(관리자 화면) + `ScenePcaf.tsx`를 구 엔진(`db/pcaf.py`)에서 정식 엔진(`db/pcaf_quality.py`)으로 교체 | 관리자 대시보드 새 탭 렌더 확인, 사장님 리포트 Scope별 품질점수 실데이터 확인 | ✅ 완료 — PR #41 + 조직경계 자동생성/리포트 래퍼/프론트 재설계(§6-6) |
| B    | 관리자 대시보드: HITL 큐(분류 신뢰도, 기 구현)와 승인요청 큐(우대금리·설비금융, 비보장 문구 포함, 신규)를 명확히 분리, 원본문서 접근 감사 로그 확장 | 두 큐 혼동 없음, 반려 로그 자동/담당자 구분           | ✅ 완료 — PR #28·#29 병합(§6-1) |
| 회계 | 정답지 라벨링, PCAF 품질 규칙 검수                                                                                                    | —                                                     | ✅ 진행 중 — `data/감탄_데이터준비_샘플.xlsx` 확장(I042~I050, R051~R058, K택소노미/설비 신규 시트 8개) 반영 확인. `README_확장내역` 시트 참고 |

### 처리 흐름

```text
사장님 업로드 → AI 처리(기존 인벤토리 파이프라인) → 저신뢰 분류 → HITL 큐
관리자 HITL 완료 → 사장님 리포트 확정 알림

사장님이 우대금리/설비금융 안내 클릭 → 승인요청 큐
관리자 승인/반려 (안내 문구에 "등급 상승·자격 보장 아님" 항상 동반) → 사장님 화면 반영
```

### 2주차 완료조건

- K택소노미·설비투자 필드가 기존 계산 로직을 깨지 않는다. — ✅ 완료(§6-5, 테스트로 검증). 프론트(리드 리스트, `ScenePcaf.tsx` 교체)도 완료(§6-6)
- 안내 문구에 항상 비보장 고지가 포함된다. — ✅ 완료(테스트로 검증, §6-1)
- HITL 큐와 승인요청 큐가 분리된 데이터·화면으로 존재한다. — ✅ 완료(§6-1)

### 6-1. 승인요청 큐 + 원본문서 접근 감사 로그 — 구현 상세 (PR #28)

- **모델 2개 신규**: `RateApprovalRequest`(사장님 요청 → 담당자 승인/반려), `SourceDocumentAccessLog`
  (원본문서 열람 사실 자체의 기록 — 기존 review-log는 "확정/반려했다"는 조치 기록이라 열람
  이벤트를 못 담았다). 마이그레이션 `0011_rate_approval_and_access_log.py`.
- **판정 로직 재사용**: 기존 `db/pcaf.py::rate_upgrade_candidates`(전체 기업 순회, 읽기 전용
  안내 목록)를 단일 기업 판정 함수 `upgrade_candidate_for_company`로 리팩터링해, 요청 생성
  시점에 동일 판정 로직으로 등급 스냅샷(`current_grade`/`target_grade`/`missing_summary`)을
  저장한다 — 로직 중복 없음, 이후 재산정과 무관하게 요청 당시 근거가 감사 가능하게 남는다.
- **여신 결정 아님(CLAUDE.md §9)**: 승인은 "안내 대상으로 확인했다"는 담당자 수동 확인일
  뿐이며, 승인/반려 응답에는 항상 비보장 문구(`disclaimer_text`)가 동반된다(원칙6).
- **API**: `GET/POST /owner/{company_id}/rate-candidate|rate-requests`,
  `GET/PATCH /admin/rate-requests[...]`, `GET /admin/documents/{id}(조회 시 자동 기록)|access-log`.
- **관리자 대시보드**: "승인요청" 탭 신규(`ApprovalQueue.tsx`), "변경 이력" 탭에
  `DocumentAccessLog.tsx` 추가 — 기존 `AuditLog`(분류 확정/반려)와 나란히 배치해 두 감사
  로그의 성격 차이(조치 vs 열람)를 화면에서도 분리했다.
- **병행 처리(2주차 B 스코프 밖, 사용자 요청으로 같이 진행)**: Docker 이미지 경량화 —
  `api.Dockerfile`에서 `data/` COPY 제거(compose가 이미 볼륨 마운트, 이미지 중복 방지),
  pip/npm 캐시 마운트 추가, 미사용 `anthropic` 패키지 제거. 실측: API 이미지
  412MB→395MB, 캐시 재빌드 17.6s→0.76s, web 캐시 재빌드 37s→1.25s.
- 테스트: `tests/test_rate_approval_queue.py` 18건(순수 로직 6 + API 라우터 12, HITL 큐와의
  데이터 분리 포함). 전체 `pytest` 140 passed, 3 skipped. 프론트 `tsc --noEmit`·`next build` 통과.
- 리뷰 지적 2건(PR #29, `fix/rate-approval-review-bugs` → `dev`, 병합 완료)도 함께 반영:
  `request_type` 미검증 시 500이 나던 걸 `Literal` 타입으로 422 전환, 이미 처리된 요청
  재처리 시 조용히 성공하던 걸 `AlreadyProcessedError`로 항상 409가 나도록 수정.
- PR: https://github.com/noeyish/GamTan/pull/28 (`feat/admin-approval-queue` → `dev`, **병합 완료**),
  https://github.com/noeyish/GamTan/pull/29 (`fix/rate-approval-review-bugs` → `dev`, **병합 완료**)

### 6-2. pre-existing 테스트 실패 3건 정리 (PR #30)

PR #28/#29 리뷰 대응 중 발견된, 이번 작업과 무관한 기존 실패 3건을 정리했다.

- `test_rules.py::test_expected_results_has_rows`: 카운트 하드코딩(41)이 PR #27(합성
  데이터 확장)로 늘어난 실제 Excel 행 수(50)와 어긋남 — 갱신.
- `test_rules.py::test_auto_classified_rows_match_expected_scope_and_fuel`: 룰 매칭
  버그가 아니었다. I050("지게차 경유 외 1종")은 I001과 품목명·금액이 완전히 동일한
  "중복 업로드 문서" 검증용 케이스라, 룰 엔진(품목 텍스트만 입력)은 원리적으로 이 둘을
  구분할 수 없다 — 중복 방지는 `source_documents.file_hash` UQ 제약(§14, db-schema.md)이
  전담하는 영역. 테스트에서 I050을 룰 엔진 검증 대상에서 명시적으로 제외했다. **회계
  담당이 이후 이 케이스를 README_확장내역 시트에 "동일 전표 중복 업로드(자동 제외)"로
  명시해 같은 결론을 확인해줬다.**
- `test_alembic_migration.py::test_backfill_assigns_default_institution_to_all_existing_vouchers`:
  `db/seed_mock.py`가 0006 마이그레이션 이후 재실행되며 만든 신규 전표가
  `financial_institution_id`를 안 채우고 있었다 — `_resolve_demo_institution_borrower()`
  추가로 향후 재시드부터 정상 채워지도록 수정, Supabase 기존 데이터는 UPDATE로 백필.
- PR: https://github.com/noeyish/GamTan/pull/30 (`fix/rule-matching-i050` → `dev`, **병합 완료**)

### 6-3. `borrower_emission_inventories` 연간 Scope 배출량 집계 (PR #32)

1주차 완료조건에서 이월됐던 "차주 인벤토리 직접 적재" 항목. `BorrowerEmissionInventory`
테이블은 있고 `candidate_quality_score`만 채워지고 있었을 뿐, `emission_tco2e`(실제
배출량)를 계산해 넣는 로직 자체가 없었다.

- `db/pcaf_quality.py`에 `aggregate_scope_emissions(session, company_id, reporting_year,
  scope_group)` 추가 — 전표별 `Classification.emission_co2e`(kg) 합산 → tCO2e. 담당자
  반려 건 제외(`db/pcaf.py::_after_measured`와 동일 규칙). 해당 Scope 전표가 없으면
  None(0 아님). Scope 3는 항상 None + `scope3_status='not_calculated'`(원칙9).
- 기존 `db/pcaf.py::_after_measured`(v0.1 사장님 리포트용, 연도 필터 없이 Scope 1·2
  통합)는 재사용하지 않고, `db/pcaf_quality.py`가 이미 하던 연도·`scope_group` 필터
  조인 패턴(`assess_inventory_completeness`)을 그대로 한 번 더 써서 로직 중복을 피했다.
- `POST /borrowers/{company_id}/quality-assessments/{year}/evaluate`(기존 엔드포인트)가
  `candidate_quality_score`와 함께 이 값도 계산해 저장하도록 확장 — 신규 엔드포인트는
  안 만듦.
- 테스트: 골든 케이스 5건 + API 통합 1건 추가, `tests/test_pcaf_quality.py` 27개 통과.
- PR: https://github.com/noeyish/GamTan/pull/32 (`feat/inventory-aggregation` → `dev`, **병합 완료**)

### 6-4. owner "안내 요청" 버튼 실데이터 연동 (PR #31)

2주차 B 항목의 owner 쪽 잔여 UI. `ScenePcaf.tsx`(리포트 화면, `/owner` 5단계)의 기존
정적 "우대금리 대상 안내" 카드를 실데이터로 교체 — `GET /owner/{company_id}/rate-candidate`
조회 → 후보면 현재/목표 등급·missing·benefit·disclaimer_text 카드 + "우대금리 안내 요청"
버튼 노출, 클릭 시 `POST /owner/{company_id}/rate-requests` → 관리자 승인요청 큐로 전달.
후보 있음/없음 두 분기 모두 `tests/test_rate_approval_queue.py`가 커버.

PR: https://github.com/noeyish/GamTan/pull/31 (`feat/owner-rate-request-ui` → `dev`, **병합 완료**)

### 6-5. K택소노미·설비투자 필드 — 백엔드 (개발자 B 대신 착수)

2주차 유일한 잔여 항목이었던 K택소노미·설비투자 필드를 개발자 B가 백엔드만 대신
착수(사용자 지시 — 프론트는 이번 스코프에서 명시적으로 제외).

- **회계 선행작업은 이미 완료돼 있었다**: `data/감탄_데이터준비_샘플.xlsx`의
  `k_taxonomy_mapping`(KT001~KT009)·`facility_keywords` 시트가 기존 룰(R051~R058,
  R031, R032, PR #27로 이미 반영됨)과 `linked_rule_id`로 이미 연결돼 있었다 — **새
  키워드 매칭 로직을 짤 필요가 없었다**, 이미 있는 룰 매칭 결과에 필드만 얹으면 됐다.
- `Classification`에 4개 컬럼 추가(`0013_k_taxonomy_fields.py`): `k_taxonomy_candidate_type`,
  `k_taxonomy_facility_type`, `finance_lead_type`, `k_taxonomy_hitl_required`.
  `finance_lead_type`이 채워져도 이건 "리드"일 뿐 여신 결정이 아니다(CLAUDE.md §9) —
  최종 승인은 기존 승인요청 큐(`RateApprovalRequest`, `request_type="equipment_finance"`,
  PR #28에서 이미 만들어둔 경로)를 거친다.
- `db/excel_loader.py::load_k_taxonomy_mapping()` + `db/k_taxonomy.py::
  k_taxonomy_fields_for_rule()` 신규 — `api/agent/tools.py`의 `_rule_decision`이
  `rule_id`를 실어 반환하도록 확장, `_build_classification`이 이 rule_id로 K택소노미
  필드를 채운다.
- **LLM 분류 프롬프트 확장은 하지 않기로 결론**(원래 스펙에 있었지만 착수 전 재확인
  필요 항목이었음): 회계가 준 정확한 키워드는 룰 매칭으로 100% 커버됨을 테스트로
  확인. 표현이 달라지면(예: "집진 설비 도입") 기존 룰 우선순위 체계상 다른 룰(R003,
  "설비" 포함 키워드)에 먼저 걸려 **오매칭**되는 부수 발견이 있었으나, 이건 K택소노미
  신규 문제가 아니라 `분류_기준표_확장` 시트 전체의 priority 설계 이슈라 별도로 분리.
- 계산 파이프라인(도구③)은 건드리지 않음 — `category='감축투자 후보'`는 배출량 계산
  대상이 아니다(원문: "배출량 계산 대상 아니나 녹색여신 참고"). 일반 연료 전표 계산이
  그대로 동작함을 테스트로 확인.
- 테스트: `tests/test_k_taxonomy.py` 10건(매핑표 무결성 2 + 순수 로직 4 + `classify_vouchers()`
  통합 4). 전체 `pytest` 207 passed.
- PR: https://github.com/noeyish/GamTan/pull/39 (`feat/k-taxonomy-equipment-fields` → `dev`, **병합 완료**)

### 6-6. K택소노미 리드 리스트 + `ScenePcaf.tsx` 정식 엔진 교체 — 남은 프론트 2건 (PR #41 + 후속)

§6-5에서 스코프 밖으로 남겨뒀던 프론트 2건(원래 개발자 A 담당) — 이번에 A가 이어받아 완료.

**K택소노미 리드 리스트 (PR #41)**

- `db/k_taxonomy.py::k_taxonomy_leads()` 신규 — `finance_lead_type`이 채워진 분류 건을
  전 기업에서 모아 반환. 정렬은 데이터 완전성(결손 개수)만 사용(원칙7 — 감축 실적 기반
  순위 금지), 담당자 반려 건 제외.
- `GET /admin/k-taxonomy-leads` 신규(기존 `/admin/rate-candidates`와 같은 패턴).
- `web/components/admin/KTaxonomyLeads.tsx` 신규(`RateCandidates.tsx` 구조 재사용),
  관리자 대시보드에 "K택소노미 리드" 탭 추가.
- 테스트: `tests/test_admin.py` 골든 케이스 3건.

**`ScenePcaf.tsx` 정식 엔진 교체**

⚠️ 단순 API 교체가 아니었다 — 정식 엔진(`db/pcaf_quality.py`)은 `OrganizationalBoundary`
사전 등록을 전제로 설계됐고(없으면 409), Before(매출추정) 기준선·동종업계 벤치마크
필드 자체가 없으며, Scope1·2를 각각 독립적으로 평가한다(구 엔진의 단일 "등급" 개념과
다름). 조사 후 재설계 방향으로 진행.

- `db/organizational_boundary.py::ensure_organizational_boundary()` 신규 — 조직경계가
  없으면 **간이화 가정**(`boundary_type='operational_control'`, `consolidation_scope='separate'`,
  대상이 대부분 자회사 없는 단일법인 소기업이라는 전제)으로 자동 생성. ⚠️ **회계 검수
  필요** — 실제로 연결대상이 있는 차주가 생기면 이 가정은 깨지므로 은행 담당자가 정식
  등록하는 절차로 교체돼야 한다. 정식 등록 레코드가 이미 있으면 그대로 존중(재생성 안 함).
- `db/pcaf_quality.py::save_quality_assessment_version()` 신규 — 한 Scope의 평가·저장
  로직을 은행 담당자용 evaluate 엔드포인트와 사장님용 리포트 래퍼가 공유(중복 제거,
  `api/routers/quality.py::evaluate_quality_assessment`도 이 함수를 쓰도록 리팩터링).
- `api/routers/owner_quality.py` 신규 — `GET /owner/{company_id}/quality-report?year=`.
  조직경계 자동 생성 → 최신 평가 없으면 1회 자동 산정·저장 → 재조회는 저장된 버전을
  그대로 반환(조회할 때마다 새 버전 안 만듦). `year` 생략 시 달력상 올해가 아니라 **그
  기업 전표가 실제로 존재하는 가장 최근 연도**를 기본값으로 씀(결산 데이터가 항상
  "올해"일 필요는 없고, "올해"로 고정하면 데이터가 과거 연도뿐인 기업은 리포트가 늘
  비어 보이는 문제가 있었다).
- `db/pcaf.py::benchmark_against_industry()`(구 `_benchmark`, 공개 함수로 개명) — 배출량
  총량 하나만 받는 순수함수로 시그니처를 다듬어 신·구 엔진 어느 쪽 결과든 재사용 가능.
- `web/components/ScenePcaf.tsx` 전면 재설계 — Scope1·2 각각 카드로 분리해 품질점수
  사다리(1~5, 구 엔진의 grade 사다리 UI를 Scope별 단일 마커로 단순화)·배출량·데이터
  완전성(`completeness_pct`)·판정 근거(`basis`/`limitations`, `db/pcaf_quality.py`가
  이미 한국어 문장으로 완결해 저장 — 프론트에 별도 매핑 안 둠)를 표시. "은행 검토 대기"
  배지 상시 노출. 벤치마크 카드는 데이터 모양이 그대로라 재사용. **월별 배출 추이만
  예외로 구 엔진(`/pcaf/{id}`)의 `monthly`를 계속 재사용** — Classification 원자료를
  월별 집계하는 독립 로직이라 엔진 교체와 무관.
- **폐기**: Before/After 박스 비교(before 값 자체가 없음), 실측/추정 비율 바(측정치
  개념이 다름 — `completeness_pct`로 대체).
- 테스트: `tests/test_owner_quality.py` 9건(조직경계 자동생성 3 + API 통합 6, 연도
  기본값 회귀 케이스 포함). 전체 `pytest` 222 passed.
- 공유 Supabase DB에 `pcaf_quality_rules` 시드가 안 돼 있던 것도 이번에 확인해 채움
  (7행, 사용자 확인 후 진행) — PR #25 이후 로컬 `db/init_db.py` 재실행이 안 됐던 것으로
  보임.
- PR: (작성 예정) 브랜치 `feat/scenepcaf-quality-engine`.

---

## 7-1. Tier 2 조기 착수 — 품질 이슈 로그 + 감사 대응 근거 패키지 (완료·병합, PR #37)

`docs/owner-admin-flow-spec.md` §7(품질 이슈 로그)·§8(감사 대응 근거 패키지)를 3주차를
기다리지 않고 조기 착수. A의 2주차 잔여 작업(K택소노미 필드)과 독립적이라 먼저 진행.

- **품질 이슈 로그**: 신규 테이블 `DocumentIngestionFailure`(`0012_document_ingestion_failures.py`).
  `api/document_ingestion.py::ingest_uploaded_document()`가 던지는 예외(중복·기관귀속
  미완료·엑셀형식오류·PDF판독실패)가 이전엔 HTTP 응답으로만 전달되고 DB엔 아무 것도
  안 남았다 — `db/quality_issues.py::record_ingestion_failure()`로 owner 업로드
  라우터의 각 except 블록에서 기록하도록 연결. 성공한 업로드는 `SourceDocument`로 이미
  남으므로 이 테이블엔 실패만 쌓인다. `GET /admin/quality-issues`(열람 전용).
- **감사 대응 근거 패키지**: 신규 테이블 없음 — `db/audit_package.py::build_audit_package()`가
  기존 `trace_logs` + `classifications.evidence` + `vouchers`를 기업·연도(월 범위 옵션)
  기준으로 조인해 시계열(`entries`)로 반환. `GET /admin/audit-package?company_id=&year=`
  (JSON), `&format=csv`로 원자료 CSV 다운로드. **PDF 서술형 감사보고서는 이번 범위 밖**
  (reportlab은 이미 requirements에 있어 후속 작업으로 부담 적음).
- 관리자 대시보드에 탭 2개 신설: "품질 이슈"(`QualityIssueLog.tsx`), "감사 대응"
  (`AuditPackage.tsx` — 기업 선택 드롭다운 + 연도 입력 + 조회 + CSV 다운로드 링크).
- 테스트: `tests/test_quality_issue_and_audit_package.py` 15건(순수 로직 8 + API 라우터 4
  + 통합 3) + 기존 `test_owner_document_upload.py`에 실패 기록 검증 1건 추가. 전체
  `pytest` 185 passed. 프론트 `tsc --noEmit`·`next build` 통과.
- PR: https://github.com/noeyish/GamTan/pull/37 (`feat/quality-issue-log-and-audit-package` → `dev`, **병합 완료**)

---

## 7. 3주차 — 통합, 여유 기능, 리허설 준비

| 담당  | 작업                                                                                                                                                          |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A + B | 전체 플로우 통합 테스트. 시간 남으면 Tier 2(PCAF 실시간 지표화, 탄소 신용카드) 또는 Tier 3(기업대출 금융배출량·귀속계수, 구 3주차 산식 그대로) 착수 여부 결정 |
| 회계  | 발표 대본, Q&A 준비(왜 두 방향을 병합했는지, PCAF 정식 산정과 우대금리 안내가 왜 상충하지 않는지 포함)                                                        |

산식(참고, Tier 3 착수 시 그대로 사용):

```text
분모 = 총자본 + PCAF 방법론상 total debt
IF 분모 <= 0: 계산 중단, review_required
ELSE: 귀속계수 = 대출잔액 / 분모, 금융배출량 = 귀속계수 × 차주 배출량
```

### 3주차 완료조건

- 사장님·관리자 플로우가 끊김 없이 1회 통주된다.
- Tier 0·1이 전부 동작한다.

---

## 8. 4주차 — 기능 동결·리허설·제출

| 순서 | 작업                                                                                                           |
| ---- | -------------------------------------------------------------------------------------------------------------- |
| 1    | 기능 동결. 이후 hotfix만 허용                                                                                  |
| 2    | 장애 주입 리허설: LLM 차단, API 중단, tenant 격리 우회 시도 → 목업 없이 오류·review_required로 표시되는지 확인 |
| 3    | 전체 백엔드 테스트(`pytest`), 프론트 정적검사·빌드                                                             |
| 4    | 통주 리허설 3회 이상                                                                                           |
| 5    | 회계 담당 진행 Q&A 리허설                                                                                      |
| 6    | `dev → main` 병합 전 최종 스모크 테스트                                                                        |
| 7    | 통주 녹화 영상 확보                                                                                            |

### 4주차 완료조건

- 다른 금융기관 데이터 접근이 차단된다 (tenant 격리 회귀 확인).
- 장애 주입 시 실패가 목업으로 대체되지 않는다.
- 우대금리·설비금융 안내가 자동 승인 없이 항상 담당자 승인을 거친다.
- 통주 녹화 영상을 확보한다.

---

## 9. 데모 시나리오

1. 마이데이터 동의 + 연료 유형 체크 + 업로드 (사진/OCR 또는 홈택스 엑셀) → 차주 인벤토리 생성
2. 에이전트 트레이스: 결손 감지·이상치 재검증
3. AI 분류 결과 + evidence, 저신뢰 HITL, K택소노미·설비투자 리드 표시
4. PCAF Business Loans 품질 후보(규칙 기반) + 통계추정 대비 활동자료 기반 개선
5. 우대금리·설비금융 안내(비보장 명시) → 은행 담당자 승인 큐
6. 관리자 대시보드: HITL 큐·승인요청 큐·포트폴리오 뷰·(가능하면) 지원 대출 커버리지

---

## 10. 일정 리스크와 대응

| 리스크                                                                            | 대응                                                                    |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 병합 충돌 (`db/models.py`, `api/main.py`)                                         | D0에 최우선 처리, 충돌 시 기존 알림 엔진(`db/alerts.py`) 회귀 먼저 확인 |
| 검증 3수치 지연                                                                   | 병행 가능한 부분(파서·UI)부터 먼저 진행                                 |
| 회계 선행작업(K택소노미 매핑표) 지연                                              | 개발 착수 자체가 막히는 최우선 리스크, 순서 재조정                      |
| 두 레이어 개념 혼동으로 "PCAF 등급"과 "우대금리 자격"을 같은 것으로 취급하는 실수 | 안내 문구·화면에 항상 분리 표기, 코드 리뷰 체크리스트에 추가            |
| Tier 3(귀속계수 금융배출량) 착수 여부 미정으로 3주차 일정 불확실                  | 2주차 종료 시점에 팀이 명시적으로 결정, 자동으로 확대하지 않음          |
| 세금계산서 마이데이터 미지원, 은행권 LLM 규제 질문 대응                           | 기존 Q&A 답변 논리 유지                                                 |

---

## 11. 브랜치·병합 원칙

- 기준 브랜치는 `dev`다. `feat/db-alembic-migration`은 §1 절차로 가장 먼저 병합한다.
- 신규 작업은 기능 브랜치에서 진행하고 PR로 `dev`에 합친다.
- 공용 스키마·Alembic revision·LLM 출력 스키마 변경은 순서를 합의하고 한 명이 작성한다. 기존 revision 파일은 수정하지 않고 새 revision을 추가한다.
- `dev → main`은 전체 테스트·통주 리허설 이후 한 번만 수행한다.
- 기능 동결 이후에는 범위 확장 없이 결함 수정만 허용한다.

---

## 12. v1 이미 구현 완료된 항목 (2026-08-12 기준)

> §5~§7-1 상세 섹션의 요약표. 병합 완료 PR만 포함 — PR 대기 중인 것은 "PR 대기"로 별도 표기.

| 티어 | 항목 | 담당 | PR | 참고 |
| --- | --- | --- | --- | --- |
| Tier 0 | Alembic 마이그레이션, 기관/포트폴리오/조직경계/인벤토리/익스포저 등 v1 스키마 전체 | — | #23 | §1, `feat/db-alembic-migration` |
| Tier 0 | HITL 대량처리·필터, 변경 이력 탭 | B | #22, #24 | §6 진행 현황 노트. 2주차 계획보다 앞서 반영 |
| Tier 1 | PCAF Business Loans 품질 후보 규칙 엔진 (Table 10.1-2 원문 기준) | B | #25 | §5-1. 임시 1~5등급 → 규칙기반(1a~3c) 전환 |
| Tier 1 | 하이브리드 데이터 입력: 마이데이터 5종 + 업로드 3종(OCR/엑셀) + 연료체크 | A | #26 | §5-2 |
| Tier 1 | 대량 전표 / 홈택스 엑셀 업로드, 합성 데이터 시나리오 확장 | A/회계 | #27 | 정답지 41→50건 확장(I042~I050) |
| Tier 1 | 관리자 플로우: HITL 큐 / 승인요청 큐 분리, 원본문서 접근 감사 로그 | B | #28, #29 | §6-1 |
| Tier 1 | `borrower_emission_inventories` 연간 Scope 배출량 집계 | B | #32 | §6-3. 1주차 완료조건에서 이월됐던 항목 |
| Tier 1 | 사장님 앱 홈 화면 + 기업 선택기 + 마이데이터 CSV 실연동 | A | #33 | — |
| Tier 1 | 실제 PDF 텍스트 추출로 OCR mock 교체 | A | #34 | §5-3. pdfplumber 도입, 사장님 업로드 시 월 자동 인식 |
| 부수 | pre-existing 테스트 실패 3건 정리 (룰 매칭 카운트, I050 중복 케이스, 마이그레이션 백필 누락) | B | #30 | §6-2 |
| 부수 | owner "우대금리 안내 요청" 버튼 실데이터 연동 | B | #31 | §6-4. 2주차 B 잔여 UI |
| 부수 | Docker 이미지 경량화 (api 412MB→395MB, 캐시 재빌드 대폭 단축) | B | #28에 포함 | §6-1 병행 처리 |
| Tier 2 | 품질 이슈 로그 + 감사 대응 근거 패키지(CSV) | B | #37 | §7-1. Tier 2 조기 착수, PDF는 범위 밖 |
| Tier 1 | K택소노미·설비투자 필드 (백엔드만) | B | #39 | §6-5. 원래 A 담당, B가 백엔드만 대신 착수 |
| Tier 1 | K택소노미 리드 리스트(관리자 화면) | A | #41 | §6-6 |
| Tier 1 | `ScenePcaf.tsx` 정식 엔진(`db/pcaf_quality.py`) 교체 + 조직경계 자동생성 | A | #42 | §6-6 |
| 부수 | 우대금리 등급 상승 후보 판정을 정식 엔진 기준으로 재정렬 | A | #46 | §6-6 후속 — `db/pcaf.py::rate_upgrade_candidates`가 정식 엔진(Scope별 독립 평가)과 어긋나던 것 정리 |
| 부수 | 리포트 화면(`ScenePcaf.tsx`) UI 다듬기 4건 — Scope 카드 통합·좌우배치, 판정근거 문구, 월별 추이 오버레이 | A | #43, #44, #45, #40 | §6-6 후속, 기능 변경 없는 UX 개선 |
| 부수 | 사장님 앱 하단바 "탄소 리포트" 탭 추가 | A | #47 | `/owner/report` 진입 경로 |

---

## 13. v1 남은 개발 항목 요약 (2026-08-12 기준)

> 매 작업 완료 시 이 표를 갱신한다. 완료된 항목은 표에서 지우지 않고 상태만 "✅ 완료"로
> 바꾼다 — 무엇이 언제 끝났는지 이력이 남아야 팀 전체가 같은 그림을 본다. 이미 구현
> 완료된 항목은 §12 참고.

| 티어 | 항목 | 담당 | 상태 | 참고 |
| --- | --- | --- | --- | --- |
| Tier 1 | 검증 3수치 확정 (분류 정확도, 트랙A MAPE, 트랙B 실물대조 오차) | 회계 | ⬜ 미착수 | §2 Tier 1-1. 발표·Q&A 근거로 반드시 필요 |
| Tier 1 | K택소노미·설비투자 필드 — 백엔드 | B | ✅ 완료 | §6-5, PR #39. 회계 매핑표를 기존 룰 매칭에 연결, 새 매칭 로직 없음 |
| Tier 1 | K택소노미 리드 리스트 — 프론트 (owner-admin-flow-spec.md §5) | A | ✅ 완료 | §6-6, PR #41 |
| Tier 1 | `ScenePcaf.tsx` 구 엔진(`db/pcaf.py`) → 정식 엔진(`db/pcaf_quality.py`) 교체 | A | ✅ 완료 | §6-6, PR #42. 조직경계 자동생성(간이화 가정, 회계 검수 필요)·사장님용 리포트 래퍼 신규. 후속 UI 다듬기 PR #40, #43~#47 |
| Tier 2 | 우대금리·설비금융 "안내" (비보장 문구) | B | ✅ 완료 | §6-1·§6-4, PR #28·#29·#31 |
| Tier 2 | PCAF 데이터 품질 실시간 지표화 (초안→확정 알림) | 미배정 | ⬜ 미착수 | §2 Tier 2-9 |
| Tier 2 | 되묻는 HITL (사장님이 물량·연료 정보 직접 보완) | 미배정 | ⬜ 미결정 | `docs/hitl-owner-action.md` — 옵션 A/B 중 팀 결정 필요, 결정 전엔 착수 불가 |
| Tier 2 | 청중별 통역 / 탄소 신용카드(QR) | 미배정 | ⬜ 미착수 | §2 Tier 2-9, 상세 스펙 미작성 |
| Tier 2 | 품질 이슈 로그 (업로드 반려·실패 이력) | B | ✅ 완료 | §7-1, PR #37 |
| Tier 2 | 감사 대응 근거 패키지 — CSV | B | ✅ 완료 | §7-1, PR #37 |
| Tier 2 | 감사 대응 근거 패키지 — PDF 서술형 감사보고서 | 미배정 | ⬜ 미착수 | §7-1에서 범위 밖으로 명시. reportlab 이미 requirements에 있어 착수 부담 적음 |
| Tier 2 | 포트폴리오 뷰 확장 — 히트맵·연동 우선순위 Top10 | 미배정 | ⬜ 미착수 | `docs/owner-admin-flow-spec.md` §5 |
| Tier 2 | 규제 대응 리포트 (금감원 4단계 구조 자동 섹션) | 미배정 | ⬜ 미착수 | `docs/owner-admin-flow-spec.md` §6 |
| 부수 | 룰 우선순위 충돌 정리 (표현 변형이 엉뚱한 룰에 오매칭되는 문제) | 미배정 | ⬜ 미착수 | §6-5 "부수 발견" — K택소노미 작업 중 발견, `분류_기준표_확장` 시트 전체 이슈라 별도 분리 |
| 3주차 | A+B 전체 플로우 통합 테스트 (사장님·관리자 1회 통주) | A+B | ⬜ 미착수 | §7 |
| Tier 3 | 기업대출 금융배출량(귀속계수) 계산 | 미배정 | ⬜ 착수 여부 미결정 | §7 산식 정의는 돼 있음, 2주차 종료 시점에 팀이 결정하기로 함(§10 리스크) |
| Tier 3 | `business_loans_readiness` 체크리스트 | 미배정 | ⬜ 미착수 | §2 Tier 3-11 |
| Tier 3 | 월간 AI 브리핑 / 장비개선 시뮬레이터 / 지역집중 리스크 히트맵 / 그린 임팩트 예금 | 미배정 | ⬜ 자를 후보 | §2 Tier 3-12, 비전 슬라이드용으로만 유지 |
| 4주차 | 기능 동결·장애 주입 리허설·통주 녹화 | A+B+회계 | ⬜ 미착수 | §8, 3주차 완료 후 착수 |

**요약**: 2주차 Tier 1이 전부 끝났다. 남은 건 회계 몫(검증 3수치 — 발표 자료의 핵심
근거라 늦어도 3주차 전에는 확정돼야 한다)과 Tier 2 이후 항목들이다. "되묻는 HITL"은
코드가 아니라 팀 결정이 먼저 필요한 유일한 항목. 조직경계 간이화 가정(§6-6)은 회계
검수가 필요한 임시 정책으로 남아 있다.
