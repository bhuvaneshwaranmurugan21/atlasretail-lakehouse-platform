from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atlasretail.simulator import run_failure_lab, write_evidence


class SimulatorTests(unittest.TestCase):
    def test_failure_lab(self) -> None:
        evidence = run_failure_lab()
        self.assertEqual("PASS", evidence["result"])
        self.assertFalse(evidence["production_claim"])
        self.assertGreaterEqual(evidence["metrics"]["checks_passed"], 12)

    def test_evidence_is_reproducible(self) -> None:
        first = run_failure_lab()
        second = run_failure_lab()
        self.assertEqual(first["evidence_digest"], second["evidence_digest"])

    def test_write_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence.json"
            evidence = write_evidence(output)
            self.assertTrue(output.exists())
            self.assertEqual("PASS", evidence["result"])


if __name__ == "__main__":
    unittest.main()
