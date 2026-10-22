"""Regression tests against the actual LangGraph and SQLite execution path."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from voice_lab.contracts.state import ActionProposal, ConversationState
from voice_lab.graph.builder import build_voice_graph
from voice_lab.graph.checkpoints import get_checkpointer
from voice_lab.graph.validators import saga_executor_node
from voice_lab.tools.operational_tools import execute_trigger_experiment, list_jobs
from voice_lab.tools.sandbox import OperationalSandbox


def turn(graph, text, config, message_id=None):
    return graph.invoke({"messages": [HumanMessage(content=text, id=message_id)]}, config)


@pytest.mark.parametrize("reply", [
    "quero apenas uma simulação", "sim, mas explique antes", "pode explicar?",
    "ok, se eu confirmar depois", "não sei", "sim ou não?",
])
def test_ambiguous_reply_never_executes(sandbox, reply):
    graph = build_voice_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "ambiguous"}}
    pending = turn(graph, "Pode executar o experimento 05", config)
    assert pending["pending_proposal"].status == "pending"
    turn(graph, reply, config)
    assert sandbox.list_jobs() == []


def test_replaying_request_cannot_confirm_it(sandbox):
    graph = build_voice_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "replay"}}
    turn(graph, "Pode executar o experimento 05", config, "request-1")
    turn(graph, "Pode executar o experimento 05", config, "request-1")
    assert sandbox.list_jobs() == []


def test_separate_confirmed_proposals_create_separate_jobs(sandbox):
    graph = build_voice_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "new-proposals"}}
    for _ in range(2):
        turn(graph, "Pode executar o experimento 05", config)
        result = turn(graph, "Sim, confirmo a execução!", config)
        assert result["last_tool_result"].status == "success"
    assert len(sandbox.list_jobs()) == 2


def test_read_does_not_seed_jobs_or_audit_events(sandbox):
    assert list_jobs.invoke({})["jobs"] == []
    assert list_jobs.invoke({"status_filter": "completed"})["jobs"] == []
    with sandbox._get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 0


def test_active_query_returns_running_jobs(sandbox):
    sandbox.trigger_job("05_voice_agents", "local_light", "active-job")
    graph = build_voice_graph(InMemorySaver())
    result = turn(graph, "listar jobs ativos", {"configurable": {"thread_id": "read"}})
    assert result["last_tool_result"].data["total"] == 1


def test_reused_key_with_different_arguments_is_rejected(sandbox):
    sandbox.trigger_job("01_experiment", "local_light", "same-key")
    with pytest.raises(ValueError, match="argument"):
        sandbox.trigger_job("02_experiment", "local_light", "same-key")
    assert len(sandbox.list_jobs()) == 1


def test_concurrent_retries_create_one_job(sandbox):
    def trigger(_):
        return sandbox.trigger_job("05_voice_agents", "local_light", "concurrent")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(trigger, range(16)))
    assert sum(is_new for _, is_new in results) == 1
    assert len({job.job_id for job, _ in results}) == 1


def test_confirmation_survives_sqlite_checkpoint_restart(sandbox, tmp_path):
    config = {"configurable": {"thread_id": "restart"}}
    path = tmp_path / "checkpoints.db"
    with get_checkpointer(path) as checkpointer:
        graph = build_voice_graph(checkpointer)
        turn(graph, "Pode executar o experimento 05", config, "request-1")
    with get_checkpointer(path) as checkpointer:
        graph = build_voice_graph(checkpointer)
        turn(graph, "quero apenas uma simulação", config, "explain-1")
        assert sandbox.list_jobs() == []
        turn(graph, "Sim, confirmo a execução!", config, "confirm-1")
    assert len(sandbox.list_jobs()) == 1


def test_executor_retry_is_stable_across_processes(sandbox):
    script = '''
from voice_lab.contracts.state import ActionProposal, ConversationState
from voice_lab.graph.validators import saga_executor_node
from voice_lab.agents.operations_agent import conversational_agent_node
from langchain_core.messages import HumanMessage
p = ActionProposal(proposal_id="retry-proposal", tool_name="trigger_experiment",
    arguments={"experiment_id": "05_voice_agents", "profile": "local_light"},
    summary_for_user="Execute 05", status="pending")
state = ConversationState(pending_proposal=p,
    messages=[HumanMessage(content="Sim, confirmo a execução!", id="fresh-confirmation")])
update = conversational_agent_node(state)
r = saga_executor_node(ConversationState(**update))["last_tool_result"]
assert r.status == "success", r.error
print(r.data["job_id"])
'''
    env = dict(os.environ, VOICE_LAB_ARTIFACTS_DIR=str(sandbox.db_path.parent),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    # Match the operational tool's configured filename in both fresh interpreters.
    env["VOICE_LAB_ARTIFACTS_DIR"] = str(sandbox.db_path.parent / "processes")
    ids = [subprocess.check_output([sys.executable, "-c", script],
           env=dict(env, PYTHONHASHSEED=seed), text=True).strip() for seed in ("1", "2")]
    assert ids[0] == ids[1]


def test_unregistered_tool_cannot_dispatch_trigger(sandbox):
    p = ActionProposal(proposal_id="other-tool", tool_name="unknown",
        arguments={"experiment_id": "05_voice_agents", "profile": "local_light"},
        summary_for_user="Unknown action", status="confirmed")
    saga_executor_node(ConversationState(pending_proposal=p))
    assert sandbox.list_jobs() == []


def test_changed_arguments_after_consent_do_not_execute(sandbox):
    from voice_lab.agents.operations_agent import conversational_agent_node
    p = ActionProposal(proposal_id="tamper", tool_name="trigger_experiment",
        arguments={"experiment_id": "05_voice_agents", "profile": "local_light"},
        summary_for_user="Execute 05")
    update = conversational_agent_node(ConversationState(pending_proposal=p,
        messages=[HumanMessage(content="Sim, confirmo!", id="confirm")]))
    update["pending_proposal"].arguments["profile"] = "hybrid_control"
    result = saga_executor_node(ConversationState(**update))
    assert result["last_tool_result"].status == "unknown"
    assert sandbox.list_jobs() == []


def test_core_import_does_not_load_audio_runtime():
    script = "import voice_lab, sys; assert 'numpy' not in sys.modules; assert 'mlx_whisper' not in sys.modules"
    subprocess.run([sys.executable, "-c", script], check=True,
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])))


def test_direct_execution_requires_a_retry_identity(sandbox):
    with pytest.raises(ValueError, match="idempotency_key"):
        execute_trigger_experiment("05_voice_agents", "local_light")
    assert sandbox.list_jobs() == []


def test_concurrent_cancel_records_one_compensation(sandbox):
    job, _ = sandbox.trigger_job("05_voice_agents", "local_light", "cancel-me")
    def cancel(_):
        return sandbox.cancel_job(job.job_id, "Requested", "cancel-key")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cancel, range(16)))
    assert sum(changed for _, changed in results) == 1
    with sandbox._get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM audit_log WHERE action = 'SAGA_COMPENSATION_CANCEL'").fetchone()[0] == 1
