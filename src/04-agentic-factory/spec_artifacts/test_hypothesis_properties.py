from hypothesis import HealthCheck, given, settings, strategies as st

from reference_implementation import analyze_preflight_plan

SAFE_KEYS = ["enter", "tab", "escape"]
DANGEROUS_KEYS = ["cmd+q", "alt+f4", "command+space", "terminal"]

CFG = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def plans(draw):
    n = draw(st.integers(1, 8))
    ids = [f"s{i}" for i in range(n)]
    ref = st.one_of(st.none(), st.sampled_from(ids))
    steps = []
    for sid in ids:
        kind = draw(st.sampled_from(["verify", "set_value", "press_key"]))
        data = {
            "id": sid,
            "instruction": f"do {sid}",
            "action": kind,
            "success": [{"kind": "exists", "role": "button"}],
            "next_step": draw(ref),
            "on_failure": draw(ref),
            "allow_partial_observation": draw(st.booleans()),
        }
        if kind == "set_value":
            data["target"] = {"role": "textbox"}
            data["text"] = "x"
        elif kind == "press_key":
            data["key"] = draw(st.sampled_from(SAFE_KEYS + DANGEROUS_KEYS))
        steps.append(data)
    return {
        "version": 1,
        "goal": "goal",
        "app_bundle_id": "com.example.app",
        "steps": steps,
        "start_step": draw(ref),
    }


def oracle_reachable(data):
    by_id = {s["id"]: s for s in data["steps"]}
    cur = data["start_step"] or data["steps"][0]["id"]
    seen = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        cur = by_id[cur]["next_step"]
    return seen


def oracle_risks(data):
    risks = set()
    for s in data["steps"]:
        if s["action"] == "set_value":
            risks.add("writes_user_data")
        if s.get("key") in DANGEROUS_KEYS:
            risks.add("destructive_keys")
        if s["allow_partial_observation"]:
            risks.add("partial_observation")
    return risks


def n_unreachable(r):
    return sum(1 for i in r["issues"] if i["code"] == "UNREACHABLE_STEP")


@CFG
@given(plans())
def test_unreachable_count_matches_oracle(data):
    r = analyze_preflight_plan(data)
    expected = len(data["steps"]) - len(oracle_reachable(data))
    assert n_unreachable(r) == expected


@CFG
@given(plans())
def test_status_and_recommendation_mapping(data):
    r = analyze_preflight_plan(data)
    unreachable = n_unreachable(r) > 0
    risks = oracle_risks(data)
    if unreachable:
        assert (r["status"], r["recommendation"]) == ("invalid", "repair")
    elif risks:
        assert (r["status"], r["recommendation"]) == ("unverified", "human_review")
    else:
        assert (r["status"], r["recommendation"]) == ("valid", "proceed_to_inspection")


@CFG
@given(plans())
def test_risk_factors_match_oracle_sorted_unique(data):
    r = analyze_preflight_plan(data)
    assert r["risk_factors"] == sorted(oracle_risks(data))
    assert len(r["risk_factors"]) == len(set(r["risk_factors"]))


@CFG
@given(plans(), st.data())
def test_on_failure_edges_never_change_reachability(data, draw):
    ids = [s["id"] for s in data["steps"]]
    baseline = n_unreachable(analyze_preflight_plan(data))
    for s in data["steps"]:
        s["on_failure"] = draw.draw(st.one_of(st.none(), st.sampled_from(ids)))
    assert n_unreachable(analyze_preflight_plan(data)) == baseline


@CFG
@given(plans())
def test_contract_invariants(data):
    r = analyze_preflight_plan(data)
    assert r["schema_version"] == 1
    assert r["checks_run"] == ["plan_schema", "references", "reachability", "risk_rules"]
    assert r["checks_not_run"] == ["live_accessibility", "runtime_effects"]
    assert all(i["severity"] in {"error", "review"} and i["code"] for i in r["issues"])
    assert (r["status"] == "invalid") == any(i["severity"] == "error" for i in r["issues"])


junk = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=True), st.text(max_size=10)),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.sampled_from(["version", "goal", "steps", "app_bundle_id", "start_step", "id"]), children, max_size=4),
    ),
    max_leaves=10,
)


@CFG
@given(junk)
def test_arbitrary_input_never_raises(data):
    r = analyze_preflight_plan(data)
    assert r["schema_version"] == 1
    assert r["status"] in {"valid", "invalid", "unverified"}
    assert r["recommendation"] in {"proceed_to_inspection", "repair", "human_review"}
    if r["status"] == "invalid":
        assert r["recommendation"] == "repair"