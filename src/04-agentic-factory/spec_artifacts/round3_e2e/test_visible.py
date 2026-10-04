from reference_impl import Plan, Step, get_terminal_steps


def make_plan(first, *steps):
    return Plan(first_step_id=first, steps={s.id: s for s in steps})


def test_linear_plan_returns_last_step():
    plan = make_plan('a', Step('a', 'b'), Step('b', 'c'), Step('c', None))
    assert get_terminal_steps(plan) == ['c']


def test_single_step_plan_is_terminal():
    plan = make_plan('only', Step('only', None))
    assert get_terminal_steps(plan) == ['only']


def test_multi_branch_via_on_failure_returns_sorted_terminals():
    plan = make_plan(
        'start',
        Step('start', 'zeta', on_failure='alpha'),
        Step('zeta', None),
        Step('alpha', None),
    )
    assert get_terminal_steps(plan) == ['alpha', 'zeta']


def test_multiple_terminals_in_chain_are_sorted_and_unique():
    plan = make_plan(
        's',
        Step('s', 'm', on_failure='t2'),
        Step('m', 't1', on_failure='t2'),
        Step('t1', None),
        Step('t2', None),
    )
    assert get_terminal_steps(plan) == ['t1', 't2']
