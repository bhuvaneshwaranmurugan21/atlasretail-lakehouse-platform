from atlasretail.simulator import simulate


def test_simulation_is_deterministic_and_honest() -> None:
    first = simulate()
    second = simulate()
    assert first == second
    assert first["result"] == "PASS"
    assert first["metrics"]["checks_passed"] == first["metrics"]["checks_total"]
    assert first["production_claim"] is False

