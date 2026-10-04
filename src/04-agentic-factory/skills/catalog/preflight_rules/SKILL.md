---
name: preflight_rules
description: "Static plan analysis heuristics: reachability, parameter sanitation, destructive keys, and evidence checks."
triggers:
  - preflight
  - plan
  - reachability
  - risk_rules
skips:
  - live_execution
---

# Preflight Plan Static Analysis Rules

## 1. Plan Reachability
- The plan execution starts at `first_step_id`.
- Follow `next_step` transitions explicitly. A step with `next_step=None` signals intentional plan termination.
- Report any unreachable steps as structural defects (`UNREACHABLE_STEP`).

## 2. Destructive & Sensitive Actions
- `set_value`: Inspect the target selector and inputs. If updating sensitive settings, mark as `review`.
- Destructive keys: Special key sequences (e.g. `delete`, `ctrl+c`, `command+q`, raw terminal commands) require elevated `human_review` severity.
- Partial observation: If `allow_partial_observation=True`, flag an issue warning that success evidence may be incomplete.

## 3. Return Guarantees
- `status=valid` ONLY if all static assertions succeed. It NEVER implies authorization or runtime execution success.
- If an unexpected error occurs during analysis, status MUST be `unverified`, NEVER `valid`.
