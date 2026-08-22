# OCR 파이프라인 테스트용 문서 fixture — 시나리오 매트릭스

```text
Status: synthetic-data
Last updated: 2026-08-18
Scope: data/fixtures/ 아래 개별 PDF/JPG/PNG가 어떤 시나리오를 시연하는지 기록
```

> 이 문서는 `docs/upload-scenarios.md`(2026-08-12, `data/업로드서류/`, C001~C006 결측 매트릭스)와는
> **별개의 새 생성 트랙**이다. 실제 정부 서식(세금계산서 별지 제11호)·한전 청구서 레이아웃을
> HTML로 재현해 Chrome headless로 PDF/JPG/PNG 렌더링하는 방식으로 만들며, 목적도 다르다 —
> 업로드 결측 매트릭스가 아니라 **문서 자체의 시각적 다양성(서식·포맷 혼합)과 계산 엔진 검증용
> golden set(`_manifest.csv`)** 확보가 우선이다. 생성기: `scripts/generate_tax_invoice_fixtures.ps1`,
> `scripts/generate_electricity_bill_fixtures.ps1`, `scripts/generate_other_companies_fixtures.ps1`,
> `scripts/generate_small_business_fixtures.ps1`
> (PowerShell + Chrome headless, Python/Node 없는 환경에서도 재현 가능하도록 설계).

---

## ⚠️ 기존 upload-scenarios.md와의 역할 충돌 — 새 지침 우선 적용

`gamtan_claude_data_revision_command.md`(사용자 개정 지시서) §6-2 기준으로 회사별 시나리오를
새로 배정하는 과정에서, 이미 존재하던 `docs/upload-scenarios.md`(2026-08-12, `data/업로드서류/`
트랙)의 회사별 역할과 **세 군데**가 정면으로 충돌했다. 모두 같은 원칙으로 해결했다:
**새 지시서를 우선 적용하고, 기존 문서는 고치지 않은 채 다른 트랙·다른 기간으로 공존시킨다.**

| 회사 | `upload-scenarios.md`(기존, Q1 트랙) | 개정 지시서(신규, 이번 `data/fixtures/` 트랙) | 결과 |
| --- | --- | --- | --- |
| 성서테크(C003) | 도시가스 결손(2~3월) | 이상치 기업 — 12월 전기 스파이크 | 두 문제 동시 보유(결손+이상치) |
| 칠곡소재(C004) | 전면 미제출(경유·도시가스 0건) | 5~9인 소규모 **벤치마크용 정상 데이터** | 신규 트랙에서는 정상 제출로 재정의 |
| 포항이엔지(C005) | 완비(결측 없음) — 벤치마크 대조군 | 7~8월 전체 누락 | 신규 트랙에서는 7~8월만 결측으로 재정의 |

칠곡소재·포항이엔지는 기존 문서와 아예 반대 방향이라 "동시 보유"로 봉합할 수 없었다 — 신규
`data/fixtures/` 트랙 안에서는 개정 지시서를 그대로 따르고, `data/업로드서류/`(기존 트랙, Q1)는
손대지 않았다. 두 데이터셋을 같은 회사·같은 기간(Q1)에 대해 동시에 "정답"처럼 쓰면 안 된다 —
어느 트랙 자료인지 구분해서 참조할 것.

원래 설계였던 "○○정밀(MAIN) = 결손·이상치 데모 전용 기업" 원칙(`scripts/generate_upload_docs.py`
docstring에 명시)은 깨지 않았다 — MAIN은 여전히 자체 이상치(경유, 7월~)를 유지하고, 성서테크는
두 번째 이상치 사례로 추가된 것뿐이다.

---

## 회사별 한 줄 요약

| 회사 | 담당 문서유형 | 시나리오 | 시스템이 해야 할 반응 |
| --- | --- | --- | --- |
| ○○정밀(MAIN) | 세금계산서(경유) | 7월부터 지게차 2대 증차로 사용량 구조적 급증 — **원인이 비고란에 명시됨** | 설명 가능한 이상치 → 자동 확정 가능, 참고용 알림만 |
| 구미정밀(C001) | 세금계산서(경유) + 전기고지서 | 세금계산서는 완비, **전기고지서 2월만 결손** | 결손 감지 → 보완요청, 나머지는 정상 처리 |
| 대경부품(C002) | 세금계산서(경유·휘발유) + 전기고지서 | 연료 데이터는 완비(Scope1 강함), **전기고지서 4개월(2·5·8·11월) 사용량 미확인 → 추정 청구** | Scope1은 자동계산, Scope2는 해당 월 HITL(추정치로 계산 불가) |
| 성서테크(C003) | 전기요금고지서 | 12월 전기 사용량 급증(4,900→11,800kWh, 약 2.4배) — **청구서 어디에도 원인 설명 없음** | 순수 숫자 패턴만으로 이상치 탐지 → HITL 필수 |
| 칠곡소재(C004) | 세금계산서(경유) + 전기고지서 | 9명 소규모, **완전히 정상적인 소액·저빈도 데이터** | 5~9인 벤치마크 밴드의 유일한 실표본 — 업종/규모 분포 비교의 기준점 |
| 포항이엔지(C005) | 세금계산서(경유) + 전기고지서 | **7~8월 서류가 통째로 없음**(세금계산서·전기고지서 둘 다) | 두 달 연속 완전 공백 → 결측 감지 + 강한 보완요청 |
| 대구정공(C006) | 세금계산서(경유) + 무관 파일 | 5월·9월에 진짜 연료 서류 대신 **카페 영수증이 업로드됨** | 문서분류가 "관계없는 파일"로 판정 → 자동 반려, 리포트 계산에서 제외 |

핵심 축 3가지로 커버리지를 나눴다:
1. **설명 가능 vs 설명 불가능한 이상치** — MAIN(비고란 있음) vs 성서테크(비고란 없음)
2. **부분 결손의 정도** — 구미정밀(1개월), 대경부품(수치는 있으나 신뢰 불가 4개월), 포항이엔지(2개월 전체)
3. **정상/대조군과 완전 오염** — 칠곡소재(깨끗한 벤치마크 데이터) vs 대구정공(엉뚱한 파일 오염)

---

## 상세

### ○○정밀(MAIN) — 세금계산서(경유), 2025년 1~12월
- 월 2~3건, 공급자 3곳(구미석유·왕산주유소·경일주유소) 로테이션
- 1~6월 평상시(월 130~190L) → 7~12월 지게차 2대 증차로 월 500~700L 구조적 상승
- 위치: `data/fixtures/tax_invoices/MAIN/` (34건 + `_manifest.csv`)
- GitHub: `feat/tax-invoice-fixtures-main` 브랜치, PR #83 (머지 대기)

### 구미정밀(C001) — 세금계산서(경유) 12개월 완비 + 전기고지서 11개월(2월 결손)
- 세금계산서: 월 2건(지게차용/배송차량용), 형곡주유소·구미중앙에너지 로테이션, 월 195~230L 평이한 흐름
- 전기고지서: 1,3~12월만 존재(2월 파일 없음 — "결측=파일을 안 만든다" 원칙), 3,300~3,950kWh 완만한 증가
- 위치: `data/fixtures/tax_invoices/C001/`(24건), `data/fixtures/electricity_bills/C001/`(11건)

### 대경부품(C002) — 세금계산서(경유·휘발유 혼합) 12개월 + 전기고지서 12개월(4개월 추정청구)
- 세금계산서: 월 2건 고정 조합(경유·지게차용 + 휘발유·업무차량용), 경산셀프주유소·대경에너지
- 전기고지서: 2·5·8·11월은 "검침 확인 지연" 문구와 함께 당월 kWh가 비어있고 전월 실적 기준
  추정 청구됨(`is_estimated=True`) — 실제 원격검침 장애 시 발행되는 추정요금고지서를 재현
- 위치: `data/fixtures/tax_invoices/C002/`(24건), `data/fixtures/electricity_bills/C002/`(12건)

### 성서테크(C003) — 전기요금고지서, 2025년 1~12월
- 월 1건, 1~11월 4,150→4,900kWh 완만한 계절 변동, 12월 11,800kWh 급증(원인 미기재)
- 12월 발행일 2026-01-05로 YTD 구간까지 자연스럽게 걸침
- 위치: `data/fixtures/electricity_bills/C003/` (12건 + `_manifest.csv`)

### 칠곡소재(C004) — 세금계산서(경유) 12개월 + 전기고지서 12개월, 전부 정상
- 9명 소기업 규모에 맞춰 월 1건(일부 달만 2건), 35~68L 소량, 공급자 1곳(칠곡주유소)만 사용
- 전기고지서도 12개월 전부 존재, 1,850~2,120kWh 소규모 사용량
- 5~9인 규모 밴드에서 유일하게 "1년치 계산 가능한 정상 데이터"를 가진 기업 — 업종 벤치마크
  분포 비교의 기준점 역할(개정 지시서 §2-3 요구사항)
- 위치: `data/fixtures/tax_invoices/C004/`(14건), `data/fixtures/electricity_bills/C004/`(12건)

### 포항이엔지(C005) — 세금계산서(경유) 10개월 + 전기고지서 10개월, 7~8월 전체 공백
- 1~6월, 9~12월만 존재 — 7월·8월은 세금계산서·전기고지서 **둘 다 파일이 없음**
- 나머지 달은 월 2건, 75~90L 안정적인 정상 흐름 (포항해맞이주유소·영일대에너지)
- 위치: `data/fixtures/tax_invoices/C005/`(20건), `data/fixtures/electricity_bills/C005/`(10건)

### 대구정공(C006) — 세금계산서(경유) 10개월 + 무관 파일 2건(5월·9월)
- 1~4,6~8,10~12월은 정상 세금계산서 월 2건(북구주유소·북대구에너지)
- 5월·9월은 정상 세금계산서 대신 **카페 영수증(무관 파일)**이 업로드됨 — 실제 연료 구매
  서류는 그 달에 존재하지 않음(대체가 아니라 결측 + 오염이 겹친 상태)
- 카페 영수증은 세금계산서와 완전히 다른 미니 영수증 레이아웃(회전·그림자 효과)으로 별도 제작 —
  문서분류기가 형태만으로도 "이건 세금계산서가 아니다"를 구분할 수 있는지 테스트
- 위치: `data/fixtures/tax_invoices/C006/` (세금계산서 20건 + 카페영수증 2건, 총 22건)

---

## 소상공인 트랙(탄소중립포인트) — S001·S002

`docs/small-business-green-supply-data-plan.md` §6 설계에 대응하는 fixture. 위 회사들과
다른 점 두 가지: ① **계약종별이 `일반용(을)`** (제조업 MAIN·C001~C006은 전부 `산업용(을)`
계열) — 소상공인 자동 판별(같은 문서 §6.1)의 근거 데이터, ② **2024-01~2026-08 32개월치** —
탄소중립포인트 자격 판정에 필요한 기준년도(2024) 비교 데이터가 있어야 하기 때문에 다른
회사들(2025년 1개년 또는 YTD 일부)보다 기간이 길다.

### S001(동성로카페) — 감축 성공 케이스
- 2024(기준) → 2025: 매달 ~7.5% 감축(5% 문턱 안전 통과) → 2026: 추가로 ~3%만 감축(절감
  여지 소진, 정체 패턴)
- 2026 구간은 산식 해석에 따라 결과가 갈리는 의도적 엣지케이스: "전년 동월 단순비교"로는
  5% 미달(~3%)이지만 "과거 2년 평균 대비"로는 통과(~6.7%) — 회계가 산식을 확정하면
  계산 함수가 올바른 쪽(2년 평균)을 구현했는지 이 골든셋으로 바로 검증 가능
- 위치: `data/fixtures/electricity_bills/S001/` (32건 + `_manifest.csv` + `_reduction_expected.csv`)

### S002(반월당분식) — 감축 미달·대조군 케이스
- 2024→2025→2026 내내 사용량이 오히려 소폭 증가(설비 추가 등 가정) — 어떤 산식으로 계산해도
  자격 미달이어야 정상인 음성 대조군
- 자격 판정 로직이 무조건 통과시키는 버그가 없는지 검증하는 용도(S001만 있으면 "항상 True를
  반환해도 통과하는" 상태를 못 잡음)
- 위치: `data/fixtures/electricity_bills/S002/` (32건 + `_manifest.csv` + `_reduction_expected.csv`)

### `_reduction_expected.csv` 공통 컬럼
```text
year_month, usage_kwh, prior_year_same_month_kwh, yoy_reduction_pct, yoy_eligible_5pct,
avg_prior_2yr_kwh, reduction_vs_2yr_avg_pct, avg2yr_eligible_5pct, note
```
2026년 행에서만 `avg_prior_2yr_kwh` 계열이 채워진다(2024+2025 두 해 데이터가 모두 있어야
2년 평균을 계산할 수 있으므로). 감축률 산정 공식은 아직 회계 확인 전이라(§14-1·§15.2,
`docs/small-business-green-supply-data-plan.md`) 두 해석을 모두 golden set에 남겨뒀다.

**아직 없음**: 상수도 요금고지서(§7.2, 실제 서식 미확보로 이번엔 제외), 탄소중립포인트
신청서 초안 자체(hwp 서식은 확보됨 — §14-1 해결, 다음 단계에서 데이터화 가능).

---

## 산출물

```text
data/fixtures/tax_invoices/MAIN/*.{pdf,jpg,png} + _manifest.csv        — 34건
data/fixtures/tax_invoices/C001/*.{pdf,jpg,png} + _manifest.csv        — 24건
data/fixtures/tax_invoices/C002/*.{pdf,jpg,png} + _manifest.csv        — 24건
data/fixtures/tax_invoices/C004/*.{pdf,jpg,png} + _manifest.csv        — 14건
data/fixtures/tax_invoices/C005/*.{pdf,jpg,png} + _manifest.csv        — 20건
data/fixtures/tax_invoices/C006/*.{pdf,jpg,png} + _manifest.csv        — 22건(카페영수증 2건 포함)
data/fixtures/electricity_bills/C001/*.{pdf,jpg,png} + _manifest.csv   — 11건
data/fixtures/electricity_bills/C002/*.{pdf,jpg,png} + _manifest.csv   — 12건
data/fixtures/electricity_bills/C003/*.{pdf,jpg,png} + _manifest.csv   — 12건
data/fixtures/electricity_bills/C004/*.{pdf,jpg,png} + _manifest.csv   — 12건
data/fixtures/electricity_bills/C005/*.{pdf,jpg,png} + _manifest.csv   — 10건
data/fixtures/electricity_bills/S001/*.{pdf,jpg,png} + _manifest.csv + _reduction_expected.csv — 32건
data/fixtures/electricity_bills/S002/*.{pdf,jpg,png} + _manifest.csv + _reduction_expected.csv — 32건

scripts/generate_tax_invoice_fixtures.ps1        — MAIN 세금계산서 생성기
scripts/generate_electricity_bill_fixtures.ps1   — 성서테크 전기요금고지서 생성기
scripts/generate_other_companies_fixtures.ps1    — C001~C006 일괄 생성기(세금계산서·
                                                     전기고지서·무관파일 공용 템플릿 포함)
scripts/generate_small_business_fixtures.ps1     — S001·S002 소상공인 전기고지서 + 감축률
                                                     골든셋 생성기(위 스크립트의 템플릿 재사용)
```

총 259건(MAIN 34 + C001 35 + C002 36 + C003 12 + C004 26 + C005 30 + C006 22 + S001 32 + S002 32).

재생성: PowerShell에서 각 스크립트 실행(Chrome headless 필요, 경로는 스크립트 상단 `$Chrome`
변수 참고). 매 실행마다 파일을 덮어쓰므로 파일명·수치는 항상 동일하게 재현된다.

## 남은 후보

- `docs/upload-scenarios.md`(Q1 트랙)와 이번 `data/fixtures/`(연간 트랙)를 하나의 로더/DB
  스키마로 통합할지 여부 — 현재는 두 데이터셋이 별개 파일 체계로 공존
- 도시가스고지서 문서 유형은 아직 신규 트랙에 없음(성서테크의 Q1 도시가스 결손은 기존
  `data/업로드서류/`만 커버)
- 2026년 1~8월 YTD 구간은 S001·S002(소상공인 트랙)만 커버함 — MAIN·C001~C006(제조업 트랙)은
  여전히 2025년 1개년 또는 그 이하라 개정 지시서 §1의 "2026년 1~8월 최근 동향" 요구사항이
  제조업 쪽에는 아직 미착수
- 상수도 요금고지서, 탄소중립포인트 신청서 초안 데이터는 아직 없음(hwp 서식은 확보 완료,
  `docs/small-business-green-supply-data-plan.md` §14-1 해결 — 다음 착수 후보)
