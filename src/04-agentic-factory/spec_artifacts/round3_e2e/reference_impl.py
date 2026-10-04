from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Step:
    id: str
    next_step: Optional[str] = None
    on_failure: Optional[str] = None


@dataclass
class Plan:
    first_step_id: str
    steps: Dict[str, Step] = field(default_factory=dict)


def get_terminal_steps(plan: Plan) -> List[str]:
    seen = set()
    stack = [plan.first_step_id]
    terminals = []
    while stack:
        sid = stack.pop()
        if sid in seen or sid not in plan.steps:
            continue
        seen.add(sid)
        step = plan.steps[sid]
        if step.next_step is None:
            terminals.append(sid)
        else:
            stack.append(step.next_step)
        if step.on_failure is not None:
            stack.append(step.on_failure)
    if not terminals:
        raise ValueError('Plan has no reachable terminal step')
    return sorted(terminals)
