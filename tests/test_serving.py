from __future__ import annotations

import pytest

from atlasretail.serving import ServingResolution, six_table_count_query


def resolution() -> ServingResolution:
    return ServingResolution.from_control_response(
        {
            "status": "RESOLVED",
            "generation_id": "g-proof-batch-012345abcdef",
            "pointer_version": 3,
            "validation_digest": "a" * 64,
        }
    )


def test_serving_query_pins_all_six_tables_to_one_generation() -> None:
    query = six_table_count_query("atlas_retail", resolution())

    assert query.count("generation_id='g-proof-batch-012345abcdef'") == 6
    assert "atlas_retail.orders" in query
    assert "atlas_retail.products" in query


def test_invalid_pointer_and_database_are_rejected() -> None:
    with pytest.raises(ValueError, match="published generation"):
        ServingResolution.from_control_response({"status": "FAILED"})
    with pytest.raises(ValueError, match="database"):
        six_table_count_query("atlas-retail; DROP TABLE", resolution())
