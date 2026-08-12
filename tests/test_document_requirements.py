"""연료 체크 → 업로드 문서 요구 상태 판정 골든케이스 (db/document_requirements.py)."""
from db.document_requirements import required_documents


def test_electricity_only_makes_tax_invoice_optional():
    """"전기만" 체크 — 전기고지서만 필수, 세금계산서는 선택(유인 전환 문구용)."""
    result = required_documents({
        "diesel": False, "gasoline": False, "city_gas": False,
        "lpg": "no", "electricity": True,
    })
    assert result == {
        "tax_invoice": "optional",
        "electric_bill": "required",
        "gas_bill": "not_applicable",
    }


def test_diesel_and_electricity_requires_tax_invoice():
    """경유+전기 — 세금계산서·전기고지서 둘 다 필수, 도시가스고지서는 해당없음."""
    result = required_documents({
        "diesel": True, "gasoline": False, "city_gas": False,
        "lpg": "no", "electricity": True,
    })
    assert result == {
        "tax_invoice": "required",
        "electric_bill": "required",
        "gas_bill": "not_applicable",
    }


def test_city_gas_and_electricity_only_does_not_require_tax_invoice():
    """도시가스+전기만 — Scope1 연료가 없으므로 세금계산서는 선택, 도시가스고지서만 필수."""
    result = required_documents({
        "diesel": False, "gasoline": False, "city_gas": True,
        "lpg": "no", "electricity": True,
    })
    assert result == {
        "tax_invoice": "optional",
        "electric_bill": "required",
        "gas_bill": "required",
    }


def test_lpg_unsure_requires_tax_invoice_for_ai_screening():
    """LPG "잘 모르겠어요" — 가스류 전표를 받아 AI가 판별해야 하므로 세금계산서 필수."""
    result = required_documents({
        "diesel": False, "gasoline": False, "city_gas": False,
        "lpg": "unsure", "electricity": True,
    })
    assert result["tax_invoice"] == "required"


def test_lpg_no_does_not_force_tax_invoice_alone():
    """LPG "아니오"만으로는(다른 Scope1 연료 없으면) 세금계산서를 강제하지 않는다."""
    result = required_documents({
        "diesel": False, "gasoline": False, "city_gas": False,
        "lpg": "no", "electricity": True,
    })
    assert result["tax_invoice"] == "optional"


def test_all_fuels_selected_requires_every_document():
    result = required_documents({
        "diesel": True, "gasoline": True, "city_gas": True,
        "lpg": "yes", "electricity": True,
    })
    assert result == {
        "tax_invoice": "required",
        "electric_bill": "required",
        "gas_bill": "required",
    }
