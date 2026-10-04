"""Harness para execução dos testes adversariais do Experimento 04.

Suporta:
- Modo A1: Teste de detecção pura (Validators determinísticos + DoD Scorecard)
- Modo A2: Teste ponta a ponta no StateGraph LangGraph com o Deep Agent Worker
- Inspeção de travas do Judge e simulação de decisões nos portões HITL.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

LAB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTORY_DIR = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.workflow import build_agentic_factory_graph
from graph.nodes import validator_node, dod_node, judge_node
from agents.judge import create_deep_agent_judge, evaluate_code_with_judge


WORKTREE_PATH = Path("/Users/matheusborges/github/mcps-catalog-worktree-exp04/laya-computer").resolve()
OUTPUT_DIR = FACTORY_DIR / "eval" / "adversarial"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def reset_worktree():
    """Restaura o worktree ao commit limpo da baseline verde."""
    subprocess.run(["git", "checkout", "-f"], cwd=str(WORKTREE_PATH), check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=str(WORKTREE_PATH), check=True, capture_output=True)


def run_pipeline_a1(case_id: str, description: str, allowed_patterns: Optional[List[str]] = None) -> Dict[str, Any]:
    """Modo A1: Executa a bateria de validadores e DoD sem invocar o worker."""
    patterns = allowed_patterns or ["laya_computer/*", "tests/*", "README.md", "pyproject.toml"]
    
    # Executa validators
    state = {
        "worktree_path": str(WORKTREE_PATH),
        "affected_files": [],
        "feature_name": "preflight_plan",
        "raw_memories_path": str(FACTORY_DIR / "memory" / "raw_memories.jsonl"),
    }
    v_output = validator_node(state, patterns)
    state.update(v_output)
    
    dod_output = dod_node(state)
    state.update(dod_output)
    
    # Formata resultados dos validadores
    v_results = []
    for r in state.get("validation_results", []):
        v_results.append({
            "validator_name": r.validator_name,
            "status": r.status,
            "exit_code": r.exit_code,
            "details": r.details[:400] if r.details else "",
            "requires_interrupt": r.requires_interrupt,
            "issues": [
                {
                    "code": i.code,
                    "category": i.category,
                    "severity": i.severity,
                    "message": i.message,
                    "suggestion": i.suggestion,
                }
                for i in r.issues
            ],
        })
        
    dod_pillars = []
    dod_rep = state.get("dod_report")
    if dod_rep:
        for p in dod_rep.pillars:
            dod_pillars.append({
                "name": p.name,
                "passed": p.passed,
                "evidence": p.evidence,
                "details": p.details,
            })

    result_data = {
        "case_id": case_id,
        "mode": "A1_pipeline_only",
        "description": description,
        "is_valid": state.get("is_valid", False),
        "ready_for_human_acceptance": state.get("ready_for_human_acceptance", False),
        "validation_results": v_results,
        "dod_pillars": dod_pillars,
    }
    
    out_file = OUTPUT_DIR / f"{case_id}_a1.json"
    out_file.write_text(json.dumps(result_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return result_data
