from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_no_change.py"
SPEC = importlib.util.spec_from_file_location("verify_no_change", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def baseline() -> dict[str, object]:
    return {
        "result": "PASS",
        "terraform_state_resources": [],
        "allowed_pending_deletion_kms_keys": ["arn:historical"],
        "unexpected_resources": [],
    }


def test_identical_clean_baselines_pass() -> None:
    result = MODULE.verify(baseline(), baseline())

    assert result["result"] == "PASS"
    assert result["persistent_inventory_unchanged"] is True


def test_new_resource_fails() -> None:
    after = baseline()
    after["unexpected_resources"] = ["arn:aws:s3:::unexpected"]

    assert MODULE.verify(baseline(), after)["result"] == "FAIL"
