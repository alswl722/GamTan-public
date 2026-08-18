"""검증 3수치 실측 결과 (docs/v1-plan.md §5-1, docs/verification-3metrics-plan.md).

분류 정확도는 PR #92로 `기대_결과` 시트 50건(사람이 작성한 정답지) 대조 실측
확정됨(scripts/score_classification_accuracy.py) — DB 상태와 무관한 정적
결과라 상수로 고정한다. 트랙A(MAPE)·트랙B(실물대조)는 전제 데이터(공시 기업
리스트업·실물 파일럿 기업) 미확보로 여전히 미착수.

api/routers/admin.py(JSON 응답)와 db/reports/climate_risk_report_pdf.py(PDF)
양쪽이 참조한다 — 라우터를 거꾸로 import하지 않도록 별도 모듈로 둔다.
"""

CLASSIFICATION_ACCURACY_RESULT = {
    "status": "measured",
    "overall_pct": 98.0,
    "auto_confirmed_pct": 97.4,
    "hitl_recall_pct": 100.0,
    "sample_size": 50,
    "note": "기대_결과 50건 정답지 기준 실측(PR #92). HITL 재현율은 K택소노미 리드 제외 기준.",
}

TRACK_A_MAPE_RESULT = {
    "status": "pending",
    "note": "산정 예정 — 공시 기업 리스트업 미확보",
}

TRACK_B_FIELD_TEST_RESULT = {
    "status": "pending",
    "note": "산정 예정 — 실물 파일럿 기업 미섭외",
}
