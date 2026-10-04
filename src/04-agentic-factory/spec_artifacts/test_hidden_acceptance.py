import copy

import pytest

try:
    from laya_computer.preflight import analyze_preflight_plan
except ImportError:
    from reference_implementation import analyze_preflight_plan


def step(id, action="verify", next_step=None, on_failure=None, **extra):
    data = {
        "id": id,
        "instruction": f"do {id}",
        "action": action,
        "success": [{"kind": "exists", "role": "button"}],
        "next_step": next_step,
        "on_failure": on_failure,
    }
    data.update(extra)
    return data


def plan(*steps, **extra):
    return {"version": 1, "goal": "goal", "app_bundle_id": "com.example.app", "steps": list(steps), **extra}


def n_unreachable(r):
    return sum(1 for i in r["issues"] if i["code"] == "UNREACHABLE_STEP")


def test_on_failure_does_not_extend_reachability_from_reachable_step():
    r = analyze_preflight_plan(
        plan(step("a", next_step="b", on_failure="r1"), step("b", on_failure="r2"), step("r1"), step("r2"))
    )
    assert n_unreachable(r) == 2
    assert r["status"] == "invalid"


def test_on_failure_to_already_reachable_step_is_fine():
    r = analyze_preflight_plan(plan(step("a", next_step="b", on_failure="b"), step("b")))
    assert r["status"] == "valid"


def test_self_loop_terminates():
    r = analyze_preflight_plan(plan(step("a", next_step="a")))
    assert r["status"] == "valid"


def test_cycle_leaves_other_steps_unreachable():
    r = analyze_preflight_plan(plan(step("a", next_step="b"), step("b", next_step="a"), step("c")))
    assert n_unreachable(r) == 1


def test_start_step_in_middle_makes_earlier_steps_unreachable():
    r = analyze_preflight_plan(plan(step("a", next_step="b"), step("b", next_step="c"), step("c"), start_step="b"))
    assert n_unreachable(r) == 1


def test_unreachable_risky_step_still_reports_risk_but_repair_wins():
    r = analyze_preflight_plan(plan(step("a"), step("b", "set_value", target={"role": "textbox"}, text="x")))
    assert n_unreachable(r) == 1
    assert "writes_user_data" in r["risk_factors"]
    assert (r["status"], r["recommendation"]) == ("invalid", "repair")


def test_multiple_risks_sorted_and_deduplicated():
    r = analyze_preflight_plan(
        plan(
            step("a", "press_key", key="cmd+q", next_step="b", allow_partial_observation=True),
            step("b", "set_value", target={"role": "textbox"}, text="x", next_step="c"),
            step("c", "set_value", target={"role": "textbox"}, text="y"),
        )
    )
    assert r["risk_factors"] == ["destructive_keys", "partial_observation", "writes_user_data"]
    assert r["recommendation"] == "human_review"


@pytest.mark.parametrize("key", ["Terminal", "COMMAND+T", "cmd+w", "ctrl+alt+delete"])
def test_destructive_key_variants(key):
    r = analyze_preflight_plan(plan(step("a", "press_key", key=key)))
    assert "destructive_keys" in r["risk_factors"]


@pytest.mark.parametrize("key", ["tab", "escape", "return"])
def test_benign_keys_not_destructive(key):
    r = analyze_preflight_plan(plan(step("a", "press_key", key=key)))
    assert r["risk_factors"] == []


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        [],
        "plan",
        plan(step("a"), step("a")),
        plan(step("a"), start_step="zzz"),
        plan(step("a", on_failure="zzz")),
        plan(step("a", "wait", duration_seconds=11)),
        plan(step("a", "click")),
        plan(step("a"), bogus=1),
        plan(step("a", "click", target={"role": "button", "index": 1}, allow_partial_observation=True)),
    ],
)
def test_invalid_inputs_never_raise_and_demand_repair(bad):
    r = analyze_preflight_plan(bad)
    assert (r["status"], r["recommendation"]) == ("invalid", "repair")
    assert r["issues"] and all(i["severity"] == "error" and i["code"] for i in r["issues"])
    assert r["schema_version"] == 1
    assert r["checks_run"] == ["plan_schema", "references", "reachability", "risk_rules"]
    assert r["checks_not_run"] == ["live_accessibility", "runtime_effects"]


def test_issue_shape_and_severity_values():
    r = analyze_preflight_plan(plan(step("a", allow_partial_observation=True), step("b")))
    for issue in r["issues"]:
        assert isinstance(issue["code"], str)
        assert issue["severity"] in {"error", "review"}


def test_review_only_issues_do_not_invalidate():
    r = analyze_preflight_plan(plan(step("a", allow_partial_observation=True)))
    assert all(i["severity"] == "review" for i in r["issues"])
    assert r["status"] == "unverified"


def test_input_not_mutated_and_deterministic():
    data = plan(step("a", next_step="b", on_failure="c"), step("b"), step("c"))
    snapshot = copy.deepcopy(data)
    first = analyze_preflight_plan(data)
    second = analyze_preflight_plan(data)
    assert data == snapshot
    assert first == second


def test_long_chain_of_100_steps():
    steps = [step(f"s{i}", next_step=f"s{i + 1}" if i < 99 else None) for i in range(100)]
    assert analyze_preflight_plan(plan(*steps))["status"] == "valid"


def test_long_cycle_of_100_steps():
    steps = [step(f"s{i}", next_step=f"s{(i + 1) % 100}") for i in range(100)]
    assert analyze_preflight_plan(plan(*steps))["status"] == "valid"