"""Build, validate, archive, and verify the Part 4 Stage 8 release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .release_integrity import (
    RELEASE_RECEIPT,
    RELEASE_TAG,
    ReleaseIntegrityError,
    build_post_release_verification,
    build_release_archive,
    build_release_receipt,
    validate_release_receipt,
    write_bytes,
    write_json,
)

ROOT = Path(__file__).resolve().parents[3]


def load_object(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseIntegrityError(f"{path}: expected a JSON object")
    return value


def command_build_receipt(arguments: argparse.Namespace) -> None:
    receipt = build_release_receipt(ROOT, arguments.controls_commit)
    validate_release_receipt(receipt, ROOT)
    write_json(arguments.output, receipt)


def command_verify_receipt(arguments: argparse.Namespace) -> None:
    validate_release_receipt(load_object(arguments.receipt), ROOT)


def command_build_archive(arguments: argparse.Namespace) -> None:
    write_bytes(arguments.output, build_release_archive(ROOT, arguments.commit))


def command_verify_tag(arguments: argparse.Namespace) -> None:
    verification = build_post_release_verification(
        ROOT,
        arguments.tag,
        arguments.receipt,
        arguments.archive,
    )
    write_json(arguments.output, verification)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)

    build_receipt = commands.add_parser("build-receipt")
    build_receipt.add_argument("--controls-commit", required=True)
    build_receipt.add_argument("--output", type=Path, default=ROOT / RELEASE_RECEIPT)
    build_receipt.set_defaults(handler=command_build_receipt)

    verify_receipt = commands.add_parser("verify-receipt")
    verify_receipt.add_argument("--receipt", type=Path, default=ROOT / RELEASE_RECEIPT)
    verify_receipt.set_defaults(handler=command_verify_receipt)

    build_archive = commands.add_parser("build-archive")
    build_archive.add_argument("--commit", required=True)
    build_archive.add_argument("--output", type=Path, required=True)
    build_archive.set_defaults(handler=command_build_archive)

    verify_tag = commands.add_parser("verify-tag")
    verify_tag.add_argument("--tag", default=RELEASE_TAG)
    verify_tag.add_argument("--receipt", type=Path, default=RELEASE_RECEIPT)
    verify_tag.add_argument("--archive", type=Path, required=True)
    verify_tag.add_argument("--output", type=Path, required=True)
    verify_tag.set_defaults(handler=command_verify_tag)
    return value


def main() -> int:
    arguments = parser().parse_args()
    try:
        arguments.handler(arguments)
    except (
        ReleaseIntegrityError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        print(f"Part 4 Stage 8 release rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
