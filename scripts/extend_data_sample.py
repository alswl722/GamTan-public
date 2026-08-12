"""data/감탄_데이터준비_샘플.xlsx 확장 패치 (1회성, 재현 가능).

배경: 이 파일은 db/excel_loader.py가 실제로 읽는 운영 파일이라 기존 5개 시트
(전표_샘플·분류_기준표_확장·배출계수·월별단가·기대_결과)의 헤더·기존 행은
절대 건드리지 않는다 — 계산 로직(배출계수·월별단가·50개 분류규칙)은 이미
이 파일에 있는 것이 훨씬 정밀해서 db/synth_dataset_generator.py로 만든
별도 시나리오 세트(감탄_합성데이터_v1.xlsx)보다 우선한다.

이 스크립트는:
1. 원본을 감탄_데이터준비_샘플_원본백업.xlsx로 백업
2. 기존 3개 시트(전표_샘플·분류_기준표_확장·기대_결과)에 "새 시나리오"만
   행으로 추가한다 — 감탄_합성데이터_v1.xlsx에서 다뤘지만 기존 50개 규칙에는
   없던 K-택소노미/설비투자 카테고리(태양광·ESS·전동지게차·히트펌프·집진기·
   폐수처리설비·재활용설비), 설비투자 불명확(유지보수비), 중복 업로드
   시나리오를 R031/R032(고효율 설비·CNC 장비구매) 패턴 그대로 확장한다.
3. 기존 파일에 전혀 없던 개념(기업 프로필, 마이데이터/업로드 구분, 구조화된
   HITL 큐, 은행 mock)만 새 시트로 추가한다 — 배출계수/월별단가/분류규칙/
   기대결과는 절대 새로 만들지 않는다(이미 있는 게 더 정밀함).

python -m scripts.extend_data_sample 로 실행. 이미 확장된 파일에 대해
재실행하면 전표ID가 겹쳐 중복 추가되므로, 항상 백업에서 다시 시작해야
재실행 가능하다(원본 백업을 최초 1회만 만들고 이후엔 덮어쓰지 않음).
"""
import os
import shutil

import openpyxl
from openpyxl.utils import get_column_letter

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TARGET = os.path.join(DATA_DIR, "감탄_데이터준비_샘플.xlsx")
BACKUP = os.path.join(DATA_DIR, "감탄_데이터준비_샘플_원본백업.xlsx")


# ────────────────────────── 새 분류 규칙 (R051~R058) ──────────────────────────
# R031(고효율 설비)·R032(CNC 장비구매) 패턴 그대로: 제외/참고, 참고분류, 사람검토필요=True
NEW_RULES = [
    dict(rule_id="R051", 우선순위=2, 대표="태양광 설비", 포함="태양광, 태양광설비, 태양광패널",
         제외="", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자", 자동="참고분류",
         검토=True, 혼합=False, 품질="E", 근거="재생에너지 설비투자, 배출량 계산 대상 아니나 녹색여신 참고",
         예시="태양광 설비 설치"),
    dict(rule_id="R052", 우선순위=2, 대표="ESS 설치", 포함="ESS, 에너지저장장치, 배터리저장",
         제외="", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자", 자동="참고분류",
         검토=True, 혼합=False, 품질="E", 근거="에너지저장장치 설치, 녹색여신·설비금융 참고",
         예시="ESS 설치 공사"),
    dict(rule_id="R053", 우선순위=2, 대표="전동지게차 리스", 포함="전동지게차, 전동 지게차, 전기지게차 리스",
         제외="전기지게차 충전전력(사용료) 아님", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자",
         자동="참고분류", 검토=True, 혼합=False, 품질="E",
         근거="경유 지게차 대체 리스, 리스금융 참고(사용전력은 R041 별도)", 예시="전동지게차 리스료"),
    dict(rule_id="R054", 우선순위=2, 대표="히트펌프", 포함="히트펌프, 열펌프",
         제외="", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자", 자동="참고분류",
         검토=True, 혼합=False, 품질="E", 근거="에너지효율 설비투자, 설비금융 참고", 예시="히트펌프 설치"),
    dict(rule_id="R055", 우선순위=2, 대표="집진기", 포함="집진기, 대기방지시설",
         제외="", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자", 자동="참고분류",
         검토=True, 혼합=False, 품질="E", 근거="오염방지 설비투자, 환경설비금융 참고", 예시="집진기 설치"),
    dict(rule_id="R056", 우선순위=2, 대표="폐수처리설비", 포함="폐수처리설비, 수처리설비",
         제외="", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자", 자동="참고분류",
         검토=True, 혼합=False, 품질="E", 근거="수처리 설비투자, 환경설비금융 참고", 예시="폐수처리설비 구축"),
    dict(rule_id="R057", 우선순위=2, 대표="재활용 설비", 포함="재활용설비, 재활용 설비",
         제외="", scope="제외/참고", 분류="감축투자 후보", 연료="설비투자", 자동="참고분류",
         검토=True, 혼합=False, 품질="E", 근거="순환경제 설비투자, 녹색여신 참고", 예시="재활용 설비 도입"),
    dict(rule_id="R058", 우선순위=2, 대표="설비 유지보수비", 포함="유지보수비, 유지보수, 정기점검",
         제외="신규 설비 구매 아님", scope="검토", 분류="설비투자 불명확", 연료="없음", 자동="사람검토",
         검토=True, 혼합=False, 품질="C", 근거="신규 설비투자인지 단순 수리인지 불명확, 사람검토 필요",
         예시="공조설비 유지보수비"),
]


def rule_row(r):
    return [r["rule_id"], r["우선순위"], r["대표"], r["포함"], r["제외"], r["scope"], r["분류"],
            r["연료"], r["자동"], r["검토"], r["혼합"], r["품질"], r["근거"], r["예시"]]


# ────────────────────────── 새 전표 (I042~I050) ──────────────────────────
# 컬럼: 전표ID,기업ID,날짜,거래처,품목명,공급가액,부가세,합계금액,수량,단위,
#       정답Scope,정답분류,정답연료,데이터품질,혼합품목,배분규칙,사람검토필요,근거,개발메모
NEW_VOUCHERS = [
    dict(id="I042", co="C002", date="2025-05-10", supplier="솔라테크", item="태양광 설비 설치",
         supply=30_000_000, qty=1, unit="식", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="재생에너지 설비투자, 배출량 계산 제외, 녹색여신 참고", memo="K-택소노미 후보(태양광)"),
    dict(id="I043", co="C001", date="2025-05-15", supplier="대한에너지솔루션", item="ESS 설치 공사",
         supply=18_000_000, qty=1, unit="식", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="에너지저장장치 설치, 녹색여신·설비금융 참고", memo="K-택소노미 후보(ESS)"),
    dict(id="I044", co="C003", date="2025-05-20", supplier="전동물류", item="전동지게차 리스료",
         supply=1_200_000, qty=1, unit="대", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="경유 지게차 대체 리스, 리스금융 참고", memo="K-택소노미 후보(전동화)"),
    dict(id="I045", co="C004", date="2025-05-22", supplier="대성설비", item="히트펌프 설치",
         supply=8_500_000, qty=1, unit="대", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="에너지효율 설비투자, 설비금융 참고", memo="K-택소노미 후보(히트펌프)"),
    dict(id="I046", co="C005", date="2025-05-25", supplier="환경엔지니어링", item="집진기 설치",
         supply=12_000_000, qty=1, unit="식", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="오염방지 설비투자, 환경설비금융 참고", memo="K-택소노미 후보(집진기)"),
    dict(id="I047", co="C006", date="2025-05-28", supplier="청정수처리", item="폐수처리설비 구축",
         supply=25_000_000, qty=1, unit="식", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="수처리 설비투자, 환경설비금융 참고", memo="K-택소노미 후보(폐수처리)"),
    dict(id="I048", co="C001", date="2025-06-02", supplier="그린리사이클", item="재활용 설비 도입",
         supply=9_800_000, qty=1, unit="식", scope="제외/참고", cat="감축투자 후보", fuel="설비투자",
         dq="E", mixed=False, alloc="참고분류", hitl=True,
         reason="순환경제 설비투자, 녹색여신 참고", memo="K-택소노미 후보(재활용)"),
    dict(id="I049", co="C002", date="2025-06-05", supplier="구미설비유지", item="공조설비 유지보수비",
         supply=850_000, qty=None, unit=None, scope="검토", cat="설비투자 불명확", fuel="없음",
         dq="C", mixed=False, alloc="HITL", hitl=True,
         reason="신규 설비투자인지 단순 수리인지 불명확", memo="HITL(설비투자 불명확)"),
    dict(id="I050", co="C001", date="2025-03-12", supplier="구미에너지", item="지게차 경유 외 1종",
         supply=654_000, qty=500, unit="L", scope="제외", cat="중복전표", fuel="없음",
         dq="E", mixed=False, alloc="중복제외", hitl=False,
         reason="I001과 완전 동일한 문서(중복 업로드), 자동 중복 제외 대상",
         memo="중복 업로드 테스트 케이스(=I001)"),
]


def voucher_row(v):
    vat = round(v["supply"] * 0.1)
    total = v["supply"] + vat
    return [v["id"], v["co"], v["date"], v["supplier"], v["item"], v["supply"], vat, total,
            v["qty"], v["unit"], v["scope"], v["cat"], v["fuel"], v["dq"], v["mixed"],
            v["alloc"], v["hitl"], v["reason"], v["memo"]]


# 배출량이 필요한 신규 전표는 없음(전부 제외/참고 또는 HITL 미확정) → 활동량·배출계수·예상배출량 0
def expected_row(v):
    return [v["id"], v["item"], v["scope"], v["fuel"], v["supply"], 0, 0, 0, 0, v["hitl"],
            v["reason"],
            ("배출량 계산 제외 · K-택소노미 후보" if v["alloc"] == "참고분류"
             else "사람검토필요로 넘김" if v["hitl"]
             else "중복 전표 자동 제외")]


# ────────────────────────── 기대_결과 원본 41행 (정적 값으로 고정) ──────────────────────────
# 원본 시트의 이 41행은 전표_샘플을 참조하는 라이브 수식(예: =전표_샘플!A2)이다.
# openpyxl은 수식은 보존해도 캐시된 계산값은 재저장 시 버리므로(재계산 엔진이 없음),
# db/excel_loader.py의 data_only=True 읽기가 전부 None이 되어 계산 엔진 골든셋이
# 깨진다. 그래서 이 41행은 원본 파일을 열어 확인한 캐시값 그대로 정적 값으로 고정해
# 다시 쓴다 — 값 자체는 원본과 100% 동일, 수식→정적값 전환만 일어난다.
ORIGINAL_EXPECTED_RESULTS = [
    ("I001", "지게차 경유 외 1종", "Scope 1", "경유", 654000, 500, "L", 2.616, 1308, False,
     "지게차+경유가 명시되어 직접배출", "Scope 1 / 경유 / 1308.0 kgCO2e"),
    ("I002", "공장 전기요금", "Scope 2", "전기", 1200000, 3500, "kWh", 0.4541, 1589.35, False,
     "한전 전기요금은 Scope 2", "Scope 2 / 전기 / 1589.4 kgCO2e"),
    ("I003", "사무용품 구입", "제외", "없음", 150000, 0, 0, 0, 0, False,
     "탄소 산정 대상 아님", "탄소 산정 제외"),
    ("I004", "공장 용접용 가스비", "Scope 1", "가스종류 불명", 320000, 0, 0, 0, 0, True,
     "가스 종류가 불명확해 사람검토 필요", "사람검토필요로 넘김"),
    ("I005", "납품차량 경유 주유", "Scope 1", "경유", 410000, 310, "L", 2.616, 810.96, False,
     "납품차량+경유 명시", "Scope 1 / 경유 / 811.0 kgCO2e"),
    ("I006", "4월 전력 사용료", "Scope 2", "전기", 1380000, 4100, "kWh", 0.4541, 1861.81, False,
     "전력 사용료는 Scope 2", "Scope 2 / 전기 / 1861.8 kgCO2e"),
    ("I007", "도시가스 요금", "Scope 1", "도시가스", 220000, 180, "m3", 2.21, 397.8, False,
     "도시가스 사용량 존재", "Scope 1 / 도시가스 / 397.8 kgCO2e"),
    ("I008", "공장 소모품 외 2종", "제외", "없음", 275000, 0, 0, 0, 0, True,
     "품목이 모호하고 탄소 항목 여부 불확실", "사람검토필요로 넘김"),
    ("I009", "LPG 연료비", "Scope 1", "LPG", 180000, 95, "kg", 3.722, 353.59, True,
     "LPG는 kg/L/Nm3 단위 확인 필요", "사람검토필요로 넘김"),
    ("I010", "전기료", "Scope 2", "전기", 980000, 2800, "kWh", 0.4541, 1271.48, False,
     "전기료 키워드", "Scope 2 / 전기 / 1271.5 kgCO2e"),
    ("I011", "유류대금", "Scope 1", "연료종류 불명", 355000, 0, 0, 0, 0, True,
     "경유/휘발유 구분 불가", "사람검토필요로 넘김"),
    ("I012", "경유", "Scope 1", "경유", 785000, 600, "L", 2.616, 1569.6000000000001, False,
     "경유 명시", "Scope 1 / 경유 / 1569.6 kgCO2e"),
    ("I013", "산소/아르곤 가스", "검토", "산업가스", 440000, 0, 0, "", "", True,
     "공정용 가스이나 배출계수 적용 여부 검토 필요", "사람검토필요로 넘김"),
    ("I014", "복사용지 및 토너", "제외", "없음", 210000, 0, 0, 0, 0, False,
     "일반 사무비용", "탄소 산정 제외"),
    ("I015", "공장 전기료", "Scope 2", "전기", 1120000, 3300, "kWh", 0.4541, 1498.53, False,
     "전기료는 Scope 2", "Scope 2 / 전기 / 1498.5 kgCO2e"),
    ("I016", "보일러 도시가스", "Scope 1", "도시가스", 360000, 295, "m3", 2.21, 651.95, False,
     "보일러+도시가스 명시", "Scope 1 / 도시가스 / 652.0 kgCO2e"),
    ("I017", "전력 사용료", "Scope 2", "전기", 1540000, 4600, "kWh", 0.4541, 2088.86, False,
     "전력 사용료", "Scope 2 / 전기 / 2088.9 kgCO2e"),
    ("I018", "지게차 경유", "Scope 1", "경유", 520000, 400, "L", 2.616, 1046.4, False,
     "지게차 경유 명시", "Scope 1 / 경유 / 1046.4 kgCO2e"),
    ("I019", "야근 식대", "제외", "없음", 180000, 0, 0, 0, 0, False,
     "식대는 MVP 제외", "탄소 산정 제외"),
    ("I020", "공장 난방 LPG", "Scope 1", "LPG", 260000, 135, "kg", 3.722, 502.46999999999997, True,
     "LPG는 kg/L/Nm3 단위 확인 필요", "사람검토필요로 넘김"),
    ("I021", "지게차 정비비", "제외", "없음", 300000, 0, 0, 0, 0, False,
     "정비비는 연료 사용량 아님", "탄소 산정 제외"),
    ("I022", "전기요금", "Scope 2", "전기", 1650000, 5000, "kWh", 0.4541, 2270.5, False,
     "전기요금 키워드", "Scope 2 / 전기 / 2270.5 kgCO2e"),
    ("I023", "경유 외 1종", "Scope 1", "경유", 432000, 330, "L", 2.616, 863.2800000000001, False,
     "경유가 주품목으로 명확", "Scope 1 / 경유 / 863.3 kgCO2e"),
    ("I024", "3월 전기요금", "Scope 2", "전기", 760000, 2200, "kWh", 0.4541, 999.02, False,
     "전기요금", "Scope 2 / 전기 / 999.0 kgCO2e"),
    ("I025", "절삭유 및 소모품", "검토", "없음", 390000, 0, 0, 0, 0, True,
     "절삭유는 배출 산정 포함 여부 판단 필요", "사람검토필요로 넘김"),
    ("I026", "도시가스", "Scope 1", "도시가스", 190000, 160, "m3", 2.21, 353.6, False,
     "도시가스 명시", "Scope 1 / 도시가스 / 353.6 kgCO2e"),
    ("I027", "사무용 의자", "제외", "없음", 280000, 0, 0, 0, 0, False,
     "일반비용", "탄소 산정 제외"),
    ("I028", "공장 전력료", "Scope 2", "전기", 830000, 2450, "kWh", 0.4541, 1112.545, False,
     "전력료는 Scope 2", "Scope 2 / 전기 / 1112.5 kgCO2e"),
    ("I029", "화물차 경유", "Scope 1", "경유", 910000, 700, "L", 2.616, 1831.2, False,
     "화물차 경유 명시", "Scope 1 / 경유 / 1831.2 kgCO2e"),
    ("I030", "전기 사용료", "Scope 2", "전기", 1950000, 5800, "kWh", 0.4541, 2633.78, False,
     "전기 사용료", "Scope 2 / 전기 / 2633.8 kgCO2e"),
    ("I031", "공장 가스비", "Scope 1", "가스종류 불명", 270000, 0, 0, 0, 0, True,
     "가스 종류 불명확", "사람검토필요로 넘김"),
    ("I032", "직원 식대", "제외", "없음", 420000, 0, 0, 0, 0, False,
     "식대 제외", "탄소 산정 제외"),
    ("I033", "전력 사용료", "Scope 2", "전기", 2100000, 6100, "kWh", 0.4541, 2770.01, False,
     "전력 사용료", "Scope 2 / 전기 / 2770.0 kgCO2e"),
    ("I034", "휘발유", "Scope 1", "휘발유", 120000, 70, "L", 2.221, 155.47, False,
     "휘발유 명시", "Scope 1 / 휘발유 / 155.5 kgCO2e"),
    ("I035", "전기요금", "Scope 2", "전기", 640000, 1900, "kWh", 0.4541, 862.79, False,
     "전기요금", "Scope 2 / 전기 / 862.8 kgCO2e"),
    ("I036", "LPG", "Scope 1", "LPG", 155000, 80, "kg", 3.722, 297.76, True,
     "LPG는 kg/L/Nm3 단위 확인 필요", "사람검토필요로 넘김"),
    ("I037", "기타 유류대", "Scope 1", "연료종류 불명", 240000, 0, 0, 0, 0, True,
     "연료 종류가 불명확", "사람검토필요로 넘김"),
    ("I038", "문구류", "제외", "없음", 76000, 0, 0, 0, 0, False,
     "문구류 제외", "탄소 산정 제외"),
    ("I039", "공장 전기 사용료", "Scope 2", "전기", 710000, 2100, "kWh", 0.4541, 953.61, False,
     "전기 사용료", "Scope 2 / 전기 / 953.6 kgCO2e"),
    ("I040", "도시가스 요금", "Scope 1", "도시가스", 115000, 95, "m3", 2.21, 209.95, False,
     "도시가스 사용량", "Scope 1 / 도시가스 / 210.0 kgCO2e"),
    ("I041", "경유 주유비", "Scope 1", "경유", 280000, 198.07, "L", 2.616, 518.14, False,
     "경유는 명시되어 있으나 수량이 없어 월별단가로 활동량 추정",
     "Scope 1 / 경유 / 월별단가 환산 / 518.1 kgCO2e"),
]


# ────────────────────────── 신규 시트 ──────────────────────────
COMPANY_MASTER = [
    ("company_id", "company_name", "region", "industry", "employee_count",
     "annual_revenue_krw", "main_energy_type", "note"),
    ("C001", "구미정밀", "경북 구미", "금속가공", 18, 2_500_000_000, "전기, 경유", "전표_샘플 I001~I008, I043, I048, I050"),
    ("C002", "대경부품", "경북 경산", "전자부품", 12, 1_800_000_000, "전기, LPG, 경유", "전표_샘플 I009~I015, I042, I049"),
    ("C003", "성서테크", "대구 달서", "표면처리", 25, 3_200_000_000, "전기, 경유, 도시가스, LPG", "전표_샘플 I016~I022, I044"),
    ("C004", "칠곡소재", "경북 칠곡", "플라스틱 부품", 9, 950_000_000, "전기, 경유, 도시가스", "전표_샘플 I023~I028, I045"),
    ("C005", "포항이엔지", "경북 포항", "표면처리", 15, 2_100_000_000, "전기, 경유, 휘발유", "전표_샘플 I029~I034, I046"),
    ("C006", "대구정공", "대구 북구", "금속가공", 11, 1_400_000_000, "전기, LPG, 도시가스, 경유", "전표_샘플 I035~I041, I047"),
]

MYDATA_DOCUMENTS = [
    ("doc_id", "company_id", "provider", "document_name", "collected_status", "used_for", "limitation"),
]
_MD_TEMPLATE = [
    ("국세청", "사업자등록증명", "기업 식별"),
    ("중소벤처기업부", "중소기업확인서", "중소기업 여부 확인"),
]
_n = 1
for _co in ["C001", "C002", "C003", "C004", "C005", "C006"]:
    for _provider, _doc, _use in _MD_TEMPLATE:
        MYDATA_DOCUMENTS.append((f"MD{_n:03d}", _co, _provider, _doc, "확인완료", _use, "탄소 사용량 정보 없음"))
        _n += 1

UPLOADED_FILES = [
    ("file_id", "company_id", "file_name", "document_type", "parse_status",
     "reject_status", "reject_reason", "linked_record_id"),
    ("F001", "C002", "2025_05_태양광_세금계산서.pdf", "세금계산서", "성공", "N", "", "I042"),
    ("F002", "C001", "2025_05_ESS_세금계산서.pdf", "세금계산서", "성공", "N", "", "I043"),
    ("F003", "C003", "2025_05_지게차리스_세금계산서.pdf", "세금계산서", "성공", "N", "", "I044"),
    ("F004", "C002", "2025_06_유지보수비_영수증.jpg", "영수증", "부분성공", "N", "설비투자 여부 불명확", "I049"),
    ("F005", "C001", "2025_03_경유_세금계산서(2).pdf", "세금계산서", "성공", "N", "", "I050"),
    ("F006", "C004", "식비영수증.jpg", "기타", "실패", "Y", "탄소계산과 무관한 파일(전표 미생성)", ""),
]

K_TAXONOMY_MAPPING = [
    ("kt_rule_id", "keyword", "candidate_type", "facility_type", "finance_lead_type",
     "hitl_required", "linked_rule_id", "evidence_rule"),
    ("KT001", "태양광", "재생에너지 설비", "태양광 설비", "녹색여신 후보", True, "R051", "품목명에 '태양광' 포함"),
    ("KT002", "ESS", "에너지저장장치", "ESS", "녹색여신·설비금융 후보", True, "R052", "품목명에 'ESS' 포함"),
    ("KT003", "전동지게차", "저탄소 장비 전환", "전동지게차", "리스금융 후보", True, "R053", "품목명에 '전동지게차' 포함"),
    ("KT004", "고효율 설비", "에너지효율 개선", "공조설비 등", "설비금융 후보", True, "R031", "품목명에 '고효율' 포함(기존 R031)"),
    ("KT005", "히트펌프", "에너지효율 개선", "열관리 설비", "설비금융 후보", True, "R054", "품목명에 '히트펌프' 포함"),
    ("KT006", "집진기", "오염방지 및 관리", "대기방지시설", "환경설비금융 후보", True, "R055", "품목명에 '집진기' 포함"),
    ("KT007", "폐수처리설비", "물 관리/오염방지", "수처리 설비", "환경설비금융 후보", True, "R056", "품목명에 '폐수처리설비' 포함"),
    ("KT008", "재활용 설비", "순환경제 전환", "재활용 설비", "녹색여신 후보", True, "R057", "품목명에 '재활용 설비' 포함"),
    ("KT009", "CNC 장비구매", "설비투자(자동화)", "CNC 장비", "설비금융 후보", False, "R032", "품목명에 'CNC' 포함(기존 R032, 최종판정 아님)"),
]

FACILITY_KEYWORDS = [
    ("keyword_id", "category", "keyword", "default_lead_type", "risk_note"),
    ("FK001", "재생에너지", "태양광", "녹색여신 후보", "설치 목적 확인 필요"),
    ("FK002", "에너지저장", "ESS", "녹색여신 후보", "재생에너지 연계 여부 확인 필요"),
    ("FK003", "전동화", "전동지게차", "리스금융 후보", "기존 경유 장비 대체 여부 확인 필요"),
    ("FK004", "에너지효율", "고효율 설비", "설비금융 후보", "고효율 인증·교체 여부 확인 필요(기존 R031)"),
    ("FK005", "열관리", "히트펌프", "설비금융 후보", "사용처 확인 필요"),
    ("FK006", "오염방지", "집진기", "환경설비금융 후보", "설비투자 규모 확인 필요"),
    ("FK007", "수처리", "폐수처리설비", "환경설비금융 후보", "처리 대상 확인 필요"),
    ("FK008", "순환경제", "재활용 설비", "녹색여신 후보", "재활용 대상·비율 확인 필요"),
    ("FK009", "보류", "유지보수비", "검토필요", "신규 설비투자인지 단순 수리인지 불명확"),
]

BANK_LOANS_MOCK_HEADER = ("loan_id", "company_id", "loan_balance_krw", "total_equity_krw",
                           "total_liabilities_krw", "company_value_proxy_krw", "attribution_factor",
                           "company_emissions_tco2e_sample", "attributed_emissions_tco2e", "note")
# (company_id, loan_balance, equity, liabilities) — 매출 규모(company_master)에 비례해 임의 산정
_LOAN_INPUT = {
    "C001": (500_000_000, 2_000_000_000, 4_000_000_000),
    "C002": (300_000_000, 1_700_000_000, 3_300_000_000),
    "C003": (800_000_000, 3_200_000_000, 4_800_000_000),
    "C004": (150_000_000, 500_000_000, 700_000_000),
    "C005": (400_000_000, 1_800_000_000, 3_000_000_000),
    "C006": (250_000_000, 1_200_000_000, 2_100_000_000),
}

PORTFOLIO_DASHBOARD_MOCK = [
    ("segment_id", "region", "industry", "sample_company_id", "avg_wadqs_before",
     "avg_wadqs_after", "note"),
    ("S001", "경북 구미", "금속가공", "C001", 5.0, 2.8, "표본 1개 기업 기준, 실제 포트폴리오 집계 아님(mock)"),
    ("S002", "경북 경산", "전자부품", "C002", 5.0, 3.0, "표본 1개 기업 기준, 실제 포트폴리오 집계 아님(mock)"),
    ("S003", "대구 달서", "표면처리", "C003", 5.0, 3.1, "표본 1개 기업 기준, 실제 포트폴리오 집계 아님(mock)"),
    ("S004", "경북 칠곡", "플라스틱 부품", "C004", 5.0, 3.6, "표본 1개 기업 기준, 실제 포트폴리오 집계 아님(mock)"),
    ("S005", "경북 포항", "표면처리", "C005", 5.0, 3.2, "표본 1개 기업 기준, 실제 포트폴리오 집계 아님(mock)"),
    ("S006", "대구 북구", "금속가공", "C006", 5.0, 3.3, "표본 1개 기업 기준, 실제 포트폴리오 집계 아님(mock)"),
]

# 사람검토필요=TRUE 인 기존 행 + 신규 행 전부를 HITL 큐로 노출
HITL_QUEUE_MOCK_HEADER = ("hitl_id", "company_id", "source_record_id", "issue_type",
                           "original_text", "confidence", "evidence", "reviewer_action_needed", "final_status")
_HITL_SOURCE = [
    # (voucher_id, company_id, item, issue_type, confidence, reviewer_action, status)
    ("I004", "C001", "공장 용접용 가스비", "가스 종류 불명확", 0.55, "가스 종류 확인 요청", "완료"),
    ("I008", "C001", "공장 소모품 외 2종", "제외 여부 불명확", 0.50, "품목 세부내역 확인", "대기"),
    ("I009", "C002", "LPG 연료비", "LPG 단위 불명확", 0.60, "kg/L/Nm3 단위 확인", "완료"),
    ("I011", "C002", "유류대금", "연료 종류 불명확", 0.55, "경유/휘발유 구분 요청", "대기"),
    ("I013", "C002", "산소/아르곤 가스", "배출계수 적용 여부 검토", 0.65, "공정용 가스 여부 확인", "대기"),
    ("I020", "C003", "공장 난방 LPG", "LPG 단위 불명확", 0.60, "kg/L/Nm3 단위 확인", "대기"),
    ("I025", "C004", "절삭유 및 소모품", "산정 포함 여부 판단 필요", 0.70, "Scope3 후보 여부 검토", "대기"),
    ("I031", "C005", "공장 가스비", "가스 종류 불명확", 0.55, "가스 종류 확인 요청", "대기"),
    ("I036", "C006", "LPG", "LPG 단위 불명확", 0.60, "kg/L/Nm3 단위 확인", "대기"),
    ("I037", "C006", "기타 유류대", "연료 종류 불명확", 0.55, "경유/휘발유 구분 요청", "대기"),
    ("I042", "C002", "태양광 설비 설치", "K-택소노미 후보", 0.92, "녹색여신 검토", "대기"),
    ("I043", "C001", "ESS 설치 공사", "K-택소노미 후보", 0.90, "녹색여신·설비금융 검토", "대기"),
    ("I044", "C003", "전동지게차 리스료", "K-택소노미 후보", 0.85, "리스금융 리드 검토", "대기"),
    ("I045", "C004", "히트펌프 설치", "K-택소노미 후보", 0.83, "설비금융 리드 검토", "대기"),
    ("I046", "C005", "집진기 설치", "K-택소노미 후보", 0.86, "환경설비금융 리드 검토", "대기"),
    ("I047", "C006", "폐수처리설비 구축", "K-택소노미 후보", 0.87, "환경설비금융 리드 검토", "대기"),
    ("I048", "C001", "재활용 설비 도입", "K-택소노미 후보", 0.84, "녹색여신 리드 검토", "대기"),
    ("I049", "C002", "공조설비 유지보수비", "설비투자 불명확", 0.50, "세부 내역·목적 확인 요청", "대기"),
]


def build_readme():
    return [
        ("항목", "내용"),
        ("이 파일의 역할", "db/excel_loader.py가 실제로 읽는 운영 데이터 파일. 전표_샘플·분류_기준표_확장·배출계수·월별단가·기대_결과 5개 시트는 원본 그대로이며 행만 확장됨"),
        ("확장 일자", "2026-08-12"),
        ("확장 스크립트", "scripts/extend_data_sample.py (python -m scripts.extend_data_sample)"),
        ("추가된 전표", "I042~I050 (9건) — 분류_기준표_확장 R051~R058(8개 규칙) 신설에 대응하는 예시. 기대_결과에도 대응 행 추가"),
        ("추가된 시나리오", "태양광·ESS·전동지게차·히트펌프·집진기·폐수처리설비·재활용설비(K-택소노미/설비투자 참고분류), 설비투자 불명확 유지보수비(HITL), 동일 전표 중복 업로드(자동 제외)"),
        ("추가된 신규 시트", "company_master, mydata_documents, uploaded_files, k_taxonomy_mapping, facility_keywords, hitl_queue_mock, bank_loans_mock, portfolio_dashboard_mock — 기존 파일에 없던 개념만 추가, 배출계수/월별단가/분류규칙/기대결과는 기존 것을 그대로 사용"),
        ("원본 백업", "감탄_데이터준비_샘플_원본백업.xlsx (이 파일을 확장하기 전 원본)"),
        ("주의", "bank_loans_mock·portfolio_dashboard_mock은 전부 시연용 mock, 실제 여신·재무데이터 아님"),
    ]


def find_last_id_row(ws) -> int:
    """A열(ID)이 비어있지 않은 마지막 행 번호."""
    last = 1
    for row in ws.iter_rows(min_row=2, max_col=1):
        if row[0].value not in (None, ""):
            last = row[0].row
    return last


def append_rows(ws, start_row: int, rows: list[list]):
    # ws.cell(..., value=None) is a no-op in openpyxl (None is the "unset" sentinel),
    # so it would silently leave a stale formula behind instead of clearing the cell.
    # Assign .value directly so None always overwrites.
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            ws.cell(row=start_row + i, column=j + 1).value = val


def resize_tables(ws, last_row: int):
    """시트에 걸린 Excel Table(ListObject)의 ref 범위를 새 마지막 행까지 넓힌다.

    행을 append_rows로 추가해도 openpyxl은 기존 Table 정의(xl/tables/*.xml)의
    ref를 자동으로 갱신하지 않는다 — 그 결과 Table의 선언된 범위 밖에 데이터가
    남게 되어, Excel은 관대하게 열어주지만 일부 xlsx 뷰어(예: VS Code 확장)는
    Table 컬럼 매핑에서 undefined 접근으로 파일을 아예 열지 못한다.
    """
    for table in ws.tables.values():
        first_col_letter = table.ref.split(":")[0].rstrip("0123456789")
        col_count = len(table.tableColumns)
        last_col_letter = get_column_letter(
            openpyxl.utils.column_index_from_string(first_col_letter) + col_count - 1
        )
        table.ref = f"{first_col_letter}1:{last_col_letter}{last_row}"


def write_new_sheet(wb, name, header_and_rows):
    ws = wb.create_sheet(title=name)
    for row in header_and_rows:
        ws.append(list(row))
    return ws


def main():
    if not os.path.exists(BACKUP):
        shutil.copy2(TARGET, BACKUP)
        print(f"[OK] 원본 백업 → {BACKUP}")
    else:
        print(f"[SKIP] 백업 이미 존재 → {BACKUP} (재실행 시 원본을 덮어쓰지 않음)")

    wb = openpyxl.load_workbook(TARGET)

    ws_voucher = wb["전표_샘플"]
    start = find_last_id_row(ws_voucher) + 1
    append_rows(ws_voucher, start, [voucher_row(v) for v in NEW_VOUCHERS])
    resize_tables(ws_voucher, start + len(NEW_VOUCHERS) - 1)
    print(f"[OK] 전표_샘플 +{len(NEW_VOUCHERS)}행 (from row {start})")

    ws_rules = wb["분류_기준표_확장"]
    start = find_last_id_row(ws_rules) + 1
    append_rows(ws_rules, start, [rule_row(r) for r in NEW_RULES])
    resize_tables(ws_rules, start + len(NEW_RULES) - 1)
    print(f"[OK] 분류_기준표_확장 +{len(NEW_RULES)}행 (from row {start})")

    # 기대_결과: 원본 41행이 전표_샘플을 참조하는 라이브 수식이라 openpyxl 재저장 시
    # 캐시값을 잃는다 → 원본 41행을 정적 값으로 다시 쓰고(값은 원본과 동일), 그 뒤에
    # 신규 9행을 붙인다. find_last_id_row로 "기존 행 보존 후 append"하지 않는 이유.
    ws_expected = wb["기대_결과"]
    append_rows(ws_expected, 2, [list(r) for r in ORIGINAL_EXPECTED_RESULTS])
    start = 2 + len(ORIGINAL_EXPECTED_RESULTS)
    append_rows(ws_expected, start, [expected_row(v) for v in NEW_VOUCHERS])
    resize_tables(ws_expected, start + len(NEW_VOUCHERS) - 1)
    print(f"[OK] 기대_결과: 원본 {len(ORIGINAL_EXPECTED_RESULTS)}행을 정적 값으로 고정 + "
          f"신규 {len(NEW_VOUCHERS)}행 추가 (from row {start})")

    # bank_loans_mock: 표본 전표(기존+신규)의 기대_결과 배출량을 기업별로 합산해 산정
    # (전표_샘플에서 전표ID→기업ID 매핑을 만들어 기대_결과와 조인)
    emissions_by_company: dict[str, float] = {}
    voucher_to_company = {}
    for row in ws_voucher.iter_rows(min_row=2, values_only=True):
        vid, co = row[0], row[1]
        if vid:
            voucher_to_company[vid] = co
    for row in ws_expected.iter_rows(min_row=2, values_only=True):
        vid, kgco2e = row[0], row[8]
        if not vid or not kgco2e:
            continue
        co = voucher_to_company.get(vid)
        if not co:
            continue
        try:
            emissions_by_company[co] = emissions_by_company.get(co, 0.0) + float(kgco2e)
        except (TypeError, ValueError):
            continue  # leftover formula string or non-numeric cell — skip

    bank_rows = [BANK_LOANS_MOCK_HEADER]
    for i, co in enumerate(["C001", "C002", "C003", "C004", "C005", "C006"], start=1):
        balance, equity, liab = _LOAN_INPUT[co]
        proxy = equity + liab
        factor = round(balance / proxy, 4)
        sample_tco2e = round(emissions_by_company.get(co, 0.0) / 1000, 4)
        attributed = round(sample_tco2e * factor, 4)
        bank_rows.append((f"L{i:03d}", co, balance, equity, liab, proxy, factor, sample_tco2e,
                           attributed, "mock — 표본 전표(전표_샘플) 배출량 합산치, 연간 환산 아님, 실제 여신·재무데이터 아님"))

    write_new_sheet(wb, "company_master", COMPANY_MASTER)
    write_new_sheet(wb, "mydata_documents", MYDATA_DOCUMENTS)
    write_new_sheet(wb, "uploaded_files", UPLOADED_FILES)
    write_new_sheet(wb, "k_taxonomy_mapping", K_TAXONOMY_MAPPING)
    write_new_sheet(wb, "facility_keywords", FACILITY_KEYWORDS)
    hitl_rows = [HITL_QUEUE_MOCK_HEADER] + [
        (f"H{i:03d}", co, vid, issue, text, conf, f"{text} — {issue}", action, status)
        for i, (vid, co, text, issue, conf, action, status) in enumerate(_HITL_SOURCE, start=1)
    ]
    write_new_sheet(wb, "hitl_queue_mock", hitl_rows)
    write_new_sheet(wb, "bank_loans_mock", bank_rows)
    write_new_sheet(wb, "portfolio_dashboard_mock", PORTFOLIO_DASHBOARD_MOCK)
    write_new_sheet(wb, "README_확장내역", build_readme())
    print("[OK] 신규 시트 8개 추가: company_master, mydata_documents, uploaded_files, "
          "k_taxonomy_mapping, facility_keywords, hitl_queue_mock, bank_loans_mock, "
          "portfolio_dashboard_mock, README_확장내역")

    wb.save(TARGET)
    print(f"[OK] 저장 완료 → {TARGET}")


if __name__ == "__main__":
    main()
