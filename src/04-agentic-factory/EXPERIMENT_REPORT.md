# Diário de Bordo & Relatório — Experimento 04: Agentic Software Factory

**Data de Início:** 2026-10-01  
**Status:** Em andamento (Construção acompanhada)  
**Objetivo:** Implementar uma fábrica agêntica para a feature `preflight_plan` no `laya-computer` com Deep Agents (worker), LangGraph (controlador), Validators com autoridade real, HITL e Memória Seletiva.

---

## 1. Registro de Decisões Arquiteturais e Critiques

| Tópico | Proposta Inicial | Crítica / Decisão do Usuário | Resolução Técnica Adotada |
| :--- | :--- | :--- | :--- |
| **Deferred Skills** | Exposição total ou descoberta genérica | Adotar `load_skill` tool; prompt inicial deve expor apenas `nome` + `descrição truncada em 110 caracteres` com progressive disclosure. | Catálogo compacto na inicialização do worker; expansão de `SKILL.md` apenas sob chamada explícita da tool `load_skill`. |
| **Tools & HITL** | Interrupção genérica de ferramentas | Concordado: modelo dual (Tier 1 safe em worktree, Tier 2 `interrupt_on` para tools sensíveis no worker, Tier 3 `interrupt()` macro no LangGraph). | Separação estrita em tools de sandbox e ferramentas com gate humano. |
| **Memória (WAL)** | Gravação rígida com `evidence_path` e contador no State | O que está ancorado no código **não** é memória. Worker gera `raw_memories` em `.jsonl` (append-only) em disco. Sem contadores redundantes no State. | Separação tríplice (State vs Git vs Reusable Memory). No State apenas `raw_memories_path`. Deduplicação/destilação ocorre em lote. |
| **Validators vs Agents** | Dúvida sobre o que são e por que não estão em `agents/` | Esclarecido: Validators técnicos são funções programáticas determinísticas (testes, linters, schemas) com poder de veto inegociável, não LLMs. Críticas semânticas subjetivas é que cabem a agentes. | `validators/` contém checagens de código puro e políticas estáveis (`pass`, `fail`, `unverified`). |

---

## 2. Memória de Sessão & Aprendizados Registrados

- **Aprendizado 1 (Eliminação de Estado Derivado/Redundante):** Não colocar contadores no State como `raw_memories_count`. O State deve manter apenas ponteiros (`raw_memories_path`). Contadores derivados no State criam descompasso com o sistema de arquivos físico e geram acoplamento desnecessário.
- **Aprendizado 2 (Padrão WAL - Write-Ahead Logging para Descobertas):** Anotações intermediárias de raciocínio e heurísticas do agente devem ser descarregadas atomicamente em um arquivo `.jsonl` em disco pelo worker. O State volátil do LangGraph fica blindado contra inchaço, e falhas inesperadas de nós não causam perda das descobertas.
- **Aprendizado 3 (Filtro Anti-Redundância de Código):** A memória persistente não deve reescrever a arquitetura que já está expressa no código-fonte. A destilação só consolida conceitos, heurísticas de decisão e correções humanas.
- **Aprendizado 4 (Orçamento de Atenção com 110 chars):** O catálogo do prompt inicial atua como um índice de baixa densidade (máximo 110 caracteres por descrição). A leitura profunda é sob demanda via `load_skill`.
- **Aprendizado 5 (Separação model_invoked e Slash Commands):** Skills com `model_invoked: true` entram no catálogo compacto para decisão autônoma do modelo. Skills com `model_invoked: false` são omitidas do system prompt e só ativam se o usuário digitar `/SKILL_NAME`, atuando como diretiva humana injetada pelo harness no turno.
- **Aprendizado 6 (Marco 0 — Protocolo Responses API no Proxy Codex):** 
  - *Coleta de Itens SSE:* O endpoint nativo `/codex/responses` envia itens durante `response.output_item.done`, deixando `output: []` vazio no evento final `response.completed`. O `proxy/transport.py` foi corrigido para acumular os itens e devolver a resposta íntegra ao LangChain.
  - *Sanitização de System Messages:* O backend ChatGPT rejeita mensagens com `role: "system"` ou `developer` no array `input` (erro 400). O `proxy/codex.py` foi atualizado para mover mensagens de sistema para o campo de topo `instructions`.
  - *Consumo de MCP no DeepAgents:* Testado com sucesso via `langchain_mcp_adapters.client.MultiServerMCPClient`. O DeepAgent executou o ciclo completo: ToolCall -> MCP stdio execution -> ToolMessage -> Resposta final sintetizada.
- **Aprendizado 7 (Worker Deep Agent & Sandbox Tools):**
  - O modelo econômico `gpt-6-luna` foi validado com sucesso em substituição ao `gpt-6-sol`.
  - As ferramentas de sandbox ([`tools/sandbox_fs.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/tools/sandbox_fs.py)) bloqueiam ativamente qualquer escape de diretório fora do worktree via `_resolve_safe_path`.
  - O portão `interrupt_on={"commit_memory": True}` intercepta com precisão a chamada sensível de memória no [`worker.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/agents/worker.py), retornando o payload serializável e retomando com sucesso via `Command(resume={"decisions": [{"type": "approve"}]})`.
  - O append no WAL `raw_memories.jsonl` funciona atomicamente sem onerar o State do LangGraph.
- **Aprendizado 8 (Validators estilo SonarQube & Soft Scope):**
  - O validador de escopo ([`validators/scope_validator.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/validators/scope_validator.py)) é não-bloqueante: se houver diff fora do esperado, ele marca `requires_interrupt=True` e `security_hotspot`, acionando o operador humano para decidir se aceita o desvio ou ordena retroceder/reverter.
  - A análise estática de código ([`validators/static_code_analysis.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/validators/static_code_analysis.py)) usa o AST nativo do Python mapeando a taxonomia do SonarQube:
    - *Bugs:* Erros de sintaxe (`blocker`), bare excepts (`major`).
    - *Vulnerabilidades:* Execução dinâmica perigosa (`eval`, `exec`, `os.system` -> `blocker`), credenciais em texto plano (`critical`).
    - *Code Smells:* Complexidade cognitiva / aninhamento excessivo > 3 (`major`), funções > 50 linhas (`minor`), ausência de type hints de retorno (`minor`).
    - *Security Hotspots:* Fatores que requerem verificação humana.
- **Aprendizado 9 (DeepAgent Judge Anti-Rabbit-Hole & DoD Scorecard):**
  - *Definition of Done (DoD):* Implementada em 5 pilares programáticos objetivos ([`validators/dod_validator.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/validators/dod_validator.py)): Contrato MCP, Suíte de Testes, Qualidade SonarQube, Higiene de Git e Memória WAL. A tarefa só é submetida ao aceite humano se todos os 5 pilares passarem.
  - *DeepAgent Judge Panel ([`agents/judge.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/agents/judge.py)):* Composto por subagentes especializados (`security_reviewer` e `performance_reviewer`) operando em modo isolado com ferramentas estritamente read-only.
  - *As 4 Travas Anti-Rabbit-Hole:*
    1. *Filtro de Veto:* Apenas findings classificados como `blocker` (segurança real ou travamentos) geram pedido de reparo. Sugestões cosméticas viram notas consultivas (`advisory`), sem bloquear.
    2. *Orçamento Estrito:* O Judge tem limite rígido de no máximo 1 ciclo de reparo.
    3. *Escalonamento em Dossiê:* Se houver divergência persistente, não há novo loop; o Judge gera um dossiê comparativo para o operador humano decidir no gate.
    4. *Juízes Read-Only:* Os revisores não possuem tools de escrita, impedindo que criem novos bugs.
- **Aprendizado 10 (Orquestrador LangGraph com Portões Duais):**
  - O grafo compilado ([`graph/workflow.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/graph/workflow.py)) interliga `worker` -> `validators` -> `scope_gate` (HITL) -> `judge` -> `dod` -> `final_gate` (HITL) -> `memory_distillation`.
  - Checkpointer preserva snapshots permitindo paradas e retomadas pelo mesmo `thread_id`.

---

## 3. Próximos Passos & Marcos

- [x] Criação da estrutura de pastas em `src/04-agentic-factory/`
- [x] Registro das diretrizes no diário de bordo (`EXPERIMENT_REPORT.md`)
- [x] Modelagem dos Contratos e `FactoryState` (`contracts/state.py` e `contracts/findings.py`)
- [x] Implementação do Registro de Skills e Tool `load_skill` com Slash Commands (`skills/`)
- [x] Validação do Proxy e execução do Probe / Marco 0 (`proxy/transport.py` e `proxy/codex.py`)
- [x] Demonstração de consumo direto de MCP pelo DeepAgent (`mcp_test_server.py`)
- [x] Implementação das ferramentas de Sandbox do Worker (`tools/sandbox_fs.py`, `tools/runner.py`, `tools/memory_tools.py`)
- [x] Implementação e teste live da factory do Deep Agent Worker com `gpt-6-luna` (`agents/worker.py`)
- [x] Implementação dos Validators programáticos e análise estática SonarQube (`validators/`)
- [x] Implementação do Validador da Definition of Done em 5 pilares (`validators/dod_validator.py`)
- [x] Implementação do DeepAgent Judge Panel com travas anti-rabbit-hole (`agents/judge.py`)
- [x] Orquestração completa LangGraph: nós, arestas e gates HITL duais (`graph/workflow.py`)
- [x] Elaboração do briefing de transição e métricas de sucesso ([`HANDOFF.md`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/HANDOFF.md))
- [x] Execução acompanhada da Feature `preflight_plan` no checkout isolado
- [ ] Tracing e Avaliação MLflow (`eval/`)

---

## 4. Execução Prática Ponta a Ponta: Feature `preflight_plan`

**Data de Conclusão do Teste:** 2026-10-04  
**Worktree Isolado:** `/Users/matheusborges/github/mcps-catalog-worktree-exp04/laya-computer` (Branch `feat/preflight-plan`)  
**Modelo:** `gpt-6-luna` (via Responses API proxy local na porta 8000)  
**Script de Execução:** [`src/04-agentic-factory/run_experiment_04.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/04-agentic-factory/run_experiment_04.py)  

### 4.1. Artefatos de Código Gerados pelo Worker
1. `laya_computer/preflight.py`: Análise estática pura contendo validação Pydantic com sanitização de erros, grafo de alcançabilidade a partir de `first_step_id` (detecção de `UNREACHABLE_STEP`), flags de risco (`writes_user_data`, `destructive_keys`, `partial_observation`) e resposta defensiva (`unverified` sob exceções imprevistas).
2. `laya_computer/server.py`: Tool MCP registrada via `@srv.tool() async def preflight_plan(plan: dict) -> dict` sem efeitos colaterais no desktop.
3. `tests/test_preflight.py`: 6 testes unitários cobrindo todos os cenários da Seção 2 da spec (mínimo válido, schema inválido, passo inalcançável, atalhos perigosos, observação parcial e exceção forçada via monkeypatch).
4. `tests/test_protocol.py`: Descoberta de ferramentas stdio atualizada para incluir `"preflight_plan"`. Suíte total executou **55/55 testes aprovados em 1.43s**.

### 4.2. Scorecard da Definition of Done (DoD)

| Pilar | Status | Evidência Observável |
| :--- | :---: | :--- |
| `contract_conformance` | ✅ PASSOU | Tool MCP registrada com schema correto e documentação presente. |
| `test_suite_coverage` | ✅ PASSOU | Suíte de testes automatizados passou com 100% de sucesso (55 testes). |
| `sonarqube_quality_gate` | ✅ PASSOU | Quality Gate SonarQube aprovado: zero falhas críticas ou bloqueantes. |
| `repository_hygiene` | ✅ PASSOU | Repositório limpo sem arquivos temporários espúrios e escopo validado. |
| `session_memory_recorded` | ✅ PASSOU | Descobertas da sessão registradas no WAL `raw_memories.jsonl`. |

### 4.3. Avaliação Rigorosa das 6 Métricas de Eficácia Agêntica

| Métrica | Meta / Critério | Resultado Medido | Avaliação & Evidência |
| :--- | :--- | :---: | :--- |
| **1. Veto Rate dos Validators** | Barramento de código incorreto antes do humano | **0.0 (Tentativa 1)** | O worker utilizou `run_pytest` iterativamente no sandbox e sanitizou o código antes de entregar aos validadores da esteira. |
| **2. Eficácia Anti-Rabbit-Hole do Judge** | Blockers reais / ciclos $\le 1$ | **100% (0 ciclos extras)** | O Judge Panel aprovou a segurança e performance da implementação sem preciosismos cosméticos ou loops infinitos. |
| **3. Sinal/Ruído do HITL (Intervention Signal)** | 100% de paradas justificadas | **100% (1/1)** | A única interrupção ocorrida foi no marco legítimo de governança: o portão `final_task_acceptance` com o DoD Scorecard completo. Zero interrupções por erros triviais de sintaxe. |
| **4. Frugalidade de Contexto** | Redução do prompt via catálogo compacto | **Alta (<=110 chars)** | Catálogo inicial de Deferred Skills carregou sob demanda apenas `preflight_rules` e `mcp_protocol`. Subagentes revisores rodaram em `mode="isolated"`. |
| **5. Taxa de Invalidação de Memória (Anti-Stale)** | WAL append-only sem inchaço de state | **100% Heurísticas Puras** | Foram registradas descobertas arquiteturais reais (sobre `allow_partial_observation` em nível de step vs plan), sem persistir linhas redundantes de sintaxe. |
| **6. Taxa de Convergência de Reparo (MTTR Agêntico)** | Convergência em $\le 2$ tentativas | **1 tentativa** | O worker entregou todos os requisitos e casos de teste na primeira rodada dentro do orçamento de 3. |
