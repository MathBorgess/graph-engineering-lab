"""
Composition and stability report for the payloads in captured/.

Reproduces every number the harness study quotes about request size, tool
schema weight, cache breakpoints and prefix stability, so the claims can be
re-checked (or re-run against a different setup) instead of taken on trust.

Usage:
    python analyze_payloads.py            # report for captured/
    python analyze_payloads.py DIR        # report for another capture directory

Sizes are compact JSON bytes (separators=(",", ":")). The capture files are
indented, so their size on disk is ~32% larger (1.32x) than the compact body.
Captures hold requests only (no `usage`), so nothing here is a token count or
a measured cache hit; it is structure and bytes.
"""

import collections
import glob
import json
import re
import sys
from pathlib import Path

CAPTURED = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "captured"


def compact(obj) -> int:
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def tool_source(name: str) -> str:
    if not name.startswith("mcp__"):
        return "(native)"
    return name.split("__")[1]


def system_chars(system) -> int:
    if isinstance(system, str):
        return len(system)
    return sum(len(b.get("text", "")) for b in system if isinstance(b, dict))


def turn_files(task: str):
    files = sorted(glob.glob(str(CAPTURED / f"{task}_claude_request_turn*_*.json")))
    return [f for f in files if not f.endswith("_summary.json")]


def claude_composition():
    print("== Claude requests, turn 0 of each task ==")
    tasks = sorted({Path(f).name.split("_claude_request")[0] for f in glob.glob(str(CAPTURED / "*_claude_request_turn0_*.json"))})
    for task in tasks:
        files = turn_files(task)
        if not files:
            continue
        d = json.load(open(files[0], encoding="utf-8"))
        total, tools, msgs = compact(d), compact(d["tools"]), compact(d["messages"])
        print(f"\n{task}: total={total:,} B | tools={tools:,} B ({100 * tools / total:.0f}%) n={len(d['tools'])}"
              f" | system={system_chars(d['system']):,} chars | messages={msgs:,} B")
        by_src, n_src = collections.Counter(), collections.Counter()
        for t in d["tools"]:
            by_src[tool_source(t["name"])] += compact(t)
            n_src[tool_source(t["name"])] += 1
        for src, b in by_src.most_common(6):
            print(f"   {src:44s} {n_src[src]:3d} tools {b:8,} B ({100 * b / tools:4.1f}% of tools)")
        heavy = sorted(d["tools"], key=lambda t: -compact(t))[:5]
        print("   heaviest:", ", ".join(f"{t['name']} {compact(t):,}" for t in heavy))
        print("   system cache_control:", [b.get("cache_control") for b in d["system"] if isinstance(b, dict)])
        print("   thinking:", d.get("thinking"), "| output_config:", d.get("output_config"),
              "| context_management:", d.get("context_management"))


def claude_stability():
    print("\n\n== Prefix stability across turns (system, tools) ==")
    tasks = sorted({Path(f).name.split("_claude_request")[0] for f in glob.glob(str(CAPTURED / "*_claude_request_turn*_*.json"))})
    for task in tasks:
        prev = None
        print(f"\n{task}")
        for f in turn_files(task):
            d = json.load(open(f, encoding="utf-8"))
            sysj = json.dumps(d["system"], sort_keys=True)
            names = {t["name"] for t in d["tools"]}
            toolj = json.dumps(d["tools"], sort_keys=True)
            n_cache = sum(
                1 for m in d["messages"] if isinstance(m["content"], list)
                for b in m["content"] if isinstance(b, dict) and b.get("cache_control")
            )
            roles = collections.Counter(m["role"] for m in d["messages"])
            turn = re.search(r"turn(\d+)", f).group(1)
            line = f"   turn {turn:>2}: body={compact(d):,} B tools={len(names)} msgs={dict(roles)} cache_breakpoints_in_msgs={n_cache}"
            if prev:
                added, removed = sorted(names - prev[2]), sorted(prev[2] - names)
                line += f" | system_same={sysj == prev[0]} tools_same={toolj == prev[1]}"
                if added or removed:
                    line += f" (+{len(added)} / -{len(removed)} tools)"
            print(line)
            prev = (sysj, toolj, names)


def codex_skills():
    print("\n\n== Codex skills_instructions block (from `codex debug prompt-input`) ==")
    for f in sorted(glob.glob(str(CAPTURED / "*_codex_internal_debug_prompt.txt"))):
        d = json.load(open(f, encoding="utf-8"))
        block = d[0]["content"][0]["text"]
        ents = re.findall(r"\n- (\S+): (.*?) \(file: ([^)]*)\)", block)
        roots = {p.split("/")[0] for _, _, p in ents}
        names = collections.Counter(n.split(":")[-1] for n, _, _ in ents)
        lens = [len(x[1]) for x in ents]
        cut = sum(1 for _, desc, _ in ents if not desc.rstrip().endswith((".", "!", ")", "`")))
        print(f"{Path(f).name}: block={len(block):,} chars, entries={len(ents)}, roots={len(roots)}, "
              f"desc len min/avg/max={min(lens)}/{sum(lens) // len(lens)}/{max(lens)}, "
              f"no sentence end (likely cut)={cut}, redundant entries (same base name)={sum(v - 1 for v in names.values() if v > 1)}")
        extra = [(m["role"], sum(len(x.get("text", "")) for x in m["content"])) for m in d[1:]]
        print(f"   other messages: {extra}")


if __name__ == "__main__":
    claude_composition()
    claude_stability()
    codex_skills()
