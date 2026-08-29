#!/usr/bin/env python3
"""Hash the version-controlled inputs that define the AtlasRetail deployment."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable
from pathlib import Path

DIGEST_SCHEME = "git-tracked-v2"
SOURCE_PATHS = (
    ".github/atlas-target.json",
    "aws/glue/atlasretail_iceberg.py",
    "aws/lambda/control.py",
    "infra/atlas",
)


def tracked_source_files(repository: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", *SOURCE_PATHS],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    relative_paths = [Path(value.decode()) for value in completed.stdout.split(b"\0") if value]
    if not relative_paths:
        raise ValueError("no tracked AtlasRetail infrastructure source files were found")
    return sorted(relative_paths, key=lambda value: value.as_posix())


def tracked_content(repository: Path, relative: Path) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"HEAD:{relative.as_posix()}"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def digest_files(repository: Path, relative_paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    digest.update((DIGEST_SCHEME + "\0").encode())
    for relative in relative_paths:
        name = relative.as_posix().encode()
        content = tracked_content(repository, relative)
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def source_digest(repository: Path = Path(".")) -> str:
    root = repository.resolve()
    return digest_files(root, tracked_source_files(root))


if __name__ == "__main__":
    print(source_digest())
