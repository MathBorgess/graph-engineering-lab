"""Reference implementation of the laya-computer preflight analyzer.

Assumes the models from the task statement are importable as `models`.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

try:
    from laya_computer.plan import Action, Plan
except ImportError:
    from models import Action, Plan

SCHEMA_VERSION = 1
CHECKS_RUN = ["plan_schema", "references", "reachability", "risk_rules"]
CHECKS_NOT_RUN = ["live_accessibility", "runtime_effects"]

DANGEROUS_SHORTCUTS = frozenset(
    {
        "cmd+q",
        "cmd+w",
        "cmd+shift+q",
        "cmd+delete",
        "cmd+backspace",
        "cmd+shift+delete",
        "cmd+option+esc",
        "ctrl+alt+delete",
        "alt+f4",
    }
)
DANGEROUS_SUBSTRINGS = ("command", "terminal")

_REFERENCE_CODES = (
    ("step ids must be unique", "DUPLICATE_STEP_ID"),
    ("start_step must refer", "UNKNOWN_START_STEP"),
    ("references unknown step", "UNKNOWN_STEP_REFERENCE"),
)


def _schema_issues(exc: ValidationError) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for err in exc.errors():
        message = str(err.get("msg", ""))
        code = "PLAN_SCHEMA_INVALID"
        for needle, candidate in _REFERENCE_CODES:
            if needle in message:
                code = candidate
                break
        issues.append(
            {
                "code": code,
                "severity": "error",
                "message": message,
                "location": ".".join(str(part) for part in err.get("loc", ())),
            }
        )
    return issues


def _is_dangerous_key(key: str) -> bool:
    lowered = key.strip().lower()
    compact = lowered.replace(" ", "")
    return compact in DANGEROUS_SHORTCUTS or any(s in lowered for s in DANGEROUS_SUBSTRINGS)


def _reachable(plan: Plan) -> set[str]:
    """Follow next_step only; on_failure edges are deliberately ignored."""
    by_id = {step.id: step for step in plan.steps}
    seen: set[str] = set()
    current: str | None = plan.first_step_id
    while current is not None and current not in seen:
        seen.add(current)
        current = by_id[current].next_step
    return seen


def _report(issues: list[dict[str, Any]], risks: set[str]) -> dict[str, Any]:
    if any(issue["severity"] == "error" for issue in issues):
        status, recommendation = "invalid", "repair"
    elif risks:
        status, recommendation = "unverified", "human_review"
    else:
        status, recommendation = "valid", "proceed_to_inspection"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "recommendation": recommendation,
        "issues": issues,
        "risk_factors": sorted(risks),
        "checks_run": list(CHECKS_RUN),
        "checks_not_run": list(CHECKS_NOT_RUN),
    }


def analyze_preflight_plan(plan_data: dict) -> dict:
    try:
        plan = Plan.model_validate(plan_data)
    except ValidationError as exc:
        return _report(_schema_issues(exc), set())

    issues: list[dict[str, Any]] = []
    reachable = _reachable(plan)
    for step in plan.steps:
        if step.id not in reachable:
            issues.append(
                {
                    "code": "UNREACHABLE_STEP",
                    "severity": "error",
                    "step_id": step.id,
                    "message": f"step {step.id!r} is not reachable through next_step",
                }
            )

    risks: set[str] = set()
    for step in plan.steps:
        found: list[str] = []
        if step.action == Action.SET_VALUE:
            found.append("writes_user_data")
        if step.key is not None and _is_dangerous_key(step.key):
            found.append("destructive_keys")
        if step.allow_partial_observation:
            found.append("partial_observation")
        for factor in found:
            risks.add(factor)
            issues.append(
                {
                    "code": f"RISK_{factor.upper()}",
                    "severity": "review",
                    "step_id": step.id,
                    "message": f"step {step.id!r} carries risk factor {factor}",
                }
            )

    return _report(issues, risks)