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
| **Memória** | Gravação rígida baseada em `evidence_path` para arquivos | Se algo está ancorado no código, **não** deve virar memória (apenas conceitos/heurísticas). O worker gera `raw_memories`, o validador/HITL destila. Sem exigência de `evidence_path` fixo; se conflitar com código, invalida (`stale`). | Separação tríplice (State vs Git vs Reusable Memory). Ciclo: `raw_memories` -> destilação -> validação contra o código atual -> gravação aprovada. |
| **Validators vs Agents** | Dúvida sobre o que são e por que não estão em `agents/` | Esclarecido: Validators técnicos são funções programáticas determinísticas (testes, linters, schemas) com poder de veto inegociável, não LLMs. Críticas semânticas subjetivas é que cabem a agentes. | `validators/` contém checagens de código puro e políticas estáveis (`pass`, `fail`, `unverified`). |

---

## 2. Memória de Sessão & Dúvidas Registradas

- **Dúvida 1:** *Como os agentes utilizam e compartilham o `State` em grafos?*  
  - *Conceito em alinhamento:* O State é o livro-razão central (quadro-negro) imutável/versionado que transita entre nós. O agente não altera o estado diretamente; ele devolve mensagens/deltas que o redutor do grafo consolida.
- **Dúvida 2:** *Qual a fronteira entre um validador e uma ferramenta (tool)?*  
  - *Conceito em alinhamento:* Tools são concedidas ao agente para ele agir no ambiente. Validators são portões de segurança do controlador (grafo) que julgam o resultado do agente sem que ele possa burlar.

---

## 3. Próximos Passos & Marcos

- [x] Criação da estrutura de pastas em `src/04-agentic-factory/`
- [ ] Modelagem do `FactoryState` e contratos de resultado (`contracts/`)
- [ ] Validação do Proxy e execução do Probe (`probe/`)
- [ ] Implementação da engine de Deferred Skills (`skills/`)
- [ ] Implementação dos Validators programáticos (`validators/`)
- [ ] Implementação do Deep Agent Worker (`agents/` e `tools/`)
- [ ] Orquestração LangGraph com gates HITL (`graph/`)
- [ ] Pipeline de Memória (`memory/`)
- [ ] Tracing e Avaliação MLflow (`eval/`)
