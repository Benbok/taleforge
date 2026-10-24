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
