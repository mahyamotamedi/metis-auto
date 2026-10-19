"""The generated contract field reference matches the code (Stage 4)."""

from contracts_docgen import OUTPUT, render


def test_contract_reference_is_current():
    assert OUTPUT.exists(), "run: python tests/architecture/contracts_docgen.py"
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "docs/architecture/contracts_reference.md is stale; "
        "run: python tests/architecture/contracts_docgen.py"
    )
