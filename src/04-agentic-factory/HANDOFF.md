# Handoff Briefing — Experimento 04: Agentic Software Factory

**Data:** 2026-10-04  
**Status:** Arquitetura do Grafo, Worker, Validators e DoD implementada e testada; pronta para o teste prático de execução da feature `preflight_plan`.  
**Modelo padrão:** `gpt-6-luna` (via proxy local Codex Responses API na porta 8000).  
**Produto Alvo:** `../mcps-catalog/laya-computer`.

---

## 1. Contexto e Objetivo do Experimento 04

O objetivo deste experimento é validar a tese:
> **"Validators com autoridade real, memória seletiva auditável e portões HITL nos marcos corretos tornam a implementação e o reparo de uma feature determinísticos, auditáveis e imunes a alucinações de conclusão?"**

Ao contrário dos experimentos anteriores (onde grafos simples rodavam com auto-revisão complacente), no Experimento 04:
- O **Deep Agent é o executor especializado (worker)**, confinado ao sandbox do worktree.
- O **LangGraph é o controlador soberano** que governa transições de estado, checkpoints e interrupções HITL.
- Os **Validators programáticos possuem poder real de veto** (o LLM não opina sobre se o teste passou ou se o diff vazou).
- A **Definition of Done (DoD)** e o **DeepAgent Judge** barram conclusões precipitadas e eliminam rabbit-holes de preciosismos infinitos.

---

## 2. Mapa dos Componentes Implementados em `src/04-agentic-factory/`

```text
src/04-agentic-factory/
├── contracts/
│   ├── state.py            # FactoryState: apenas ponteiros leves (WAL .jsonl, diff_path, decisions)
│   ├── findings.py         # Issue (estilo SonarQube), ValidationResult (pass/fail/unverified)
│   └── dod.py              # DoDPillar, DoDReport (5 pilares), ReviewFinding, JudgeVerdict
├── skills/
│   ├── registry.py         # DeferredSkillsRegistry: catálogo compacto (<= 110 chars)
│   │                       # Suporte a model_invoked: true (autônomo) e false (slash commands /SKILL)
│   └── catalog/            # Pacotes de skills: mcp_protocol, preflight_rules, audit_code
├── tools/
│   ├── sandbox_fs.py       # read_file, edit_file, write_file, list_dir com _resolve_safe_path
│   ├── runner.py           # run_pytest confinado com timeout de 120s
│   └── memory_tools.py     # record_raw_memory (WAL append-only) e commit_memory (sensível)
├── validators/
│   ├── scope_validator.py  # Soft Scope: se houver diff inesperado, dispara requires_interrupt (HITL)
│   ├── static_code_analysis.py # SonarQube AST: Bugs (blocker), Vulnerabilidades, Code Smells
│   ├── mcp_contract.py     # Valida registro e schema FastMCP via stdio
│   ├── code_quality.py     # Executa pytest e captura exit_code sanitizando logs
│   └── dod_validator.py    # Audita os 5 pilares da DoD gerando o scorecard para o aceite
├── agents/
│   ├── worker.py           # create_factory_worker: DeepAgent com gpt-6-luna e interrupt_on
│   └── judge.py            # create_deep_agent_judge: Painel com security_reviewer e performance_reviewer
├── graph/
│   ├── gates.py            # scope_review_gate e final_acceptance_gate (HITL com interrupt())
│   ├── nodes.py            # worker_node, validator_node, judge_node, dod_node, memory_distillation
│   └── workflow.py         # StateGraph completo compilado com InMemorySaver
├── EXPERIMENT_REPORT.md    # Diário de bordo com todos os aprendizados e decisões registradas
└── mcp_test_server.py      # Servidor FastMCP usado no teste de consumo de MCP
```

---

## 3. Marcos Técnicos Validados ao Vivo

1. **Correção do Proxy Codex (`proxy/transport.py` e `proxy/codex.py`):**
   - *Itens SSE:* O upstream `/codex/responses` emitia dados em `response.output_item.done` e deixava `response.completed.output` vazio. O proxy agora acumula os itens no streaming e devolve o JSON completo para o LangChain.
   - *Sanitização de System Prompt:* O backend ChatGPT proíbe `role: "system"` em `input`. O proxy move automaticamente para o campo de topo `instructions`.
2. **Consumo Direto de MCP no DeepAgent:**
   - O DeepAgent consumiu ferramentas de um servidor FastMCP via stdio usando `langchain_mcp_adapters.client.MultiServerMCPClient`. O modelo gerou `ToolCall` real e sintetizou o retorno.
3. **Sandbox & WAL:**
   - Tentativas de path traversal foram bloqueadas.
   - O worker carregou skills sob demanda com `load_skill` e gravou descobertas em `raw_memories.jsonl`.
4. **HITL Interrupt-on & Retomada:**
   - A chamada a `commit_memory` foi congelada pelo `HumanInTheLoopMiddleware`, retornou o payload serializável `__interrupt__` e foi retomada com sucesso via `Command(resume={"decisions": [{"type": "approve"}]})`.
5. **SonarQube AST & Soft Scope:**
   - AST identificou 6 regras em código intencionalmente defeituoso (incluindo `eval()`, bare except e credenciais em texto plano).
   - O `scope_validator` não bloqueou imediatamente: sinalizou `requires_interrupt=True` para decisão humana.

---

## 4. Avaliação Crítica da Arquitetura (Pontos Fortes e Riscos)

### Pontos Fortes:
* **Autoridade Real e Veto Programático:** O agente não pode convencer o validador de que um código quebrado passou. Testes e linters são código puro com poder de veto.
* **Economia de Contexto Extrema:** O prompt inicial carrega descrições de apenas 110 caracteres. Subagentes revisores rodam em `mode="isolated"`, preservando a janela de atenção do modelo principal.
* **Arquitetura WAL para Memória:** Separar o State volátil do LangGraph do log físico `.jsonl` em disco protege contra inchaço de serialização e perda de descobertas em falhas catastróficas.
* **Duplo Nível de HITL:** Interrupção cirúrgica de ferramenta (`interrupt_on` no worker) vs Interrupção de marco de governança (`interrupt()` no LangGraph).

### Riscos e Pontos de Atenção para o Teste Prático:
1. **Fallback de JSON no Judge:** Se o LLM emitir texto conversacional ao invés do JSON estruturado esperado em `JudgeVerdict`, o parser atual usa um fallback defensivo que aprova como `advisory`. No teste real, monitorar se o modelo segue o schema estritamente.
2. **Setup do Git Worktree:** O `laya-computer` possui dependências gerenciadas por `uv`. O teste prático deve assegurar que o worktree isolado execute `uv run --project laya-computer pytest` sem interferir na branch principal.
3. **Invalidação de Memórias Antigas:** A destilação precisa validar se uma regra aprendida no passado contradiz o código atual antes de torná-la `active`.

---

## 5. Proposta de Métricas de Sucesso para Estudo da Eficácia

Para que o operador e o próximo agente possam medir com rigor científico como cada nó e decisão técnica melhorou ou viabilizou a entrega, propomos as seguintes **6 métricas de eficácia agêntica**:

| Métrica | O que Mede? | Como Calcular? | Evidência de Sucesso |
| :--- | :--- | :--- | :--- |
| **1. Veto Rate dos Validators (Autonomia Real)** | Capacidade dos validadores programáticos de barrar alucinações de conclusão do LLM. | $\frac{\text{Tentativas com Falha Detectada}}{\text{Total de Tentativas do Worker}}$ | O worker errou na 1ª tentativa e foi obrigado a reparar antes de chegar ao humano. |
| **2. Eficácia Anti-Rabbit-Hole do Judge** | Capacidade do Judge de criticar apenas o que importa sem travar a esteira em preciosismo. | $\frac{\text{Blockers Reais Identificados}}{\text{Total de Apontamentos do Judge}}$ e contagem de ciclos (deve ser $\le 1$). | Zero ciclos infinitos; sugestões cosméticas ficaram em `advisory` sem bloquear. |
| **3. Sinal/Ruído do HITL (Intervention Signal)** | Proporção de paradas humanas que foram para decisões de risco reais vs falsos alertas. | $\frac{\text{Interrupções Justificadas (Risco/Escopo/Aceite)}}{\text{Total de Interrupções Disparadas}}$ | $100\%$ das interrupções foram em marcos reais (`scope_drift` ou `final_acceptance`). Zero interrupções por erros triviais de sintaxe. |
| **4. Frugalidade de Contexto (Token Efficiency)** | Economia de tokens proporcionada pelo catálogo compacto (110 chars) e subagentes isolados. | Comparar tokens da sessão com catálogo deferido vs sessão que injetaria todas as skills/docs no prompt inicial. | Redução estimada $\ge 40\%$ no consumo acumulado de tokens de entrada. |
| **5. Taxa de Invalidação de Memória (Anti-Stale)** | Capacidade do sistema de descartar memórias que contradizem o código atual. | $\frac{\text{Memórias marcadas como Stale/Rejeitadas}}{\text{Total de Candidatos no WAL}}$ | Candidatos óbvios de código foram descartados; apenas conceitos e heurísticas viraram memória. |
| **6. Taxa de Convergência de Reparo (MTTR Agêntico)** | Número médio de tentativas que o worker leva para corrigir um defeito apontado pelos validadores. | $\frac{\text{Tentativas Totais}}{\text{Features Entregues com DoD Verde}}$ | Convergência em $\le 2$ tentativas dentro do orçamento de 3. |

---

## 6. Próximo Passo Imediato (Comando de Retomada)

O próximo agente deve:
1. Criar o worktree isolado do `../mcps-catalog/laya-computer`.
2. Instanciar o grafo compilado (`graph/workflow.py`).
3. Disparar a execução da feature `preflight_plan` orientada pelos casos de aceitação da Seção 2 da spec.
4. Coletar os traces e preencher as 6 métricas de sucesso acima.

### Prompt de Retomada (Copy & Paste para o Novo Agente):

```markdown
/handoff resume
Contexto: Experimento 04 concluído em sua fase de scaffold e testes de contratos.
Consulte: src/04-agentic-factory/HANDOFF.md e src/04-agentic-factory/EXPERIMENT_REPORT.md.
Objetivo: Executar o teste prático de ponta a ponta da feature `preflight_plan` no checkout isolado de `laya-computer` usando o grafo compilado em `src/04-agentic-factory/graph/workflow.py`.
Diretrizes: Conduzir a execução passo a passo, monitorando as 6 métricas de sucesso (Veto Rate, Anti-Rabbit-Hole, Sinal HITL, Frugalidade, Anti-Stale e Convergência).
```
