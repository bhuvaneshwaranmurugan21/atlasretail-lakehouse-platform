from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-bounded-lab.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def parsed() -> dict[str, object]:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_dispatch_exposes_only_the_frozen_authorization_and_bounds() -> None:
    workflow = parsed()
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "budget_ceiling_usd",
        "confirm_destroy",
        "confirm_execute",
        "order_count",
    }
    assert inputs["order_count"]["default"] == "500"
    assert inputs["budget_ceiling_usd"]["default"] == "5"
    assert "1-5 USD" in inputs["budget_ceiling_usd"]["description"]
    assert "default" not in inputs["confirm_execute"]
    assert "default" not in inputs["confirm_destroy"]
    assert "EXECUTE_ATLASRETAIL_PART4" in inputs["confirm_execute"]["description"]
    assert "DESTROY" in inputs["confirm_destroy"]["description"]


def test_admission_has_no_oidc_or_aws_reachability() -> None:
    workflow = parsed()
    assert workflow["permissions"] == {"contents": "read"}
    admission = workflow["jobs"]["admission"]
    assert admission["permissions"] == {"contents": "read"}
    rendered = "\n".join(
        str(step.get("uses", "")) + "\n" + str(step.get("run", "")) for step in admission["steps"]
    )
    assert "configure-aws-credentials" not in rendered
    assert "aws " not in rendered
    assert "terraform" not in rendered
    assert "id-token" not in rendered
    assert "scripts/admit_part4_run.py" in rendered
    assert "scripts/validate_part4_admission.py" in rendered


def test_execute_and_teardown_revalidate_before_oidc() -> None:
    workflow = parsed()
    for job_name in ("execute", "teardown"):
        job = workflow["jobs"][job_name]
        assert job["permissions"] == {
            "actions": "read",
            "contents": "read",
            "id-token": "write",
        }
        steps = job["steps"]
        validation = next(
            index for index, step in enumerate(steps) if "Revalidate" in str(step.get("name", ""))
        )
        credentials = next(
            index
            for index, step in enumerate(steps)
            if "aws-actions/configure-aws-credentials@" in step.get("uses", "")
        )
        assert validation < credentials
        assert "validate_part4_admission.py" in steps[validation]["run"]


def test_attempt_bound_source_handoff_is_single_producer_and_reused() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count("atlasretail generate-sources") == 1
    artifact = "atlasretail-part4-admission-${{ github.run_id }}-${{ github.run_attempt }}"
    assert workflow.count(artifact) == 3
    assert '--run-attempt "${GITHUB_RUN_ATTEMPT}"' in workflow
    assert "--managed-manifest-output" in workflow
    assert ".artifacts/aws" not in workflow
    admission = workflow.index("Materialize the exact pre-AWS source tree")
    apply = workflow.index("Apply only the validated saved plan")
    upload = workflow.index("Upload only the admitted immutable inputs")
    unchanged = workflow.index("Prove the admitted source tree remained unchanged after upload")
    execute = workflow.index("Execute success and replay proofs")
    assert admission < apply < upload < unchanged < execute


def test_teardown_routes_only_admitted_runs_and_releases_only_clean_lease() -> None:
    workflow = parsed()
    assert set(workflow["jobs"]) == {"admission", "execute", "teardown"}
    assert workflow["jobs"]["execute"]["needs"] == "admission"
    teardown = workflow["jobs"]["teardown"]
    assert teardown["needs"] == ["admission", "execute"]
    assert teardown["if"] == "${{ always() && needs.admission.result == 'success' }}"
    steps = teardown["steps"]
    verify_destroy = next(step for step in steps if step.get("id") == "verify_teardown")
    verify_no_deployment = next(step for step in steps if step.get("id") == "verify_no_deployment")
    release = next(step for step in steps if "Release only" in str(step.get("name", "")))
    assert "verify_teardown.py" in verify_destroy["run"]
    assert "verify_preflight.py" in verify_no_deployment["run"]
    assert 'arguments+=("${GITHUB_REPOSITORY}/${GITHUB_RUN_ID}")' in verify_no_deployment["run"]
    assert "steps.verify_teardown.outcome == 'success'" in release["if"]
    assert "steps.verify_no_deployment.outcome == 'success'" in release["if"]
    assert release["run"] == "bash scripts/release_lock.sh"


def test_admission_receipt_is_copied_into_execution_and_teardown_evidence() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count('"${EVIDENCE_DIR}/admission-receipt.json"') == 2
    assert "Persist the immutable admitted source handoff" in workflow
    assert "if-no-files-found: error" in workflow


def test_ci_reproduces_compact_local_stage3_evidence() -> None:
    workflow = CI.read_text(encoding="utf-8")
    assert workflow.count("validate_part4_admission_controls.py") == 2
    assert "part4-stage3-admission-controls-${{ github.run_id }}" in workflow
    assert "part4-stage3-admission-controls.json" in workflow
