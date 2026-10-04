import pytest

from reference_impl import Plan, Step, get_terminal_steps

MSG = 'Plan has no reachable terminal step'


def make_plan(first, *steps):
    return Plan(first_step_id=first, steps={s.id: s for s in steps})


def test_cycle_without_terminal_raises():
    plan = make_plan('a', Step('a', 'b'), Step('b', 'a'))
    with pytest.raises(ValueError, match=MSG):
        get_terminal_steps(plan)


def test_self_loop_without_terminal_raises():
    plan = make_plan('a', Step('a', 'a', on_failure='a'))
    with pytest.raises(ValueError, match=MSG):
        get_terminal_steps(plan)


def test_terminal_only_reachable_via_on_failure():
    plan = make_plan(
        'a',
        Step('a', 'b', on_failure='t'),
        Step('b', 'a'),
        Step('t', None),
    )
    assert get_terminal_steps(plan) == ['t']


def test_unreachable_terminal_is_excluded_and_failure_chain_from_terminal_followed():
    # 'orphan' is terminal but unreachable; 't1' is terminal and its on_failure leads to 't0'.
    plan = make_plan(
        'a',
        Step('a', 't1'),
        Step('t1', None, on_failure='t0'),
        Step('t0', None),
        Step('orphan', None),
    )
    assert get_terminal_steps(plan) == ['t0', 't1']

    cyc = make_plan('x', Step('x', 'y'), Step('y', 'x'), Step('orphan', None))
    with pytest.raises(ValueError, match=MSG):
        get_terminal_steps(cyc)
