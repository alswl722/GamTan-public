# 탄소 캘린더 — 월간 AI 브리핑 + 날짜별 활동 캘린더 (작업 계획)

> 논의 배경: Figma에 먼저 두 화면을 시안으로 만듦 — ①"월간 AI 브리핑"(캐릭터 우디가
> 그달 결제·사용량을 편지 형식으로 전달하는 화면), ②"탄소 캘린더"(월 캘린더
> 그리드에 전표·AI 활동을 날짜별 점으로 표시하고, 날짜를 탭하면 하단 시트로
> 상세 내역이 펼쳐지는 화면). 사장님 앱 홈 화면 2×2 기능 카드 중 "이상 신호"
> 자리를 "탄소 캘린더"로 교체하고, 하단 탭바(4개→5개, 데이터 업로드와 탄소
> 리포트 사이에 "탄소 캘린더" 삽입)까지 Figma 반영 완료. 이 문서는 그 시안을
> 실제 코드로 구현하기 위한 계획.

## 확정된 방향

- **월간 AI 브리핑**과 **탄소 캘린더**는 별개 화면이지만 하나의 플로우로 잇는다
  — 캘린더 화면 상단에 이번 달 편지 도착을 알리는 축약 카드를 두고, 탭하면
  브리핑 화면으로 이동한다(Figma에 이미 그렇게 배치됨).
- 새 계산 로직은 만들지 않는다. 두 화면 모두 기존 데이터를 다른 형태로
  재배열해 보여주는 뷰일 뿐이다 — CLAUDE.md §5 원칙1(LLM 산수 금지)과 같은
  결로, "새로 계산"이 아니라 "이미 있는 값을 요약·재조합"만 한다.
  - 브리핑의 "경유 사용량 +18%" 같은 증감률은 `Classification.emission_co2e`·
    `activity_amount`를 연료별로 이번 달 vs 지난달 합산해서 나온 파생값이지,
    새로운 배출량 계산이 아니다.
  - 캘린더의 날짜별 점은 `Voucher.issue_date`(전표 발행일)와
    `TraceLog.created_at`(에이전트 활동 시각)을 날짜로 그룹핑만 한 것이다.
- **브리핑 문장(편지)은 LLM이 아니라 코드가 조립한다.** 증감 방향(▲/▼)·비율은
  결정론적 계산이고, 문장은 미리 정해둔 템플릿에 그 값을 끼워 넣는 방식으로
  만든다("이번 달 {연료} 사용량이 {비율}% {늘었어요|줄었어요}"). CLAUDE.md
  §6의 코드 우선 오케스트레이터 원칙과 동일 — 매달 반복되는 정형 요약에
  LLM을 태울 이유가 없고(비용·재현성·환각 리스크), 자연스러운 문장은 템플릿
  분기를 촘촘히 짜는 것으로 충분히 달성 가능하다.
- **캘린더는 조회 전용이다.** 날짜를 눌러도 데이터를 수정하지 않는다 —
  전표 확정/반려 같은 조치는 여전히 담당자 HITL 몫이고(CLAUDE.md §9),
  사장님 화면은 "무슨 일이 있었는지 보여주기"까지만 한다.
- `issue_date`가 없는(nullable) 전표는 정확한 날짜에 못 꽂는다 — 이런 전표는
  캘린더에서 빠지고, 필요하면 월간 브리핑 쪽 "이달 요약" 안내문에서 건수만
  뭉뚱그려 언급한다(예: "발행일이 확인되지 않은 전표 2건은 캘린더에는 표시되지
  않아요"). 없는 데이터를 있는 것처럼 특정 날짜에 끼워 넣지 않는다(실패 가시성
  원칙, CLAUDE.md §6).

## 데이터 소스 확인 (착수 전 확인 완료)

- `vouchers.issue_date`(DateTime, nullable) — 전표 발행일. `get_vouchers()`가
  이미 `issue_date`·`item_description`·`supply_amount_krw`·`source`를
  반환 중(`api/queries.py:38`).
- `trace_logs.created_at` + `step_type`(계획/관찰/행동) + `message` — 에이전트
  활동 시각과 내용. 관리자 쪽 트레이스 뷰가 쓰는 것과 같은 테이블, 이번엔
  `company_id`로 필터해 사장님 화면에 노출한다는 점만 다름.
- `classifications.emission_co2e`, `activity_amount`, `fuel_type`,
  `scope`, `classified_at` — 브리핑의 "이번 달 vs 지난달" 비교에 필요.
  `Classification`은 `Voucher`와 1:1(unique)이라 `issue_date` 기준 월로
  묶을 수 있음.
- **아직 없는 것**: 위 데이터를 "월별 요약"이나 "날짜별 그룹"으로 집계해주는
  쿼리 함수·API 엔드포인트. 이번 작업의 핵심은 이 집계 레이어를 새로 만드는
  것 — 프론트에서 원자료를 받아 재조합하지 않고, 백엔드가 이미 그룹핑된
  형태로 내려준다(관리자 감사 대응 패키지 `GET /admin/audit-package`와 같은
  패턴 — 여러 테이블을 조인·정렬해서 시계열로 묶어주는 것 자체가 신규지만,
  그 안의 숫자는 기존 값 그대로).

## 백엔드 설계

### 1. `api/queries.py` — 집계 함수 2개 신규 추가

```python
def get_calendar_events(session, company_id: int, year: int, month: int) -> list[dict]:
    """해당 월의 날짜별 이벤트 — 전표(issue_date 있는 것만) + 트레이스 로그.
    반환: [{date, entry_type: "voucher"|"trace", scope, fuel_type,
            item_description, supply_amount_krw, step_type, message}, ...]
    날짜 오름차순. issue_date가 null인 전표는 결과에서 제외(원칙 참고)."""

def get_monthly_briefing(session, company_id: int, year: int, month: int) -> dict:
    """이번 달 vs 지난달 연료별 활동량·배출량 비교 + 편지 문단 조립.
    반환: {year, month, paragraphs: [str, ...], stats: [
             {fuel_type, this_month, last_month, delta_pct, direction}
           ], has_previous_month: bool}
    직전월 데이터가 없으면(첫 달) 비교 문장 대신 "측정을 시작한 첫 달이에요"류
    안내로 분기 — 없는 지난달과 비교해 억지로 %를 만들지 않는다."""
```

- `get_monthly_briefing()`의 문장 조립은 `db/` 아래 순수 함수로 분리한다
  (`db/owner_briefing.py` 신규) — 계산(증감률)과 문장 템플릿을 분리해 단위
  테스트를 각각 걸 수 있게. `api/queries.py`는 얇게 이 함수를 호출만 한다
  (기존 `db/pcaf_engine/`, `db/document/` 등과 같은 배치 원칙,
  CLAUDE.md §3 "디렉토리 구성" 절 — 신규 파일 성격이 같은 게 2~3개 쌓이면
  서브디렉토리로 묶는 규칙이니 지금은 `db/` 루트에 단일 파일로 시작).

### 2. `api/routers/owner.py` — 엔드포인트 2개 신규 추가

```
GET /owner/{company_id}/calendar?year=&month=       그 달 날짜별 이벤트
GET /owner/{company_id}/briefing?year=&month=        그 달 편지(문단+증감 통계)
```

- 기존 라우터 상단 docstring(엔드포인트 목록)에 두 줄 추가 — 이 파일의 기존
  관례.
- `year`/`month` 생략 시 서버 기준 이번 달로 기본값 처리(캘린더 화면 최초
  진입 시 파라미터 없이 호출하는 게 자연스러움).

### 3. Pydantic 응답 스키마

기존 owner 라우터가 `dict` 그대로 반환하는 패턴을 따른다(다른 owner
엔드포인트들과 통일 — 별도 response_model 강제하지 않는 기존 스타일 유지).

## 프론트엔드 설계

### 1. `web/lib/api.ts` — 함수 2개 추가

```typescript
export async function getOwnerCalendar(companyId: number, year: number, month: number): Promise<CalendarEvent[]>
export async function getOwnerBriefing(companyId: number, year: number, month: number): Promise<MonthlyBriefing>
```

타입(`CalendarEvent`, `MonthlyBriefing`)도 이 파일에 추가 — 기존 owner 쪽
타입들과 같은 위치(admin은 `admin-types.ts`로 분리돼 있지만 owner는 지금
`api.ts` 하나에 다 있는 기존 구조를 그대로 따름).

### 2. 신규 페이지 2개

- `web/app/owner/calendar/page.tsx` — 탄소 캘린더. Figma 시안 그대로:
  이번 달 브리핑 축약 카드 → 월 캘린더 그리드(요일 헤더 + 날짜별 점,
  Scope1=`scope1` 색상/Scope2=`scope2` 색상/AI 활동=`brand` 색상) →
  날짜 탭 시 하단에 그날 이벤트 상세 리스트.
- `web/app/owner/briefing/page.tsx` — 월간 AI 브리핑. Figma 시안 그대로:
  우디 캐릭터+말풍선 인사말 → 편지 본문(템플릿 문단, 백엔드가 조립해서
  내려준 문자열 그대로 렌더) → 미니 수치 뱃지 3개 → "탄소 리포트 자세히
  보기" CTA → 이전/다음 달 네비게이션.
- 두 페이지 모두 기존 owner 페이지들과 같은 레이아웃 규칙 적용
  (`web/app/owner/layout.tsx`의 공통 하단바, `max-w-2xl` 좁은 폭, `rounded-3xl
  bg-surface shadow-card` 카드 스타일 — CLAUDE.md §8 각주 참고).

### 3. `web/app/owner/page.tsx` — 홈 화면 반영

- `FEATURE_CARDS` 배열에서 "이상 신호"(`href: "/owner/report"`) 항목을
  "탄소 캘린더"(`href: "/owner/calendar"`)로 교체 — Figma에서 이미 이
  카드를 사용자가 직접 손봐둔 상태이므로, 코드에서는 캐릭터 이미지 경로만
  그 Figma 결과물에 맞춰 확인 후 반영(현재 어떤 이미지로 정리됐는지는
  구현 착수 시 Figma에서 재확인 필요 — 이 문서 작성 시점엔 미확정).

### 4. 하단 탭바 반영

- 사장님 앱 하단 탭바(현재 소스 위치 확인 필요 — `web/app/owner/layout.tsx`
  또는 별도 `BottomNav` 컴포넌트)에 "탄소 캘린더" 탭 추가.
  Figma 순서: 홈 → 데이터 업로드 → **탄소 캘린더** → 탄소 리포트 → 맞춤 혜택.
  아이콘은 Figma에서 기존 4개와 통일된 라인 스타일(캘린더 바디+바인더
  고리 2개+활동 점)로 이미 확정됨 — 그대로 SVG/아이콘 컴포넌트로 옮긴다.

## 테스트 설계

- `db/owner_briefing.py`의 문장 조립 함수 — 단위 테스트로 각 분기 검증:
  증가/감소/변화없음, 직전월 데이터 없음(첫 달), 특정 연료만 데이터 있고
  나머지는 없음.
- `get_calendar_events()` — `issue_date` null인 전표가 결과에서 빠지는지,
  월 경계(예: 6/30 vs 7/1)가 정확히 걸러지는지, 전표와 트레이스가 날짜
  오름차순으로 잘 섞이는지 검증.
- `get_monthly_briefing()` — 지난달 대비 증감률 계산이 실제 배출량 계산
  엔진 결과(`emission_co2e`)와 일치하는지(새로 계산하지 않고 기존 값을
  합산만 했는지 확인하는 회귀 테스트 성격).
- 기존 `tests/` 디렉토리 구조 규칙(CLAUDE.md §3) 그대로 — 소스가
  `db/owner_briefing.py`(루트)면 테스트도 `tests/` 루트에 대응 파일로.
  단, TestClient 통합 테스트(`GET /owner/{id}/calendar` 등 라우터 테스트)는
  기존 관례대로 `tests/` 루트의 owner 통합 테스트 파일에 추가.

## 결정 필요 (착수 전 확인 필요)

- [ ] **하단 탭바 소스 위치 확정** — 현재 4탭 하단바가 코드 어디에 정의돼
  있는지(레이아웃 공통 컴포넌트인지, 각 페이지 개별 렌더인지) 확인 후 계획
  갱신 필요. Figma는 5탭으로 이미 반영됐으나 코드 쪽 실제 파일은 미조사.
- [ ] **홈 화면 "이상 신호→탄소 캘린더" 카드 이미지** — Figma에서 사용자가
  직접 정리한 최종 카드 디자인을 구현 직전에 다시 확인.
- [ ] 캘린더 이벤트가 하루에 4개 이상 몰릴 때 점 표시 상한(Figma는 최대 3개
  가정) — 실데이터로 이보다 많은 날이 나오는지 사전 확인 필요(다건 전표
  발행일이 겹치는 달 존재 가능성, 예: 세금계산서+전기고지서 같은 날 도착).
- [ ] 브리핑 문장 템플릿의 문구 톤(존댓말 어미, 이모지 사용 여부 등) 최종
  확정 — 이 문서의 예시 문장은 Figma 시안 그대로 가져온 초안.

## 진행 상태 — 착수 전 (Figma 시안만 완료)

- [x] Figma: 월간 AI 브리핑 화면(App 페이지, "⑧ 월간 AI 브리핑")
- [x] Figma: 탄소 캘린더 화면(App 페이지, "⑨ 탄소 캘린더")
- [x] Figma: 하단 탭바 5탭 반영 + 캘린더 아이콘 스타일 통일
- [x] Figma: 홈 화면 기능 카드 "이상 신호"→"탄소 캘린더" 교체(사용자 직접 수정)
- [ ] 백엔드: `db/owner_briefing.py` 신규(문장 조립 순수 함수)
- [ ] 백엔드: `api/queries.py::get_calendar_events()`,
  `get_monthly_briefing()` 신규
- [ ] 백엔드: `api/routers/owner.py`에 `GET /calendar`, `GET /briefing`
  엔드포인트 추가
- [ ] 프론트: `web/lib/api.ts`에 타입·호출 함수 추가
- [ ] 프론트: `web/app/owner/calendar/page.tsx` 신규
- [ ] 프론트: `web/app/owner/briefing/page.tsx` 신규
- [ ] 프론트: 홈 화면 기능 카드 링크 교체
- [ ] 프론트: 하단 탭바에 "탄소 캘린더" 추가(소스 위치 확인 후)
- [ ] 테스트: 문장 조립 단위 테스트, 캘린더/브리핑 쿼리 테스트, 라우터
  통합 테스트
- [ ] 브라우저 실측 확인: 캘린더 날짜 탭 → 상세 시트, 브리핑 이전/다음 달
  네비게이션 동작 확인
