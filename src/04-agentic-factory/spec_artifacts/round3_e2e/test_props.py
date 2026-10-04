import pytest
from hypothesis import given, strategies as st

from reference_impl import Plan, Step, get_terminal_steps


@st.composite
def plans(draw):
    n = draw(st.integers(min_value=1, max_value=8))
    ids = draw(
        st.lists(
            st.text(alphabet='abcdefgh', min_size=1, max_size=3),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )
    opt_id = st.one_of(st.none(), st.sampled_from(ids))
    steps = {}
    for sid in ids:
        steps[sid] = Step(sid, draw(opt_id), draw(opt_id))
    first = draw(st.sampled_from(ids))
    return Plan(first_step_id=first, steps=steps)


def reachable_closure(plan):
    reach = {plan.first_step_id}
    changed = True
    while changed:
        changed = False
        for sid in list(reach):
            step = plan.steps[sid]
            for nxt in (step.next_step, step.on_failure):
                if nxt is not None and nxt not in reach:
                    reach.add(nxt)
                    changed = True
    return reach


@given(plans())
def test_result_is_exactly_sorted_reachable_terminals_or_error(plan):
    expected = sorted(
        sid for sid in reachable_closure(plan) if plan.steps[sid].next_step is None
    )
    if not expected:
        with pytest.raises(ValueError, match='Plan has no reachable terminal step'):
            get_terminal_steps(plan)
        return
    result = get_terminal_steps(plan)
    assert result == expected
    assert result == sorted(result)
    assert len(result) == len(set(result))


@given(plans(), st.integers(min_value=1, max_value=3))
def test_unreachable_terminals_do_not_change_outcome(plan, extra):
    try:
        before = get_terminal_steps(plan)
    except ValueError:
        before = None
    steps = dict(plan.steps)
    for i in range(extra):
        sid = 'ZZ_orphan_%d' % i
        steps[sid] = Step(sid, None, None)
    bigger = Plan(first_step_id=plan.first_step_id, steps=steps)
    try:
        after = get_terminal_steps(bigger)
    except ValueError:
        after = None
    assert before == after
