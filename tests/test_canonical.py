from __future__ import annotations

import unittest

from atlasretail.canonical import digest, digest_records


class CanonicalDigestTests(unittest.TestCase):
    def test_streamed_records_match_canonical_list_digest(self) -> None:
        records = [{"z": 1, "a": None}, {"currency": "₹", "amount": 42}]
        count, actual = digest_records(iter(records))
        self.assertEqual(count, len(records))
        self.assertEqual(actual, digest(records))

    def test_empty_record_stream_matches_empty_array(self) -> None:
        self.assertEqual(digest_records(iter(())), (0, digest([])))

    def test_record_order_remains_part_of_table_identity(self) -> None:
        first = [{"id": "a"}, {"id": "b"}]
        second = list(reversed(first))
        self.assertNotEqual(digest_records(iter(first)), digest_records(iter(second)))
