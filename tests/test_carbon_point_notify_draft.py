"""§4 알림 트리거 + 신청서 초안 생성.

핵심 규약 3개를 잠근다:
  - 자격 미충족·계산 불가면 알림을 만들지 않는다(빈 알림으로 배너를 채우지 않는다).
  - 같은 기업의 안 읽은 알림이 있으면 중복 생성하지 않는다(이 테이블 첫 dedup).
  - 초안 응답은 프론트 `CarbonPointDraft` 계약과 필드명·타입이 같아야 하고, 못 채운 값은
    빈 문자열이 아니라 None이어야 한다(실패 가시성).
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.carbon_neutral_point import (
    APPLICANT_FIELDS,
    BLANK_BY_POLICY,
    INCENTIVE_TYPES,
    MISSING_CONTRACT_TYPE,
    MISSING_GAS,
    MISSING_WATER,
    NOTIFICATION_TYPE_ELIGIBLE,
    REMAINING_FIELDS,
    THRESHOLD_PCT,
    build_application_draft,
    evaluate_eligibility,
    missing_required_keys,
    notify_if_eligible,
    save_applicant_input,
)
from db.models import (
    Base,
    CarbonNeutralPointApplication,
    Classification,
    Company,
    FinancialInstitution,
    OwnerNotification,
    SourceDocument,
    Voucher,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def setup(db):
    inst = FinancialInstitution(name="감탄 데모", reporting_currency="KRW", tenant_key="demo")
    company = Company(name="동성로카페", industry_code="I561", region="대구 중구")
    db.add_all([inst, company])
    db.commit()
    return db, company, inst


def _bill(db, company, inst, year, month, kwh, contract_class="commercial"):
    """전기고지서 1장 + 전표 + 분류(전기 kWh)를 만든다."""
    db.add(SourceDocument(
        financial_institution_id=inst.id, company_id=company.id,
        document_type="electric_bill", year=year, month=month,
        contract_type="일반용(을)" if contract_class else None,
        contract_type_class=contract_class,
        extracted_json={"customer_number": "0355-7712-90"},
    ))
    v = Voucher(company_id=company.id, source="kepco", year=year, month=month,
                item_description="전기요금", supply_amount_krw=100_000)
    db.add(v)
    db.flush()
    db.add(Classification(voucher_id=v.id, scope=2, category="간접배출", fuel_type="전기",
                          activity_amount=kwh, activity_unit="kWh", status="auto"))
    db.commit()


def _eligible_history(db, company, inst):
    """2024·2025년 12개월 100kWh → 2026년 상반기 90kWh = 10% 감축(자격 충족)."""
    for year in (2024, 2025):
        for m in range(1, 13):
            _bill(db, company, inst, year, m, 100.0)
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 90.0)


# ── evaluate_eligibility ───────────────────────────────────────────────────


def test_eligibility_payload_matches_frontend_contract(setup):
    db, company, inst = setup
    _eligible_history(db, company, inst)

    info = evaluate_eligibility(db, company.id, 2026, 1)

    assert set(info) == {
        "business_scale_hint", "baseline_year", "target_year",
        "reduction_rate_pct", "eligible", "missing_data",
    }
    assert info["business_scale_hint"] == "소상공인/상업시설"
    assert info["reduction_rate_pct"] == pytest.approx(10.0)
    assert info["eligible"] is True
    assert info["baseline_year"] == 2024 and info["target_year"] == 2026
    # 수도·가스는 파싱이 없어 항상 미반영 — 숨기지 않는다
    assert MISSING_WATER in info["missing_data"]
    assert MISSING_GAS in info["missing_data"]


def test_manufacturing_is_not_calculated_at_all(setup):
    """산업용 전기는 제도상 원천 제외 — 계산해서 숨기는 게 아니라 계산 자체를 안 한다."""
    db, company, inst = setup
    for year in (2024, 2025):
        for m in range(1, 13):
            _bill(db, company, inst, year, m, 100.0, contract_class="industrial")
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 10.0, contract_class="industrial")  # 90% 감축이어도

    info = evaluate_eligibility(db, company.id, 2026, 1)
    assert info["business_scale_hint"] == "제조업/산업체"
    assert info["reduction_rate_pct"] is None
    assert info["eligible"] is False


def test_residential_is_not_calculated_and_asks_for_nothing(setup):
    """주택용도 계산하지 않는다(2026-08-25 확정: 법인참여만 지원).

    제조업과 다른 점은 `missing_data`가 비어야 한다는 것이다 — 계약종별을 못 읽은 게
    아니라 읽었고 대상이 아니므로, 사장님에게 더 올릴 게 있다고 말하면 거짓이 된다.
    """
    db, company, inst = setup
    for year in (2024, 2025):
        for m in range(1, 13):
            _bill(db, company, inst, year, m, 100.0, contract_class="residential")
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 10.0, contract_class="residential")  # 90% 감축이어도

    info = evaluate_eligibility(db, company.id, 2026, 1)
    assert info["business_scale_hint"] == "가정용/개인참여"
    assert info["reduction_rate_pct"] is None
    assert info["eligible"] is False
    assert info["missing_data"] == []


def test_unknown_contract_type_surfaces_as_missing_data(setup):
    db, company, inst = setup
    _bill(db, company, inst, 2026, 1, 90.0, contract_class=None)

    info = evaluate_eligibility(db, company.id, 2026, 1)
    assert info["business_scale_hint"] == "미확인"
    assert MISSING_CONTRACT_TYPE in info["missing_data"]
    assert info["reduction_rate_pct"] is None


def test_missing_data_names_the_real_blocker_first(setup):
    """감축률조차 계산 못 한 상태면 수도·가스 미반영을 나열하지 않는다 — 무엇이 진짜
    걸림돌인지 흐려지기 때문."""
    db, company, inst = setup
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 90.0)   # 과거 이력 없음

    info = evaluate_eligibility(db, company.id, 2026, 1)
    assert info["reduction_rate_pct"] is None
    assert MISSING_WATER not in info["missing_data"]
    assert any("과거 사용량" in m for m in info["missing_data"])


# ── 알림 트리거 ────────────────────────────────────────────────────────────


def test_notifies_when_threshold_met(setup):
    db, company, inst = setup
    _eligible_history(db, company, inst)

    note = notify_if_eligible(db, company.id, 2026, 1)

    assert note is not None
    assert note.type == NOTIFICATION_TYPE_ELIGIBLE
    assert "예상 감축률" in note.message
    # 확정치처럼 보이는 표현 금지(develop-plan §2.3)
    assert "확정" not in note.message
    assert note.payload["reduction_rate_pct"] == pytest.approx(10.0)
    assert note.payload["threshold_pct"] == THRESHOLD_PCT


def test_no_notification_when_not_eligible(setup):
    """근거 없이 레코드를 만들지 않는다 — rate_approvals가 활동자료 없는 요청을 거부하는
    것과 같은 결."""
    db, company, inst = setup
    for year in (2024, 2025):
        for m in range(1, 13):
            _bill(db, company, inst, year, m, 100.0)
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 99.0)   # 1% 감축 — 미달

    assert notify_if_eligible(db, company.id, 2026, 1) is None
    assert db.execute(select(OwnerNotification)).scalars().all() == []


def test_no_notification_when_reduction_uncomputable(setup):
    db, company, inst = setup
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 90.0)
    assert notify_if_eligible(db, company.id, 2026, 1) is None


def test_does_not_duplicate_unread_notification(setup):
    """조회마다 판정이 도는 구조라 가드가 없으면 알림이 계속 쌓인다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)

    first = notify_if_eligible(db, company.id, 2026, 1)
    second = notify_if_eligible(db, company.id, 2026, 1)

    assert first is not None and second is None
    assert len(db.execute(select(OwnerNotification)).scalars().all()) == 1


def test_notifies_again_after_previous_one_was_read(setup):
    """읽은 알림은 가드 대상이 아니다 — 다음 정산 구간엔 다시 알려야 한다."""
    from datetime import datetime, timezone

    db, company, inst = setup
    _eligible_history(db, company, inst)
    first = notify_if_eligible(db, company.id, 2026, 1)
    first.read_at = datetime.now(timezone.utc)
    db.commit()

    assert notify_if_eligible(db, company.id, 2026, 1) is not None
    assert len(db.execute(select(OwnerNotification)).scalars().all()) == 2


# ── 신청서 초안 ────────────────────────────────────────────────────────────


def test_draft_matches_frontend_contract(setup):
    db, company, inst = setup
    _eligible_history(db, company, inst)
    db.add(SourceDocument(
        financial_institution_id=inst.id, company_id=company.id,
        document_type="business_registration",
        extracted_json={"business_registration_no": "211-81-10011",
                        "company_name": "동성로카페", "representative": "김○○"},
    ))
    db.commit()

    draft = build_application_draft(db, company.id, 2026, 1)

    assert set(draft) == {"application_id", "status", "fields", "applicant_fields",
                          "remaining_fields", "draft_document_url"}
    assert draft["status"] == "draft"
    assert draft["draft_document_url"] is None
    for f in draft["fields"]:
        assert set(f) == {"label", "value", "source"}
        assert f["value"] is None or isinstance(f["value"], str)

    by_label = {f["label"]: f for f in draft["fields"]}
    assert by_label["상호(법인명)"]["value"] == "동성로카페"
    assert by_label["사업자등록번호"]["value"] == "211-81-10011"
    assert by_label["고지서 고객번호 — 전기"]["value"] == "0355-7712-90"
    assert by_label["예상 감축률"]["value"] == "10.0%"


def test_draft_fills_address_from_mydata(setup):
    """주소는 사업자등록증명에 있는 항목이다 — mock에 site_addr가 추가된 뒤로 채워진다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    db.add(SourceDocument(
        financial_institution_id=inst.id, company_id=company.id,
        document_type="business_registration",
        extracted_json={"business_registration_no": "211-81-10011", "company_name": "동성로카페",
                        "representative": "김○○", "site_addr": "대구 중구 ○○로 11"},
    ))
    db.commit()

    by_label = {f["label"]: f for f in build_application_draft(db, company.id, 2026, 1)["fields"]}
    assert by_label["사업장 주소"]["value"] == "대구 중구 ○○로 11"
    assert by_label["사업장 주소"]["source"] == "마이데이터 · 사업자등록증명"


def test_contact_fields_are_owner_input(setup):
    """휴대전화번호·전자메일은 마이데이터 5종에 없다(국세청·중소벤처기업부·한전 서류) —
    은행 내부 고객정보를 mock으로 지어내지 않고 사장님 입력으로 둔다(2026-08-24 결정).

    0032 이후 이 항목들은 "안내만 하는 잔여 필드"가 아니라 3단계 입력 폼(`applicant_fields`)의
    칸이다 — 화면이 실제로 값을 받아 저장하게 됐다.
    """
    db, company, inst = setup
    _eligible_history(db, company, inst)

    draft = build_application_draft(db, company.id, 2026, 1)
    by_label = {f["label"]: f for f in draft["fields"]}
    for label in ("신청인 휴대전화번호", "전자메일"):
        assert by_label[label]["value"] is None
        assert by_label[label]["source"] == "사장님 직접 입력"

    by_key = {f["key"]: f for f in draft["applicant_fields"]}
    assert by_key["applicant_phone"]["required"] is True
    assert by_key["applicant_email"]["required"] is False


def test_draft_omits_household_leftover_fields(setup):
    """서식에 남은 가정용 항목은 초안에 아예 넣지 않는다(2026-08-25).

    이전엔 value=null로 "해당 없음"을 노출했는데, 채울 수도 없고 채울 필요도 없는 칸이
    미리보기만 길게 만들어서 제외로 바꿨다. 입력 폼에도 없어야 한다.
    """
    db, company, inst = setup
    _eligible_history(db, company, inst)
    draft = build_application_draft(db, company.id, 2026, 1)

    labels = {f["label"] for f in draft["fields"]}
    for label in BLANK_BY_POLICY:
        assert label not in labels
        assert label not in " ".join(draft["remaining_fields"])
    assert not ({f["label"] for f in draft["applicant_fields"]} & set(BLANK_BY_POLICY))


def test_remaining_fields_only_carry_password_notice(setup):
    """잔여 필드는 "감탄도 사장님도 여기서 채울 수 없는 것"만 남는다.

    비밀번호는 탄소중립포인트 포털 계정의 것이라 감탄이 받아 보관할 단계가 없다 —
    타 기관 자격증명을 대신 들고 있지 않는다. 입력 폼에도 비밀번호 칸이 없어야 한다.
    """
    db, company, inst = setup
    _eligible_history(db, company, inst)
    draft = build_application_draft(db, company.id, 2026, 1)

    assert draft["remaining_fields"] == list(REMAINING_FIELDS)
    assert "비밀번호" in " ".join(draft["remaining_fields"])
    keys = {f["key"] for f in draft["applicant_fields"]}
    assert not any("password" in k or "비밀번호" in k for k in keys)


def test_applicant_fields_expose_form_spec(setup):
    """3단계 폼 명세는 백엔드가 정본이다 — 라벨·필수여부·선택지 어휘까지."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    applicant_fields = build_application_draft(db, company.id, 2026, 1)["applicant_fields"]

    assert [f["key"] for f in applicant_fields] == [f.key for f in APPLICANT_FIELDS]
    for f in applicant_fields:
        assert set(f) == {"key", "label", "input_type", "required", "group",
                          "placeholder", "help_text", "options", "visible_when", "value"}

    by_key = {f["key"]: f for f in applicant_fields}
    # 인센티브 유형 선택지는 DB CHECK와 같은 어휘여야 한다.
    assert [o["value"] for o in by_key["incentive_type"]["options"]] == [
        v for v, _ in INCENTIVE_TYPES
    ]
    # 금융정보는 서식이 "②현금으로 선택한 분에 한하여"라고 명시한 조건부 항목이다.
    assert by_key["account_number"]["visible_when"] == {"key": "incentive_type", "equals": "cash"}


def test_electric_customer_number_prefilled_from_bill(setup):
    """전기 고객번호는 고지서 파싱값을 폼 기본값으로 깔아준다 — 서식 필수 항목인데
    빈칸부터 시작하게 두면 이미 아는 값을 사장님이 다시 찾아 적게 된다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)

    by_key = {f["key"]: f
              for f in build_application_draft(db, company.id, 2026, 1)["applicant_fields"]}
    assert by_key["electric_customer_number"]["value"] == "0355-7712-90"


def test_draft_persists_row_only_when_eligible(setup):
    db, company, inst = setup
    _eligible_history(db, company, inst)

    draft = build_application_draft(db, company.id, 2026, 1)
    row = db.get(CarbonNeutralPointApplication, draft["application_id"])
    assert row.eligible is True
    assert row.reduction_rate_pct == pytest.approx(10.0)
    # 기준값은 6개월 구간으로 환산된 값이다(2년 합계가 아니라 두 구간의 평균) —
    # 감축년도 6개월 합계(540)와 월수를 맞춰야 비교가 성립한다.
    assert row.baseline_usage_json == {"electricity_kwh": 600.0}
    assert row.target_usage_json == {"electricity_kwh": 540.0}
    # 수도·가스는 키를 아예 넣지 않는다 — 0을 넣으면 "안 썼다"와 뭉개진다(원칙7)
    assert "water_m3" not in row.baseline_usage_json


def test_draft_does_not_persist_when_not_eligible(setup):
    """미달 기업의 신청서를 DB에 쌓지 않는다 — 초안 미리보기는 여전히 반환한다."""
    db, company, inst = setup
    for year in (2024, 2025):
        for m in range(1, 13):
            _bill(db, company, inst, year, m, 100.0)
    for m in range(1, 7):
        _bill(db, company, inst, 2026, m, 99.0)

    draft = build_application_draft(db, company.id, 2026, 1)
    assert draft["application_id"] is None
    assert db.execute(select(CarbonNeutralPointApplication)).scalars().all() == []


# ── 3단계 사장님 직접 입력 저장 (0032) ──────────────────────────────────────


def test_draft_reuses_existing_draft_row(setup):
    """POST를 다시 불러도 draft 행이 늘어나지 않는다.

    위저드를 다시 열 때마다 새 행이 생기면 3단계에서 받은 입력이 매번 사라진다 —
    입력이 붙어 있는 행을 재사용하고 계산값만 갱신한다.
    """
    db, company, inst = setup
    _eligible_history(db, company, inst)

    first = build_application_draft(db, company.id, 2026, 1)["application_id"]
    second = build_application_draft(db, company.id, 2026, 1)["application_id"]

    assert first == second
    assert len(db.execute(select(CarbonNeutralPointApplication)).scalars().all()) == 1


def test_draft_reuse_preserves_applicant_input(setup):
    """재계산이 사장님 입력을 지우지 않는다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    save_applicant_input(db, company.id, app_id, {"applicant_phone": "01012345678"})
    draft = build_application_draft(db, company.id, 2026, 1)

    by_key = {f["key"]: f for f in draft["applicant_fields"]}
    assert by_key["applicant_phone"]["value"] == "01012345678"
    # 초안 미리보기에도 같은 값이 반영돼야 한다 — 같은 화면의 두 단계가 다른 값을 보이면 안 된다.
    by_label = {f["label"]: f for f in draft["fields"]}
    assert by_label["신청인 휴대전화번호"]["value"] == "01012345678"


def test_draft_does_not_touch_submitted_row(setup):
    """제출했다고 표시한 신청서는 재계산 대상이 아니다 — 새 draft를 따로 만든다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    submitted_id = build_application_draft(db, company.id, 2026, 1)["application_id"]
    db.get(CarbonNeutralPointApplication, submitted_id).status = "submitted"
    db.commit()

    new_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    assert new_id != submitted_id
    assert db.get(CarbonNeutralPointApplication, submitted_id).status == "submitted"


def test_save_applicant_input_is_partial(setup):
    """보낸 key만 갱신한다 — 폼을 다 채우기 전에 나가도 지금까지 쓴 게 남아야 한다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    save_applicant_input(db, company.id, app_id, {"applicant_phone": "01011112222"})
    result = save_applicant_input(db, company.id, app_id, {"applicant_email": "a@b.com"})

    assert result["values"]["applicant_phone"] == "01011112222"
    assert result["values"]["applicant_email"] == "a@b.com"


def test_save_applicant_input_blank_becomes_null(setup):
    """빈 문자열은 "지웠다"는 뜻이라 null로 저장한다 — ""와 null이 섞이면 미입력 판정이
    두 갈래가 된다(원칙7과 같은 결)."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    save_applicant_input(db, company.id, app_id, {"applicant_email": "a@b.com"})
    result = save_applicant_input(db, company.id, app_id, {"applicant_email": "   "})

    assert result["values"]["applicant_email"] is None
    assert db.get(CarbonNeutralPointApplication, app_id).applicant_email is None


def test_save_applicant_input_parses_date(setup):
    """영업개시일자는 date 컬럼이라 ISO 문자열을 변환해 저장하고, 다시 ISO로 돌려준다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    result = save_applicant_input(db, company.id, app_id, {"business_open_date": "2019-03-14"})

    assert result["values"]["business_open_date"] == "2019-03-14"
    assert db.get(CarbonNeutralPointApplication, app_id).business_open_date.year == 2019


def test_save_applicant_input_reports_missing_required(setup):
    """필수 미입력은 에러가 아니라 목록으로 돌려준다 — 화면이 다음 단계 버튼을 막는 근거."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    result = save_applicant_input(db, company.id, app_id, {"applicant_phone": "01011112222"})

    assert "applicant_phone" not in result["missing_required"]
    assert "portal_id" in result["missing_required"]
    # 전기 고객번호는 고지서에서 읽혔지만 아직 저장 전이라 미입력으로 잡힌다 — 화면은
    # 파싱값을 기본값으로 채워 보여주고 저장 시 함께 보낸다.
    assert "electric_customer_number" in result["missing_required"]


def test_missing_required_skips_hidden_conditional_fields():
    """화면에 안 나오는 조건부 칸은 미입력으로 세지 않는다 — 인센티브를 상품권으로 골랐다면
    계좌번호는 애초에 물어보지 않았다."""
    filled = {
        "application_kind": "new", "portal_id": "cafe0001",
        "applicant_phone": "01011112222", "road_address": "대구 중구 ○○로 11",
        "electric_customer_number": "0355-7712-90",
    }
    assert missing_required_keys({**filled, "incentive_type": "gift_certificate"}) == []
    assert missing_required_keys({**filled, "incentive_type": "cash"}) == []


def test_save_applicant_input_rejects_other_company(setup):
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]

    with pytest.raises(LookupError):
        save_applicant_input(db, company.id + 999, app_id, {"applicant_phone": "01011112222"})


def test_save_applicant_input_rejects_submitted(setup):
    """이미 제출한 신청서는 수정하지 않는다 — 사장님이 실제로 낸 내용과 기록이 어긋난다."""
    db, company, inst = setup
    _eligible_history(db, company, inst)
    app_id = build_application_draft(db, company.id, 2026, 1)["application_id"]
    db.get(CarbonNeutralPointApplication, app_id).status = "submitted"
    db.commit()

    with pytest.raises(PermissionError):
        save_applicant_input(db, company.id, app_id, {"applicant_phone": "01011112222"})
