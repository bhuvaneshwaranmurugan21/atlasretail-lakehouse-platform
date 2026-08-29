from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIGEST = load("terraform_source_digest")
AUTHORITY = load("build_teardown_authority")
VALIDATOR = load("validate_teardown_authority")


def repository(tmp_path: Path) -> Path:
    paths = {
        ".github/atlas-target.json": "{}\n",
        "aws/glue/atlasretail_iceberg.py": "print('glue')\n",
        "aws/lambda/control.py": "def handler(event, context): return event\n",
        "infra/atlas/main.tf": "terraform {}\n",
        "infra/atlas/.terraform.lock.hcl": "provider-lock\n",
    }
    for name, content in paths.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    return tmp_path


def environment() -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": "owner/repository",
        "GITHUB_RUN_ID": "12345",
        "GITHUB_SHA": "a" * 40,
        "AWS_ACCOUNT_ID": "857229544428",
        "AWS_REGION": "ap-southeast-2",
        "TERRAFORM_STATE_BUCKET": "state-bucket",
        "TERRAFORM_STATE_KEY": "atlasretail/main.tfstate",
    }


def test_tracked_digest_is_stable_across_terraform_runtime_mutation(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    before = DIGEST.source_digest(repo)

    (repo / "infra/atlas/.terraform.lock.hcl").write_text("runtime mutation\n", encoding="utf-8")
    runtime = repo / "infra/atlas/.terraform/provider"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("runtime", encoding="utf-8")

    assert DIGEST.source_digest(repo) == before

    subprocess.run(["git", "add", "infra/atlas/.terraform.lock.hcl"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change source"], cwd=repo, check=True)
    assert DIGEST.source_digest(repo) != before


def test_current_authority_validates_exact_identity_and_source(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    env = environment()
    manifest = AUTHORITY.authority(env, repo)

    proof = VALIDATOR.validate(
        manifest,
        repository=env["GITHUB_REPOSITORY"],
        run_id=env["GITHUB_RUN_ID"],
        source_commit=env["GITHUB_SHA"],
        account=env["AWS_ACCOUNT_ID"],
        region=env["AWS_REGION"],
        backend_bucket=env["TERRAFORM_STATE_BUCKET"],
        backend_key=env["TERRAFORM_STATE_KEY"],
        repository_root=repo,
    )

    assert proof["result"] == "PASS"
    assert proof["claim"] == "IMMUTABLE_TEARDOWN_AUTHORITY_VERIFIED"
    assert proof["infrastructure_digest_scheme"] == "git-tracked-v2"

    manifest["backend_key"] = "wrong.tfstate"
    rejected = VALIDATOR.validate(
        manifest,
        repository=env["GITHUB_REPOSITORY"],
        run_id=env["GITHUB_RUN_ID"],
        source_commit=env["GITHUB_SHA"],
        account=env["AWS_ACCOUNT_ID"],
        region=env["AWS_REGION"],
        backend_bucket=env["TERRAFORM_STATE_BUCKET"],
        backend_key=env["TERRAFORM_STATE_KEY"],
        repository_root=repo,
    )
    assert rejected["result"] == "FAIL"
    assert "backend_key mismatch" in rejected["errors"]


def test_legacy_authority_requires_explicit_post_init_digest(tmp_path: Path) -> None:
    terraform_root = tmp_path / "infra/atlas"
    terraform_root.mkdir(parents=True)
    (terraform_root / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    (terraform_root / ".terraform.lock.hcl").write_text("post-init lock\n", encoding="utf-8")
    runtime = terraform_root / ".terraform/providers/runtime"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("ignored", encoding="utf-8")
    env = environment()
    manifest = {
        "project": "AtlasRetail",
        "operation": "controlled-deployment",
        "repository": env["GITHUB_REPOSITORY"],
        "run_id": env["GITHUB_RUN_ID"],
        "source_commit": env["GITHUB_SHA"],
        "account": env["AWS_ACCOUNT_ID"],
        "region": env["AWS_REGION"],
        "backend_bucket": env["TERRAFORM_STATE_BUCKET"],
        "backend_key": env["TERRAFORM_STATE_KEY"],
        "infrastructure_digest": VALIDATOR.legacy_post_init_digest(terraform_root),
    }

    proof = VALIDATOR.validate(
        manifest,
        repository=env["GITHUB_REPOSITORY"],
        run_id=env["GITHUB_RUN_ID"],
        source_commit=env["GITHUB_SHA"],
        account=env["AWS_ACCOUNT_ID"],
        region=env["AWS_REGION"],
        backend_bucket=env["TERRAFORM_STATE_BUCKET"],
        backend_key=env["TERRAFORM_STATE_KEY"],
        repository_root=tmp_path,
        legacy_terraform_root=terraform_root,
    )

    assert proof["result"] == "PASS"
    assert proof["infrastructure_digest_scheme"] == "legacy-post-init-v1"
