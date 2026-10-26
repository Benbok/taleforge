from tools.eval_universal_balance import evaluate_balance, render_report


def test_preliminary_report_repeats_with_same_seed_and_flags_extremes():
    first = evaluate_balance(seed=47)
    assert first == evaluate_balance(seed=47)
    assert first["levels"] == [1, 10, 100]
    assert {row["build"] for row in first["rows"]} == {"specialist", "even"}
    assert first["flags"]["automatic_checks"]
    assert first["flags"]["one_shots"]
    assert first["resistance_binding_percent"] == {"14": "90", "24": "65", "33": "45"}
    assert "provisional" in render_report(first).lower()
    assert "not a universal balance proof" in render_report(first).lower()


def test_specialist_report_uses_exact_documented_damage_and_growth():
    result = evaluate_balance(seed=47)
    rows = {(row["level"], row["build"]): row for row in result["rows"]}
    assert rows[1, "specialist"]["mean_damage"] == "11/2"
    assert rows[10, "specialist"]["mean_damage"] == "65/2"
    assert rows[100, "specialist"]["mean_damage"] == "605/2"
    assert rows[10, "specialist"]["wis"] == "33"
    assert rows[100, "specialist"]["hp"] == "618"
    assert rows[10, "even"]["growth_points"] == "18"
    assert rows[100, "even"]["growth_points"] == "198"


def test_growth_balance_uses_actual_budgets_and_repeats():
    from tools.eval_universal_balance import simulate_build

    for level in (1, 10, 20, 100, 1000):
        for build in ("str", "dex", "con", "wis", "even"):
            first = simulate_build(level, build, 47)
            assert first == simulate_build(level, build, 47)
            assert first["allocated_points"] == str(2 * (level - 1))
            assert first["budget_verified"]
            assert len(first["energies"]) == 5 and len(first["opponents"]) == 3
            assert first["weapon_when_empty"]["energy_cost"] == "0"


def test_growth_report_checks_both_rarity_encodings_and_flags_burst_damage():
    from tools.eval_universal_balance import simulate_build

    row = simulate_build(10, "str", 47)
    assert {item["variant"] for item in row["rarity"]} == {"flat", "multiplier"}
    assert any(
        item["status"] == "epic" and item["variant"] == "multiplier" and item["max_one_shot_chance"] != "0"
        for item in row["rarity"]
    )
