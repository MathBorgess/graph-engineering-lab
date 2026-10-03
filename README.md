# Graph Engineering Lab

Experiments with Agentic Workflows, Knowledge Graphs, and Local LLM Tooling.

---

## 🌐 Native subscription proxies

Two independent local transports. LangChain handles tool schemas, tool call IDs,
tool results and streaming; the proxies inject subscription credentials and forward HTTP.

| Provider | Start | Endpoint | LangChain client |
| --- | --- | --- | --- |
| Codex | `python -m proxy.codex` | `http://127.0.0.1:8000/v1/responses` | `ChatOpenAI(use_responses_api=True)` |
| Claude | `python -m proxy.claude` | `http://127.0.0.1:8001/v1/messages` | `ChatAnthropic` |

```bash
pip install -r proxy/requirements.txt
python -m unittest discover -s proxy/tests -v
```

```python
from proxy.client import create_model

codex = create_model("codex", "gpt-6-sol")
claude = create_model("claude", "claude-sonnet-4-6")
# Both expose native LangChain bind_tools(), invoke() and stream().
```

Use a concrete model supported by your account. Offline tests use simulated upstreams;
live subscription compatibility remains unverified. See [proxy documentation](proxy/README.md).

`python src/subscription_proxy.py --backend codex` remains a launcher;
`--backend claude` starts the separate Claude server on port 8001.
`GET /health` checks server availability only.

### Historical experiments

The scripts below still use the former Chat Completions gateway and model aliases.
Their model construction must be migrated to `proxy.client.create_model()` before
running against these native proxies. `/v1/chat/completions` and `/v1/models`
are no longer exposed. The factory study spec uses the new constructor.

---

## 🤖 3. Running the LangChain ReAct Agent

```bash
# Query using Claude (Anthropic subscription)
python src/react_agent.py --model claude --query "Look up GraphRAG in the lab glossary and calculate 15 * 8."

# Query using Codex (ChatGPT subscription)
python src/react_agent.py --model codex --query "What is 500 divided by 4? Calculate it with calculate."

# Run automated test suite
python src/react_agent.py --test

# Interactive CLI chat mode
python src/react_agent.py --model claude
```

---

## 🧠 4. Running the Two-Tier DeepAgents LangGraph Workflow

A hierarchical, stateful multi-agent system built on LangGraph:
- **DeepAgent 1 (Memory & Ontology Agent)**: Entity Linking, Domain Knowledge Graph maintenance, Directive Contract formulation, and epistemic reflection / ontology growth.
- **DeepAgent 2 (Execution Agent)**: Orchestrator dispatching specialized subagents (`calculate`, `python_eval`, `system_inspect`, `lab_knowledge`).

```bash
# Automated end-to-end test (Plan -> Execute -> Reflect -> Graph Evolution)
python src/deep_agents_graph.py --test

# Interactive Studio mode (Ontology expands and persists across turns)
python src/deep_agents_graph.py --model codex

# Print Mermaid workflow diagram
python src/deep_agents_graph.py --mermaid

# One-shot query
python src/deep_agents_graph.py --model claude --query "Calculate 2^16 memory blocks and relate to GraphRAG."
```

---

## 📓 5. Lab Study & Architecture Assessment (Experiments 1 & 2)

For a comprehensive breakdown of the experiments, harness pollution analysis, MITM proxy mechanisms, and a **self-assessment question bank**, see:
👉 [**experiments/01_harness_proxy_and_deepagents_study.md**](experiments/01_harness_proxy_and_deepagents_study.md)

---

## 🔬 6. Experimento 03: Engenharia Reversa de Harnesses & DeepAgents com Auto-Memory

Engenharia reversa das injeções de harness do **Claude Code CLI** (requests capturados) e **OpenAI Codex CLI** (só o prompt de entrada e handshakes MCP) via MITM Proxy, revelando system prompts, discovery de skills/MCPs, gerenciamento de contexto e reasoning effort.

Replicado no DeepAgents com:
- **Auto-Memory Persistente**: Índice mestre `MEMORY.md` com arquivos `<slug>.md` estruturados em frontmatter YAML (`user`, `feedback`, `project`, `reference`).
- **Context Deferred**: Skills catalog leve e carregamento sob demanda (`load_skill`).
- **Logs Estruturados & Auto-Revisão (Crítica Epistêmica)**: revisão por LLM do log de execução antes da resposta final; o veredito não bloqueia o fluxo (ver a errata em `report.md`).
- **Self-Improvement Loop**: Mutação contínua de memória e ontologia a cada interação.

```bash
# Executar a suíte de engenharia reversa via MITM:
.venv/bin/python src/03-harness-reverse-experiment/run_experiment.py

# Teste automatizado de 2 turnos com autoaperfeiçoamento e memória:
.venv/bin/python src/03-harness-reverse-experiment/deepagents_self_improving.py --test

# Iniciar o Studio Interativo com Memória Persistente:
.venv/bin/python src/03-harness-reverse-experiment/deepagents_self_improving.py
```

Documentação e cadernos de laboratório:
- 👉 [**`src/03-harness-reverse-experiment/report.md`**](src/03-harness-reverse-experiment/report.md)
- 👉 [**`src/03-harness-reverse-experiment/memory_and_self_improvement_study.md`**](src/03-harness-reverse-experiment/memory_and_self_improvement_study.md)
- 👉 [**`experiments/03_harness_reverse_engineering.md`**](experiments/03_harness_reverse_engineering.md)
