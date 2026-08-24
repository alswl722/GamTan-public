"""계약종별 정규화 + 전기고지서 추출 + business_scale_hint 판별.

소상공인 탄소중립포인트 트랙의 판별 축(data-plan §5·§6.1·§7.1) 전체를 잠근다.
fixture 파싱은 합성 PDF가 아니라 `data/fixtures/electricity_bills/` 실제 파일을 쓴다 —
`_manifest.csv`엔 `contract_type` 컬럼이 없어서 manifest 시딩으론 이 경로를 검증할 수 없다.
"""
import pdfplumber
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.carbon_neutral_point import business_scale_hint
from db.document.contract_type import normalize_contract_type_class
from db.document.document_text_extractor import parse_document_text
from db.models import Base, Company, FinancialInstitution, SourceDocument

FIXTURES = "data/fixtures/electricity_bills"


# ── 정규화 순수 함수 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("산업용(을) 고압A", "industrial"),
        ("산업용(갑)", "industrial"),
        ("산업용 을", "industrial"),          # 괄호 없는 변형
        ("일반용(을)", "commercial"),
        ("일반용(갑) 저압", "commercial"),
        ("주택용", "residential"),
        ("주택용전력", "residential"),        # 실물 고지서 표기(2026-08-17 관측)
        ("주 택 용 전 력", "residential"),    # 자간 벌어진 렌더링·OCR
    ],
)
def test_normalizes_known_contract_types(raw, expected):
    assert normalize_contract_type_class(raw) == expected


@pytest.mark.parametrize("raw", ["농사용(을)", "교육용전력", "심야전력", "가로등", "", None, "알 수 없음"])
def test_unmapped_contract_types_become_unknown(raw):
    """4종에 안 맞는 실제 계약종별을 억지로 commercial로 밀어넣지 않는다 —
    자격 없는 사업자에게 신청 안내가 가면 안 된다(§6.2)."""
    assert normalize_contract_type_class(raw) == "unknown"


# ── 실제 fixture 파싱 ──────────────────────────────────────────────────────


def _parse_fixture(path: str) -> dict:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    return parse_document_text(text, "electric_bill")


@pytest.mark.parametrize(
    "path,contract_type,cls,customer_number",
    [
        (f"{FIXTURES}/S001/동성로카페_2024-01_전기요금고지서.pdf", "일반용(을)", "commercial", "0355-7712-90"),
        (f"{FIXTURES}/S002/반월당분식_2024-01_전기요금고지서.pdf", "일반용(을)", "commercial", "0871-2245-63"),
        (f"{FIXTURES}/C001/구미정밀_2025-01_전기요금고지서.pdf", "산업용(을)", "industrial", "0284-1193-55"),
    ],
)
def test_extracts_contract_type_and_customer_number(path, contract_type, cls, customer_number):
    r = _parse_fixture(path)
    assert r["contract_type"] == contract_type
    assert r["contract_type_class"] == cls
    # 실측 버그(2026-08-24): 줄 끝까지 잡으면 고객번호에 뒷 라벨까지 붙었다
    # ("0355-7712-90 계약종별 일반용(을)").
    assert r["customer_number"] == customer_number


@pytest.mark.parametrize(
    "path,expected_amount",
    [
        (f"{FIXTURES}/S001/동성로카페_2024-01_전기요금고지서.pdf", 197_316),
        (f"{FIXTURES}/S002/반월당분식_2024-01_전기요금고지서.pdf", 177_768),
        (f"{FIXTURES}/C001/구미정밀_2025-01_전기요금고지서.pdf", 677_000),
    ],
)
def test_billed_amount_is_not_the_due_date(path, expected_amount):
    """회귀 방어(2026-08-24 수정): 이 서식은 pdfplumber 추출에서 금액이 라벨보다 앞줄에
    온다. 종전 파서는 라벨 다음 줄인 납기일을 값으로 잡아 `20240225`를 금액으로
    저장했고, 공유 DB에 그렇게 오염된 전표가 7건 있었다."""
    amount = _parse_fixture(path)["supply_amount_krw"]
    assert amount == expected_amount
    assert not (20_000_000 < amount < 21_000_000), "납기일(YYYYMMDD)을 금액으로 읽었다"


def test_contract_type_absent_is_not_a_parse_failure():
    """계약종별·고객번호가 없어도 파싱 자체는 성공해야 한다 — 없으면 배출량 계산이
    안 되는 필드가 아니므로 기존 업로드를 회귀시키면 안 된다."""
    text = "\n".join([
        "전 기 요 금 청 구 서",
        "2025년 3월분",
        "당월 사용량 전월 사용량",
        "1,200 kWh 1,100 kWh",
        "250,000 원",
        "이번달 청구금액",
    ])
    r = parse_document_text(text, "electric_bill")
    assert r["supply_amount_krw"] == 250_000
    assert r["quantity"] == 1200
    assert "contract_type" not in r
    assert "contract_type_class" not in r


# ── business_scale_hint 판별 ───────────────────────────────────────────────


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def company(db):
    inst = FinancialInstitution(name="감탄 데모", reporting_currency="KRW", tenant_key="demo")
    c = Company(name="동성로카페", industry_code="I561")
    db.add_all([inst, c])
    db.commit()
    return c, inst


def _add_bill(db, company, inst, year, month, contract_type_class, *, document_type="electric_bill"):
    db.add(SourceDocument(
        financial_institution_id=inst.id, company_id=company.id,
        document_type=document_type, year=year, month=month,
        contract_type="(원문)" if contract_type_class else None,
        contract_type_class=contract_type_class,
    ))
    db.commit()


def test_hint_industrial(db, company):
    c, inst = company
    _add_bill(db, c, inst, 2026, 1, "industrial")
    assert business_scale_hint(db, c.id) == "제조업/산업체"


@pytest.mark.parametrize("cls", ["commercial", "residential"])
def test_hint_commercial_covers_residential(db, company, cls):
    """주택용도 소상공인 쪽으로 본다 — 제도 대상이 가정용·상업용 전기다(§6.2)."""
    c, inst = company
    _add_bill(db, c, inst, 2026, 1, cls)
    assert business_scale_hint(db, c.id) == "소상공인/상업시설"


def test_hint_unknown_when_no_electric_bill(db, company):
    """신규 온보딩 직후 — 전기고지서가 아예 없다."""
    c, inst = company
    assert business_scale_hint(db, c.id) == "미확인"


def test_hint_unknown_when_class_unmapped(db, company):
    c, inst = company
    _add_bill(db, c, inst, 2026, 1, "unknown")
    assert business_scale_hint(db, c.id) == "미확인"


def test_hint_uses_most_recent_bill(db, company):
    """계약종별이 바뀌면(공장 → 사무실) 최근 고지서를 따라간다 — 저장형 라벨을 두지
    않는 설계의 이유가 이것이다(§5)."""
    c, inst = company
    _add_bill(db, c, inst, 2025, 6, "industrial")
    _add_bill(db, c, inst, 2026, 2, "commercial")
    assert business_scale_hint(db, c.id) == "소상공인/상업시설"


def test_hint_falls_back_to_older_bill_when_latest_unreadable(db, company):
    """최신 한 장이 파싱 실패(null)해도 직전 달에 읽은 값이 있으면 그걸 쓴다 —
    최신 문서 하나 때문에 판별을 포기하지 않는다."""
    c, inst = company
    _add_bill(db, c, inst, 2026, 1, "commercial")
    _add_bill(db, c, inst, 2026, 2, None)
    assert business_scale_hint(db, c.id) == "소상공인/상업시설"


def test_hint_ignores_other_document_types(db, company):
    """세금계산서·가스고지서엔 계약종별 개념이 없다 — 혹시 채워져 있어도 판별에 안 쓴다."""
    c, inst = company
    _add_bill(db, c, inst, 2026, 3, "industrial", document_type="gas_bill")
    _add_bill(db, c, inst, 2026, 1, "commercial")
    assert business_scale_hint(db, c.id) == "소상공인/상업시설"


# ── LLM 라우터 경로 (4순위) ────────────────────────────────────────────────


def test_llm_router_reuses_same_normalizer():
    """LLM 라우터도 셀 선택만 하고 값은 텍스트 레이어 경로와 같은 함수로 정규화한다
    (원칙1 — LLM이 값을 지어낼 경로가 없다)."""
    from db.document.document_llm_router import _resolve_fields

    cells = [
        {"id": 0, "text": "고객번호 0355-7712-90", "row_index": 0},
        {"id": 1, "text": "주택용전력", "row_index": 0},
        {"id": 2, "text": "197,316 원", "row_index": 1},
    ]
    result = {
        "document_type": "electric_bill",
        "contract_type_cell_id": "1",
        "customer_number_cell_id": "0",
        "amount_cell_id": "2",
        "confidence": 0.9,
        "evidence": "테스트",
    }
    parsed = _resolve_fields(result, cells, ["고객번호 0355-7712-90 주택용전력", "197,316 원"], "electric_bill")
    assert parsed["contract_type"] == "주택용전력"
    assert parsed["contract_type_class"] == "residential"
    # 셀에 라벨이 섞여 와도 숫자만 남는다
    assert parsed["customer_number"] == "0355-7712-90"


def test_llm_router_omits_fields_when_no_cell_chosen():
    """전기고지서가 아닌 문서는 이 두 필드가 null로 온다 — 키를 만들지 않는다."""
    from db.document.document_llm_router import _resolve_fields

    parsed = _resolve_fields(
        {"document_type": "tax_invoice", "confidence": 0.9, "evidence": "t",
         "contract_type_cell_id": None, "customer_number_cell_id": None},
        [{"id": 0, "text": "무관", "row_index": 0}],
        ["무관"],
        "tax_invoice",
    )
    assert "contract_type" not in parsed
    assert "customer_number" not in parsed
