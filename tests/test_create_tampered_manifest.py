from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from atlasretail.generator import generate_batch
from atlasretail.manifest import ObjectProof, bind_objects, build_manifest, manifest_from_dict

SCRIPT = Path(__file__).parents[1] / "scripts" / "create_tampered_manifest.py"


def test_tampered_manifest_remains_canonical_but_claims_stale_evidence(tmp_path: Path) -> None:
    batch = generate_batch(order_count=2)
    manifest = build_manifest(
        batch,
        batch_id="tamper-1",
        produced_at=1,
        as_of_knowledge_time=1,
    )
    objects = {
        name: (ObjectProof("bucket", f"{name}.gz", "old-version", 10, "a" * 64, "old-etag"),)
        for name in manifest.tables
    }
    source = tmp_path / "managed.json"
    source.write_text(json.dumps(bind_objects(manifest, objects).to_dict()), encoding="utf-8")
    output = tmp_path / "tampered.json"

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source),
            "--table",
            "orders",
            "--version-id",
            "new-version",
            "--output",
            str(output),
        ],
        check=True,
    )

    tampered = manifest_from_dict(json.loads(output.read_text(encoding="utf-8")))
    assert tampered.tables["orders"].objects[0].version_id == "new-version"
    assert tampered.tables["orders"].objects[0].etag == "old-etag"
