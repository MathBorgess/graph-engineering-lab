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


def codes(result, code):
    return [i for i in result["issues"] if i["code"] == code]


def test_contract_structure():
    r = analyze_preflight_plan(plan(step("a")))
    assert r["schema_version"] == 1
    assert r["status"] in {"valid", "invalid", "unverified"}
    assert r["recommendation"] in {"proceed_to_inspection", "repair", "human_review"}
    assert isinstance(r["issues"], list)
    assert r["risk_factors"] == sorted(r["risk_factors"])
    assert r["checks_run"] == ["plan_schema", "references", "reachability", "risk_rules"]
    assert r["checks_not_run"] == ["live_accessibility", "runtime_effects"]


def test_clean_linear_plan_is_valid():
    r = analyze_preflight_plan(plan(step("a", next_step="b"), step("b", next_step="c"), step("c")))
    assert (r["status"], r["recommendation"]) == ("valid", "proceed_to_inspection")
    assert r["issues"] == []
    assert r["risk_factors"] == []


def test_schema_violation_is_invalid():
    r = analyze_preflight_plan({"version": 1})
    assert (r["status"], r["recommendation"]) == ("invalid", "repair")
    assert any(i["severity"] == "error" for i in r["issues"])


def test_unknown_reference_is_invalid():
    r = analyze_preflight_plan(plan(step("a", next_step="ghost")))
    assert (r["status"], r["recommendation"]) == ("invalid", "repair")


def test_step_only_reachable_via_on_failure_is_unreachable():
    r = analyze_preflight_plan(plan(step("a", on_failure="rescue"), step("rescue")))
    assert len(codes(r, "UNREACHABLE_STEP")) == 1
    assert codes(r, "UNREACHABLE_STEP")[0]["severity"] == "error"
    assert (r["status"], r["recommendation"]) == ("invalid", "repair")


def test_cycle_terminates_and_is_valid():
    r = analyze_preflight_plan(plan(step("a", next_step="b"), step("b", next_step="a")))
    assert r["status"] == "valid"


def test_start_step_is_honoured():
    r = analyze_preflight_plan(plan(step("a"), step("b"), start_step="b"))
    assert len(codes(r, "UNREACHABLE_STEP")) == 1
    assert r["status"] == "invalid"


def test_set_value_writes_user_data():
    r = analyze_preflight_plan(plan(step("a", "set_value", target={"role": "textbox"}, text="hi")))
    assert r["risk_factors"] == ["writes_user_data"]
    assert r["recommendation"] == "human_review"
    assert r["status"] == "unverified"


@pytest.mark.parametrize("key", ["cmd+q", "alt+f4", "Command+Space", "terminal"])
def test_destructive_keys(key):
    r = analyze_preflight_plan(plan(step("a", "press_key", key=key)))
    assert r["risk_factors"] == ["destructive_keys"]
    assert r["recommendation"] == "human_review"


def test_safe_key_has_no_risk():
    r = analyze_preflight_plan(plan(step("a", "press_key", key="enter")))
    assert r["risk_factors"] == []
    assert r["recommendation"] == "proceed_to_inspection"


def test_partial_observation_risk():
    r = analyze_preflight_plan(plan(step("a", allow_partial_observation=True)))
    assert r["risk_factors"] == ["partial_observation"]
    assert r["recommendation"] == "human_review"