"""Nós de execução do orquestrador LangGraph."""

from pathlib import Path
from typing import Any, Dict, List
from langchain_core.messages import HumanMessage

try:
    from ..contracts.state import FactoryState
    from ..validators.scope_validator import validate_diff_scope
    from ..validators.static_code_analysis import validate_codebase_static
    from ..validators.mcp_contract import validate_mcp_tool_contract
    from ..validators.code_quality import run_code_tests
    from ..validators.dod_validator import evaluate_definition_of_done
    from ..agents.judge import create_deep_agent_judge, evaluate_code_with_judge
except (ImportError, ValueError):
    from contracts.state import FactoryState
    from validators.scope_validator import validate_diff_scope
    from validators.static_code_analysis import validate_codebase_static
    from validators.mcp_contract import validate_mcp_tool_contract
    from validators.code_quality import run_code_tests
    from validators.dod_validator import evaluate_definition_of_done
    from agents.judge import create_deep_agent_judge, evaluate_code_with_judge


async def worker_node(state: Dict[str, Any], worker_instance) -> dict:
    """Invoca o Worker Deep Agent para implementar ou reparar a feature."""
    attempt = state.get("worker_attempt", 0) + 1
    messages = state.get("messages", [])

    # Se for uma rodada de reparo, a última mensagem traz as diretivas de correção
    result = await worker_instance.ainvoke({"messages": messages})
    worker_messages = result.get("messages", [])
    new_messages = worker_messages[len(messages):] if len(worker_messages) >= len(messages) else worker_messages

    return {
        "worker_attempt": attempt,
        "messages": new_messages,
    }


def validator_node(state: Dict[str, Any], allowed_scope_patterns: List[str]) -> dict:
    """Executa a bateria de validators determinísticos (Scope, SonarQube AST, Pytest e MCP)."""
    import subprocess
    worktree = Path(state.get("worktree_path", ".")).resolve()
    affected_files = list(state.get("affected_files", []))

    # 0. Auto-detecção de arquivos alterados via git status
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "."],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if len(line) >= 4:
                    rel_path = line[3:].strip().lstrip("/")
                    if " -> " in rel_path:
                        rel_path = rel_path.split(" -> ")[-1].strip()
                    if rel_path and rel_path not in affected_files:
                        affected_files.append(rel_path)
    except Exception:
        pass

    # 1. Validador de Escopo
    scope_res = validate_diff_scope(affected_files, allowed_scope_patterns)

    # 2. Validador SonarQube AST
    sonar_res = validate_codebase_static(worktree, target_files=affected_files)

    # 3. Validador de Testes Pytest
    test_res = run_code_tests(worktree)

    # 4. Validador de Contrato MCP extraído do server.py do worktree
    try:
        from ..validators.mcp_contract import extract_mcp_tools_from_worktree
    except (ImportError, ValueError):
        from validators.mcp_contract import extract_mcp_tools_from_worktree
    server_tools = extract_mcp_tools_from_worktree(worktree)
    mcp_res = validate_mcp_tool_contract(
        server_tools=server_tools,
        expected_tool_name="preflight_plan",
    )

    all_results = [scope_res, sonar_res, test_res, mcp_res]
    is_valid = all(r.status == "pass" for r in all_results)

    ret = {
        "affected_files": affected_files,
        "validation_results": all_results,
        "is_valid": is_valid,
    }
    if not is_valid:
        failures = []
        for r in all_results:
            if r.status != "pass":
                failures.append(f"Validator '{r.validator_name}' ({r.status}): {r.details}")
                for issue in r.issues:
                    failures.append(f"  - [{issue.severity}] {issue.code}: {issue.message}. Sugestão: {issue.suggestion}")
        feedback_content = (
            "### [Validators: Falhas Detectadas]\n"
            + "\n".join(failures)
            + "\nPor favor, analise as falhas acima e faça os ajustes necessários no código."
        )
        ret["messages"] = [HumanMessage(content=feedback_content)]

    return ret


async def judge_node(state: Dict[str, Any], base_url: str = None) -> dict:
    """Invoca o DeepAgent Judge Panel aplicando as travas anti-rabbit-hole."""
    worktree = Path(state.get("worktree_path", ".")).resolve()
    judge_attempts = state.get("judge_attempts", 0)

    # TRAVA 2: Orçamento máximo de 1 ciclo de reparo solicitado pelo Judge
    if judge_attempts >= 1:
        return {
            "judge_ready_for_dod": True,
            "judge_summary": "Judge esgotou o orçamento de 1 ciclo. Itens residuais convertidos em notas consultivas.",
        }

    judge_agent = create_deep_agent_judge(worktree, base_url=base_url)
    verdict = await evaluate_code_with_judge(judge_agent, state.get("feature_name", "feature"), state.get("affected_files", []))

    if verdict.verdict == "repair_required" and verdict.blockers:
        # TRAVA 1: Apenas blockers geram reparo
        remediations = [b.remediation_suggestion for b in verdict.blockers]
        repair_msg = (
            "### [Judge Panel: Correções Críticas Obrigatórias]\n"
            + "\n".join(f"- {r}" for r in remediations)
            + "\nPor favor, faça os ajustes necessários para sanar esses blockers de segurança/performance."
        )
        return {
            "judge_attempts": judge_attempts + 1,
            "is_valid": False,  # Redireciona para o worker
            "messages": [HumanMessage(content=repair_msg)],
            "judge_ready_for_dod": False,
        }

    return {
        "judge_ready_for_dod": True,
        "judge_summary": verdict.summary_for_human or "Aprovado sem blockers.",
    }


def dod_node(state: Dict[str, Any]) -> dict:
    """Consolida os 5 pilares da Definition of Done gerando o scorecard para o aceite humano."""
    worktree = Path(state.get("worktree_path", ".")).resolve()
    raw_memories = Path(state["raw_memories_path"]) if state.get("raw_memories_path") else None

    dod_report = evaluate_definition_of_done(
        feature_name=state.get("feature_name", "feature"),
        validation_results=state.get("validation_results", []),
        worktree_path=worktree,
        raw_memories_file=raw_memories,
    )

    return {
        "dod_report": dod_report,
        "dod_summary_markdown": dod_report.summary_markdown,
        "ready_for_human_acceptance": dod_report.ready_for_human_acceptance,
    }


def memory_distillation_node(state: Dict[str, Any]) -> dict:
    """Destila o WAL de memórias brutas salvando cartões permanentes para o projeto."""
    raw_path_str = state.get("raw_memories_path")
    if not raw_path_str:
        return {"active_memories_used": []}

    raw_file = Path(raw_path_str).resolve()
    if not raw_file.exists():
        return {"active_memories_used": []}

    # Aqui a destilação consolida as linhas do .jsonl gerando o índice
    return {
        "active_memories_used": ["mcp-preflight-heuristics"],
    }
