"""Create a canonical manifest that deliberately claims stale evidence for a new S3 version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlasretail.canonical import digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    value = json.loads(arguments.input.read_text(encoding="utf-8"))
    value.pop("identity_digest", None)
    objects = value["tables"][arguments.table]["objects"]
    if len(objects) != 1:
        raise ValueError("tamper proof expects exactly one object")
    objects[0]["version_id"] = arguments.version_id
    value["identity_digest"] = digest(value)
    arguments.output.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
