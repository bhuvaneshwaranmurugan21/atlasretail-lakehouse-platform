"""Keep every workflow caller aligned with the strict lease-aware preflight CLI."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

CONTROLLED_OWNER = '"${GITHUB_REPOSITORY}/${GITHUB_RUN_ID}"'
BOUNDED_OWNER = '"${GITHUB_REPOSITORY}/${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}"'


def normalized_calls(workflow_name: str) -> list[str]:
    workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
    blocks = workflow.split("python scripts/verify_preflight.py \\")[1:]
    return ["\n".join(block.lstrip("\n").splitlines()[:3]) for block in blocks]


def test_absence_proofs_bind_the_canonical_lease_table() -> None:
    foundation_calls = normalized_calls("foundation.yml")
    plan_calls = normalized_calls("aws-plan-only.yml")

    assert len(foundation_calls) == 1
    assert len(plan_calls) == 2
    assert all('"${ACCOUNT_LEASE_TABLE}"' in call for call in foundation_calls + plan_calls)
    assert all("GITHUB_REPOSITORY" not in call for call in foundation_calls + plan_calls)


def test_post_acquisition_proofs_require_the_exact_run_owner() -> None:
    controlled_calls = normalized_calls("aws-controlled-deployment.yml")
    bounded_calls = normalized_calls("aws-bounded-lab.yml")

    assert len(controlled_calls) == 1
    assert len(bounded_calls) == 1
    assert CONTROLLED_OWNER in controlled_calls[0]
    assert BOUNDED_OWNER in bounded_calls[0]
