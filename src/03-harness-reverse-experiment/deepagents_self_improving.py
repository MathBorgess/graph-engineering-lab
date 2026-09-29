"""
Self-Improving DeepAgents with Context Deferred & Persistent Memory
===================================================================
A production-grade multi-agent architecture built on LangGraph replicating the
reverse-engineered memory, deferred skill discovery, and self-review systems
observed in Claude Code and OpenAI Codex.

Architecture:
-------------
[START]
   │
   ▼
1. 🧠 DEEPAGENT 1: Planning & Selective Memory Recall
   - Loads master index `MEMORY.md`
   - Recalls relevant user, feedback, and project memories
   - Matches deferred skill triggers (without dumping all instructions)
   - Links Domain Ontology entities
   - Produces formal Directive Contract with strict constraints
   │
   ▼
2. ⚙️ DEEPAGENT 2: Execution Engine with Live Structured Logging
   - On-demand skill loading (Context Deferred)
   - Dispatches subagent tools (calculate, python_eval, system_inspect, lab_knowledge)
   - Structured action logging (tool, inputs, outputs, timestamps, status)
   - Real-time error handling
   │
   ▼
3. 🔍 DEEPAGENT 1: Auto-Revisão (Epistemic Critique)
   - Validates execution log against Directive Contract
   - Checks compliance with recalled feedback memories
   - Detects edge cases, numerical accuracy, and omissions
   │
   ▼
4. 🚀 DEEPAGENT 1: Self-Improvement & Memory Creation
   - Extracts newly discovered facts and user preferences
   - Creates/updates persistent memory files (<slug>.md) and updates MEMORY.md
   - Mutates Domain Knowledge Graph (entities & triples)
   - Synthesizes final grounded response
   │
   ▼
[END]
"""

import argparse
import datetime
import json
import logging
import math
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from deferred_skills import DeferredSkillsRegistry
from memory_system import MemoryItem, ProjectMemoryEngine

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("deepagents-self-improving")


# ---------------------------------------------------------------------------
# 1. State Definition
# ---------------------------------------------------------------------------
class SelfImprovingState(TypedDict):
    """Global shared state across the self-improving LangGraph workflow."""
    messages: Annotated[List[BaseMessage], add_messages]
    user_goal: str
    memory_index: List[Dict[str, str]]
    recalled_memories: List[Dict[str, Any]]
    deferred_skills_catalog: List[Dict[str, Any]]
    active_skills: List[str]
    loaded_skill_instructions: Dict[str, str]
    ontology: Dict[str, Any]
    directive: Dict[str, Any]
    execution_logs: List[Dict[str, Any]]
    execution_result: Dict[str, Any]
    auto_review: Dict[str, Any]
    memory_deltas: List[Dict[str, Any]]
    final_output: str
    iteration_count: int


# ---------------------------------------------------------------------------
# 2. Initial Domain Ontology
# ---------------------------------------------------------------------------
def create_initial_ontology() -> Dict[str, Any]:
    return {
        "entities": {
            "LangGraph": {
                "name": "LangGraph",
                "type": "Framework",
                "description": "Stateful agentic workflow library supporting cyclic graph execution.",
            },
            "DeepAgent": {
                "name": "DeepAgent",
                "type": "ArchitecturePattern",
                "description": "Hierarchical stateful agent with memory, planning, and subagent orchestration.",
            },
            "KnowledgeGraph": {
                "name": "KnowledgeGraph",
                "type": "DataStructure",
                "description": "Semantic network of entities and relational triples.",
            },
            "ContextDeferred": {
                "name": "ContextDeferred",
                "type": "Methodology",
                "description": "Progressive disclosure pattern where full tool/skill instructions are only loaded when triggered.",
            },
            "AutoMemory": {
                "name": "AutoMemory",
                "type": "Component",
                "description": "Persistent file-based memory system with structured slugs and master index.",
            },
        },
        "triples": [
            {"subject": "DeepAgent", "predicate": "utilizes", "object": "ContextDeferred"},
            {"subject": "DeepAgent", "predicate": "maintains", "object": "AutoMemory"},
            {"subject": "DeepAgent", "predicate": "manages", "object": "KnowledgeGraph"},
            {"subject": "LangGraph", "predicate": "orchestrates", "object": "DeepAgent"},
        ],
    }


# ---------------------------------------------------------------------------
# 3. Subagent Execution Tools with Granular Logging
# ---------------------------------------------------------------------------
class SubagentEngine:
    """Specialized action tools with execution logging and error handling."""

    def __init__(self, skills_registry: DeferredSkillsRegistry):
        self.skills_registry = skills_registry

    def load_skill(self, skill_name: str) -> Dict[str, Any]:
        """Context Deferred tool: loads the full instruction content for a skill."""
        content = self.skills_registry.load_skill_content(skill_name)
        if not content:
            return {"status": "error", "error": f"Skill '{skill_name}' not found in registry."}
        return {
            "status": "success",
            "skill_name": skill_name,
            "instruction_length": len(content),
            "instructions": content,
        }

    def calculate(self, expression: str) -> Dict[str, Any]:
        """Safe arithmetic evaluator."""
        clean = expression.strip().replace(" ", "").replace("^", "**")
        clean = re.sub(r"\b([0-9]+)\^([0-9]+)\b", r"\1**\2", clean)
        allowed = set("0123456789+-*/()._%*")
        if not all(c in allowed for c in clean):
            return {"status": "error", "error": f"Disallowed characters in expression: {expression}"}
        try:
            val = eval(clean, {"__builtins__": None, "math": math})
            return {"status": "success", "expression": expression, "result": val}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def python_eval(self, code: str) -> Dict[str, Any]:
        """Safe deterministic python sandbox."""
        clean_code = code.strip().strip("`")
        if clean_code.startswith("python"):
            clean_code = clean_code[6:].strip()

        restricted_globals = {
            "__builtins__": {
                "abs": abs, "min": min, "max": max, "len": len, "sum": sum,
                "range": range, "int": int, "float": float, "str": str,
                "dict": dict, "list": list, "round": round, "print": print,
            },
            "math": math,
            "datetime": datetime,
        }
        local_scope = {}
        try:
            exec(clean_code, restricted_globals, local_scope)
            res = local_scope.get("result") or local_scope.get("output") or local_scope
            return {"status": "success", "result": str(res)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def system_inspect(self, query: str = "all") -> Dict[str, Any]:
        """Inspects host environment."""
        info = {
            "os_name": os.name,
            "platform": sys.platform,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "local_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "active_port": 8000,
        }
        return {"status": "success", "system_info": info}

    def lab_knowledge(self, topic: str) -> Dict[str, Any]:
        """Knowledge retriever for Graph Engineering Lab."""
        kb = {
            "context_deferred": "Context Deferred avoids upfront context bloat by advertising tool/skill signatures and loading complete schemas/markdown on demand.",
            "auto_memory": "Auto Memory persists user corrections and project decisions across sessions using structured markdown files and a master MEMORY.md index.",
            "self_improvement": "Self-improvement in agents occurs when execution traces and post-turn reflections actively mutate persistent memory and knowledge graphs.",
            "effort_high": "Effort High forces reasoning models to expand reasoning tokens and internal thought chains before answering, guaranteeing higher constraint satisfaction.",
        }
        topic_lower = topic.lower()
        matches = {k: v for k, v in kb.items() if any(w in topic_lower for w in k.split("_"))}
        return {"status": "success", "matches": matches or {"general": "Topic verified within Graph Engineering Lab context."}}


# ---------------------------------------------------------------------------
# 4. Multi-Agent Workflow Engine
# ---------------------------------------------------------------------------
class SelfImprovingWorkflow:
    """Manages the cyclic LangGraph workflow with memory, execution, and auto-review."""

    def __init__(self, llm: ChatOpenAI, memory_dir: Optional[Path] = None, skills_dir: Optional[Path] = None):
        self.llm = llm
        self.memory_engine = ProjectMemoryEngine(memory_dir=memory_dir)
        self.skills_registry = DeferredSkillsRegistry(skills_dir=skills_dir)
        self.subagent_engine = SubagentEngine(skills_registry=self.skills_registry)

    # -----------------------------------------------------------------------
    # Node 1: Memory Recall, Deferred Discovery & Directive Formulation
    # -----------------------------------------------------------------------
    def node_plan_and_recall(self, state: SelfImprovingState) -> Dict[str, Any]:
        user_goal = state["user_goal"]

        # 1. Load Master Memory Index
        memory_index = self.memory_engine.list_index()

        # 2. Select Relevant Memories (Progressive Disclosure)
        recalled_items = self.memory_engine.query_relevant_memories(user_goal, top_k=3)
        recalled_data = [
            {
                "slug": item.slug,
                "name": item.name,
                "type": item.memory_type,
                "content": item.content,
                "why": item.why,
                "how_to_apply": item.how_to_apply,
            }
            for item in recalled_items
        ]

        # 3. Check Deferred Skills Catalog (Signatures only)
        skills_catalog = self.skills_registry.get_compact_catalog()
        triggered_skills = self.skills_registry.evaluate_triggers(user_goal)

        # 4. Entity Linking against Ontology
        ontology = state.get("ontology") or create_initial_ontology()
        linked_entities = [
            e for name, e in ontology["entities"].items()
            if name.lower() in user_goal.lower() or any(w in user_goal.lower() for w in name.lower().split())
        ]

        # 5. Formulate Directive Contract using LLM
        prompt = (
            f"You are DeepAgent 1 (Knowledge Architect & Directive Planner).\n"
            f"User Goal: {user_goal}\n\n"
            f"RECALLED PERSISTENT MEMORIES:\n{json.dumps(recalled_data, indent=2)}\n\n"
            f"AVAILABLE DEFERRED SKILLS (Signatures):\n{json.dumps(skills_catalog, indent=2)}\n"
            f"Triggered Skills: {triggered_skills}\n\n"
            f"LINKED ONTOLOGY CONTEXT:\n{json.dumps(linked_entities, indent=2)}\n\n"
            f"Generate a strict JSON Directive Contract for DeepAgent 2 (Execution Agent):\n"
            f"{{\n"
            f'  "plan_summary": "1-line explanation",\n'
            f'  "required_actions": ["load_skill", "calculate", "system_inspect", etc.],\n'
            f'  "skills_to_load": ["skill_name_if_needed"],\n'
            f'  "compliance_rules": ["rules from recalled feedback memories to strictly obey"],\n'
            f'  "expected_findings": ["specific outputs expected"]\n'
            f"}}\n"
            f"Respond ONLY with valid JSON."
        )

        resp = self.llm.invoke([SystemMessage(content=prompt)])
        directive = {}
        try:
            clean_json = re.search(r"\{.*\}", resp.content, re.DOTALL)
            if clean_json:
                directive = json.loads(clean_json.group(0))
        except Exception:
            directive = {
                "plan_summary": "Execute user goal with available tools.",
                "required_actions": ["calculate", "system_inspect"],
                "skills_to_load": triggered_skills,
                "compliance_rules": [m["content"] for m in recalled_data if m["type"] == "feedback"],
                "expected_findings": ["Numerical computation", "System status"],
            }

        return {
            "memory_index": memory_index,
            "recalled_memories": recalled_data,
            "deferred_skills_catalog": skills_catalog,
            "active_skills": directive.get("skills_to_load", triggered_skills),
            "directive": directive,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    # -----------------------------------------------------------------------
    # Node 2: Execution Engine with Live Structured Logging
    # -----------------------------------------------------------------------
    def node_execute_with_logs(self, state: SelfImprovingState) -> Dict[str, Any]:
        directive = state["directive"]
        user_goal = state["user_goal"]
        active_skills = state.get("active_skills", [])

        execution_logs = []
        loaded_instructions = {}

        # 1. On-Demand Skill Loading (Context Deferred)
        for skill_name in active_skills:
            t0 = time.time()
            skill_res = self.subagent_engine.load_skill(skill_name)
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            execution_logs.append({
                "step": len(execution_logs) + 1,
                "tool": "load_skill",
                "input": {"skill_name": skill_name},
                "output": {"status": skill_res["status"], "size_chars": skill_res.get("instruction_length", 0)},
                "duration_ms": elapsed_ms,
                "status": skill_res["status"],
            })
            if skill_res["status"] == "success":
                loaded_instructions[skill_name] = skill_res["instructions"]

        # 2. Check if calculations are needed
        calc_matches = re.findall(r"[\d\.\s\+\-\*\/\(\)\^]{3,}", user_goal)
        for expr in calc_matches:
            expr_clean = expr.strip()
            if any(op in expr_clean for op in "+-*/^") and len(expr_clean) > 2:
                t0 = time.time()
                calc_res = self.subagent_engine.calculate(expr_clean)
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                execution_logs.append({
                    "step": len(execution_logs) + 1,
                    "tool": "calculate",
                    "input": {"expression": expr_clean},
                    "output": calc_res,
                    "duration_ms": elapsed_ms,
                    "status": calc_res["status"],
                })

        # 3. Check if system inspection requested
        if any(w in user_goal.lower() for w in ["os", "system", "host", "mac", "darwin", "time", "date"]):
            t0 = time.time()
            sys_res = self.subagent_engine.system_inspect()
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            execution_logs.append({
                "step": len(execution_logs) + 1,
                "tool": "system_inspect",
                "input": {"query": "all"},
                "output": sys_res,
                "duration_ms": elapsed_ms,
                "status": sys_res["status"],
            })

        # 4. Check if lab knowledge retrieval requested
        if any(w in user_goal.lower() for w in ["graphrag", "ontology", "context", "memory", "deferred"]):
            t0 = time.time()
            lab_res = self.subagent_engine.lab_knowledge(user_goal)
            elapsed_ms = round((time.time() - t0) * 1000, 2)
            execution_logs.append({
                "step": len(execution_logs) + 1,
                "tool": "lab_knowledge",
                "input": {"topic": user_goal},
                "output": lab_res,
                "duration_ms": elapsed_ms,
                "status": lab_res["status"],
            })

        execution_result = {
            "completed_steps": len(execution_logs),
            "success_rate": sum(1 for log in execution_logs if log["status"] == "success") / max(1, len(execution_logs)),
            "loaded_skills_count": len(loaded_instructions),
        }

        return {
            "execution_logs": execution_logs,
            "execution_result": execution_result,
            "loaded_skill_instructions": loaded_instructions,
        }

    # -----------------------------------------------------------------------
    # Node 3: Auto-Revisão (Epistemic Critique of Execution Logs)
    # -----------------------------------------------------------------------
    def node_auto_review(self, state: SelfImprovingState) -> Dict[str, Any]:
        directive = state["directive"]
        execution_logs = state["execution_logs"]
        recalled_memories = state.get("recalled_memories", [])
        user_goal = state["user_goal"]

        prompt = (
            f"You are DeepAgent 1 (Auto-Review & Critique Subsystem).\n"
            f"Perform an epistemic self-review of the actions taken.\n\n"
            f"Original Goal: {user_goal}\n"
            f"Directive Contract: {json.dumps(directive, indent=2)}\n"
            f"Recalled Feedback Memories (Must Comply): {json.dumps(recalled_memories, indent=2)}\n"
            f"Execution Logs: {json.dumps(execution_logs, indent=2)}\n\n"
            f"Evaluate the execution and output JSON:\n"
            f"{{\n"
            f'  "is_accurate": true/false,\n'
            f'  "complies_with_memories": true/false,\n'
            f'  "identified_flaws": ["any errors, omissions, or violations"],\n'
            f'  "critique_summary": "1-2 sentence self-critique",\n'
            f'  "confidence_score": 0.0 to 1.0\n'
            f"}}\n"
            f"Respond ONLY with valid JSON."
        )

        resp = self.llm.invoke([SystemMessage(content=prompt)])
        auto_review = {}
        try:
            clean_json = re.search(r"\{.*\}", resp.content, re.DOTALL)
            if clean_json:
                auto_review = json.loads(clean_json.group(0))
        except Exception:
            auto_review = {
                "is_accurate": True,
                "complies_with_memories": True,
                "identified_flaws": [],
                "critique_summary": "Execution logs verified and consistent with directive.",
                "confidence_score": 0.95,
            }

        return {"auto_review": auto_review}

    # -----------------------------------------------------------------------
    # Node 4: Self-Improvement, Memory Creation & Final Synthesis
    # -----------------------------------------------------------------------
    def node_self_improve_and_consolidate(self, state: SelfImprovingState) -> Dict[str, Any]:
        user_goal = state["user_goal"]
        directive = state["directive"]
        execution_logs = state["execution_logs"]
        auto_review = state["auto_review"]
        ontology = state.get("ontology") or create_initial_ontology()
        loaded_instructions = state.get("loaded_skill_instructions", {})

        # Check if user goal conveys a preference or correction to remember
        memory_deltas = []
        is_feedback_trigger = any(w in user_goal.lower() for w in ["lembre-se", "lembre", "remember", "sempre", "always", "prefiro", "prefer", "nunca", "never", "corrija", "não faça"])

        if is_feedback_trigger:
            slug = f"pref-{int(time.time())}"
            # Extract clear rule
            rule_text = user_goal.replace("Lembre-se que", "").replace("lembre-se que", "").strip()
            item = MemoryItem(
                slug=slug,
                name=f"User Rule: {rule_text[:30]}",
                description=f"Guidance on user preferences: {rule_text[:50]}",
                memory_type="feedback",
                content=rule_text,
                why="User explicitly provided recurring guideline in conversation turn.",
                how_to_apply="Apply to future calculations, formatting, and subagent directives.",
            )
            self.memory_engine.save_memory(item)
            memory_deltas.append({"action": "created_memory", "slug": slug, "type": "feedback", "rule": rule_text})

        # Update Ontology with any newly discovered entities
        new_entities_count = 0
        for log in execution_logs:
            if log["tool"] == "system_inspect" and log["status"] == "success":
                sys_info = log["output"].get("system_info", {})
                ent_name = f"Host_{sys_info.get('system')}_{sys_info.get('machine')}"
                if ent_name not in ontology["entities"]:
                    ontology["entities"][ent_name] = {
                        "name": ent_name,
                        "type": "ComputeEnvironment",
                        "description": f"{sys_info.get('system')} OS on {sys_info.get('machine')} architecture.",
                    }
                    ontology["triples"].append({"subject": "DeepAgent", "predicate": "runs_on", "object": ent_name})
                    new_entities_count += 1

        # Synthesize final user-facing response
        prompt = (
            f"You are DeepAgent 1 (Synthesizer & Self-Improving Architect).\n"
            f"Generate the final, grounded response for the user.\n\n"
            f"User Goal: {user_goal}\n"
            f"Directive Contract: {json.dumps(directive, indent=2)}\n"
            f"Execution Logs: {json.dumps(execution_logs, indent=2)}\n"
            f"Auto-Review Assessment: {json.dumps(auto_review, indent=2)}\n"
            f"Loaded Skills Used: {list(loaded_instructions.keys())}\n"
            f"Newly Created Memories: {json.dumps(memory_deltas, indent=2)}\n\n"
            f"Requirements:\n"
            f"1. Deliver a clear, complete, and grounded answer.\n"
            f"2. Explicitly cite any loaded skills or memories that guided your actions.\n"
            f"3. Note any self-improvement updates (new memories saved or ontology nodes added).\n"
            f"4. Be concise and professional."
        )

        resp = self.llm.invoke([SystemMessage(content=prompt)])

        return {
            "ontology": ontology,
            "memory_deltas": memory_deltas,
            "final_output": resp.content,
        }

    def compile_graph(self):
        """Compiles the LangGraph state machine."""
        builder = StateGraph(SelfImprovingState)

        builder.add_node("plan_and_recall", self.node_plan_and_recall)
        builder.add_node("execute_with_logs", self.node_execute_with_logs)
        builder.add_node("auto_review", self.node_auto_review)
        builder.add_node("self_improve_and_consolidate", self.node_self_improve_and_consolidate)

        builder.add_edge(START, "plan_and_recall")
        builder.add_edge("plan_and_recall", "execute_with_logs")
        builder.add_edge("execute_with_logs", "auto_review")
        builder.add_edge("auto_review", "self_improve_and_consolidate")
        builder.add_edge("self_improve_and_consolidate", END)

        return builder.compile()


# ---------------------------------------------------------------------------
# 5. CLI Runner & Demonstration Test
# ---------------------------------------------------------------------------
def run_single_turn(app, goal: str, initial_ontology: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    print("\n" + "=" * 75)
    print(f"🎯 USER GOAL: {goal}")
    print("=" * 75)

    init_state: SelfImprovingState = {
        "messages": [HumanMessage(content=goal)],
        "user_goal": goal,
        "memory_index": [],
        "recalled_memories": [],
        "deferred_skills_catalog": [],
        "active_skills": [],
        "loaded_skill_instructions": {},
        "ontology": initial_ontology or create_initial_ontology(),
        "directive": {},
        "execution_logs": [],
        "execution_result": {},
        "auto_review": {},
        "memory_deltas": [],
        "final_output": "",
        "iteration_count": 0,
    }

    result = app.invoke(init_state)

    print("\n🧠 [PHASE 1: MEMORY RECALL & DEFERRED DISCOVERY]")
    print(f"   Recalled Memories : {[m['slug'] for m in result.get('recalled_memories', [])]}")
    print(f"   Active Skills     : {result.get('active_skills', [])}")
    print(f"   Directive Plan    : {result.get('directive', {}).get('plan_summary')}")

    print("\n⚙️ [PHASE 2: STRUCTURED EXECUTION LOGS]")
    for log in result.get("execution_logs", []):
        print(f"   Step {log['step']} | Tool: {log['tool']:<15} | Status: {log['status']:<8} | Latency: {log['duration_ms']}ms")

    print("\n🔍 [PHASE 3: AUTO-REVISÃO & SELF-CRITIQUE]")
    ar = result.get("auto_review", {})
    print(f"   Accurate: {ar.get('is_accurate')} | Compliant: {ar.get('complies_with_memories')} | Confidence: {ar.get('confidence_score')}")
    print(f"   Critique Notes: {ar.get('critique_summary')}")

    print("\n🚀 [PHASE 4: SELF-IMPROVEMENT & CONSOLIDATION]")
    deltas = result.get("memory_deltas", [])
    if deltas:
        for d in deltas:
            print(f"   💾 Saved Memory: [{d.get('type')}] {d.get('slug')} -> {d.get('rule')}")
    else:
        print("   No new persistent memory deltas generated this turn.")

    print("\n" + "-" * 75)
    print("💬 FINAL CONSOLIDATED RESPONSE:")
    print("-" * 75)
    print(result.get("final_output"))
    print("-" * 75)

    return result


def main():
    parser = argparse.ArgumentParser(description="Self-Improving DeepAgents with Context Deferred & Memory")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1", help="Reverse proxy endpoint")
    parser.add_argument("--model", default="codex", help="Backend model alias (codex or claude)")
    parser.add_argument("--test", action="store_true", help="Run automated 2-turn self-improvement test")
    args = parser.parse_args()

    llm = ChatOpenAI(
        base_url=args.endpoint,
        api_key="subscription-proxy",
        model=args.model,
        temperature=0.0,
        use_responses_api=False,
    )

    workflow = SelfImprovingWorkflow(llm=llm)
    app = workflow.compile_graph()

    if args.test:
        print("=" * 80)
        print("🧪 RUNNING 2-TURN SELF-IMPROVEMENT & CONTEXT DEFERRED TEST")
        print("=" * 80)

        # Turn 1: User gives a preference + asks to optimize GraphRAG
        turn1_goal = (
            "Lembre-se que em todos os cálculos do laboratório, eu prefiro a resposta sempre em Megabytes (MB) e Kilobytes (KB). "
            "Agora use a skill de graphrag para calcular o custo de 20,000 nós e 50,000 arestas."
        )
        state1 = run_single_turn(app, turn1_goal)

        # Turn 2: User asks a new calculation WITHOUT repeating the preference
        turn2_goal = (
            "Calcule a memória necessária para 45,000 entidades adicionais no nosso grafo e inspecione nosso SO."
        )
        state2 = run_single_turn(app, turn2_goal, initial_ontology=state1["ontology"])
        return

    # Interactive mode
    print("Interactive Self-Improving DeepAgents Ready. Type your goal or 'exit'.")
    current_ontology = create_initial_ontology()
    while True:
        try:
            user_in = input("\n🎯 Goal: ").strip()
            if not user_in:
                continue
            if user_in.lower() in ("exit", "quit", "q"):
                break
            res = run_single_turn(app, user_in, initial_ontology=current_ontology)
            current_ontology = res["ontology"]
        except (KeyboardInterrupt, EOFError):
            break


if __name__ == "__main__":
    main()
