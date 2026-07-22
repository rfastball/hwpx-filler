from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_test_portfolio.py"
SPEC = importlib.util.spec_from_file_location("audit_test_portfolio", SCRIPT)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def _row(nodeid: str = "tests/test_x.py::test_one") -> dict[str, str]:
    return {
        "nodeid": nodeid,
        "source": "tests/test_x.py",
        "layer": "unit",
        "risk_surfaces": "application-workflows",
        "platform": "cross-platform",
        "execution_unit_id": nodeid,
        "contract_claims": "one",
        "claim_count": "1",
        "fixture_kind": "synthetic",
        "verification_method": "behavioral",
        "owner_contract": "one",
        "duration_s": "0.001",
        "covered_modules": "src/hwpxfiller/example.py",
        "correlation_group": "",
        "duplicate_of": "",
        "disposition": "keep-supporting",
        "evidence": "tests/test_x.py",
    }


def test_validate_rejects_duplicate_nodeids() -> None:
    row = _row()
    with pytest.raises(audit.AuditError, match="duplicate nodeids"):
        audit.validate_rows([row, dict(row)])


def test_validate_rejects_invalid_enum() -> None:
    row = _row()
    row["layer"] = "regression"
    with pytest.raises(audit.AuditError, match="invalid layer"):
        audit.validate_rows([row])


def test_validate_detects_stale_or_missing_junit_case() -> None:
    cases = [audit.TestCase("tests/test_x.py::test_other", "tests/test_x.py", 0.1, "passed")]
    with pytest.raises(audit.AuditError, match="inventory/JUnit mismatch"):
        audit.validate_rows([_row()], cases)


def test_render_is_deterministic_and_counts_execution_units() -> None:
    first = _row("tests/test_x.py::test_one")
    second = _row("tests/test_x.py::test_two")
    second["execution_unit_id"] = first["execution_unit_id"]
    rendered_a = audit.render_matrix([first, second], {"baseline_sha": "abc123"})
    rendered_b = audit.render_matrix([first, second], {"baseline_sha": "abc123"})
    assert rendered_a == rendered_b
    assert "수집 사례: **2**" in rendered_a
    assert "독립 실행 단위: **1**" in rendered_a


def test_ast_metadata_accepts_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "test_bom.py"
    source.write_text("def test_bom():\n    assert True\n", encoding="utf-8-sig")

    metadata = audit._ast_test_metadata(source)

    assert metadata["test_bom"][0] == 1
