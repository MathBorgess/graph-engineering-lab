# 📓 Caderno de Laboratório: Do CLI Loopback ao DeepAgents Graph
## Estudo de Arquitetura Agentica, Poluição de Harness, Engenharia de Proxy e Ontologias em LangGraph

**Autor:** Matheus Borges  
**Repositório:** `graph-engineering-lab`  
**Data:** Setembro de 2026  
**Status:** Validado e em Execução  

---

> **Errata (2026-09-30).** A tese central ("poluição de harness" degrada o agente), os números da §1.2 (cold-start de ~800 ms a 2,5 s, hooks com timeout) e a matriz da §5 (latência, pureza semântica, resistência a alucinações) são **qualitativos ou relatados, não medidos** no repositório. O que o experimento 03 mediu é o **peso** do request do Claude Code (140–359 KB; tools em 70–88% do corpo). Acurácia, foco e latência com e sem harness continuam sem medição.

## 📌 Sumário Executivo

Este documento consolida o ciclo completo de pesquisa, experimentação prática e decisões de arquitetura desenvolvidas no `graph-engineering-lab`. 

O objetivo central foi projetar um ecossistema agentico avançado capaz de:
1. Reutilizar assinaturas ativas de desenvolvedor (Claude Pro/Team e ChatGPT Codex) sem custos avulsos de API por token.
2. Eliminar completamente a **poluição de harness** decorrente de invocações de subprocessos CLI (`claude -p` / `codex exec`).
3. Construir um proxy reverso autenticado (estratégia MITM / token harvesting) que expõe uma interface padronizada OpenAI `/v1/chat/completions`.
4. Analisar criticamente as limitações do padrão **ReAct** monolítico.
5. Desenvolver e orquestrar uma arquitetura **DeepAgent em LangGraph**, dividida em dois agentes profundos especializados:
   - **DeepAgent 1 (Memória & Ontologia):** Guardião do grafo de conhecimento, linked entities, working/episodic memory e reflexão pós-execução.
   - **DeepAgent 2 (Execução & Orquestração de Subagentes):** Receptor de contratos de diretiva, executor determinístico e coordenador de ferramentas especializadas.
6. Fornecer um **Questionário de Autoavaliação e Validação de Conhecimento** em arquitetura agentica.

---

## 1. O Problema do "CLI Loopback" e a Poluição do Harness

### 1.1 A Ideia Inicial (CLI Wrapper)
A intenção original de muitos desenvolvedores ao tentar utilizar suas assinaturas locais é criar um "loopback" via `subprocess`:
```
Agente (LangChain) ---> subprocess.Popen(["claude", "-p", prompt]) ---> CLI stdout
```
Ou equivalentemente:
```
Agente (LangChain) ---> subprocess.Popen(["codex", "exec", prompt]) ---> CLI stdout
```

### 1.2 Por que o Subprocess Harness falha catastroficamente?
Durante nossos experimentos no laboratório e a análise de ferramentas como o `jev-gateway`, identificamos múltiplos fenômenos de **Harness Pollution (Poluição de Harness)**:

```
+-----------------------------------------------------------------------------+
| CLI HARNESS WRAPPER (Node.js / Python CLI)                                  |
|                                                                             |
|  [Injeção Oculta de Contexto]                                               |
|  * Git Worktree Scan ("Repository status: 3 modified files...")            |
|  * Hooks Locais ("SessionEnd hook timeout after 5000ms...")                 |
|  * Warnings de MCP ("Warning: Server filesystem not responding...")         |
|  * System Prompt Hardcoded ("You are Claude Code, an interactive CLI...")   |
|                                                                             |
|  [Vazamento no stdout / stderr]                                             |
|  * Caracteres ANSI / Escape codes de cor e terminal interativo              |
|  * Buffering assíncrono quebrando o formato JSON / Tool Calling             |
|                                                                             |
|  [Overhead Operacional]                                                     |
|  * Cold-start de processo (~800ms a 2.5s por token/geração)                 |
|  * Não há streaming SSE granular de chat completion                         |
+-----------------------------------------------------------------------------+
                                     |
                                     v (Saída Corrompida)
                         [Agente LangChain Quebra]
              ParserError: "Failed to parse tool call or thoughts"
```

1. **Injeção de Metadados Indesejados no Prompt:**
   O CLI não envia apenas o seu prompt: ele varre o diretório corrente (`git status`, arquivos modificados, árvore do projeto) e injeta tudo isso no contexto do modelo. Em um grafo multi-agente, onde cada agente precisa de contexto puro e estrito, essa injeção degrada a capacidade de raciocínio lógico e desperdiça a janela de contexto.
2. **Prompts de Sistema Conflitantes:**
   O CLI injeta instruções de identidade fixas (ex: *"You are an interactive command-line assistant assisting a programmer..."*). Se você está instruindo seu agente a ser um *"Ontology Architect specializing in RDF triples"*, o modelo recebe instruções contraditórias, gerando alucinações e recusa de chamadas de ferramentas.
3. **Erros de Runtime e Hooks:**
   Observamos no laboratório logs reais como `SessionEnd hook timeout` e quebras de subprocessos quando o CLI tentava executar tarefas de limpeza de sessão que não faziam sentido em chamadas de API estocásticas.
4. **Instabilidade de Parsing (ANSI & JSON):**
   Saídas formatadas para terminais humanos (com animações de spinner e cores) quebram os parsers de saída (`PydanticOutputParser`, `ReAct parser`, `JsonOutputKeyToolsParser`).

---

## 2. A Estratégia MITM: Proxy Reverso Autenticado (`subscription_proxy.py`)

Para superar a poluição do harness sem perder o benefício das assinaturas pessoais, foi implementada a estratégia de **Man-In-The-Middle (MITM) / Proxy Reverso Autenticado**:

```
+------------------------------------------------------------------------+
|                          SEU CÓDIGO AGENTICO                          |
|         (LangGraph / LangChain / OpenAI SDK / DeepAgents)              |
+------------------------------------------------------------------------+
                                     |
                     POST /v1/chat/completions (HTTP SSE)
                     API Key: "subscription-proxy"
                                     v
+------------------------------------------------------------------------+
|                 LOCAL SUBSCRIPTION PROXY (Porta 8000)                  |
|                 Arquivo: src/subscription_proxy.py                     |
|                                                                        |
|  [1. Credential Harvesting]                                            |
|  * Anthropic: Lê OAuth Token do macOS Keychain ("Claude Code-credentials")
|  * OpenAI: Lê Access Token de ~/.codex/auth.json                       |
|                                                                        |
|  [2. Transport & Protocol Translation]                                 |
|  * Sem nenhuma inferência local de modelo                              |
|  * OpenAI Format <---> Anthropic Messages API                          |
|  * OpenAI Format <---> ChatGPT Codex Backend API (store: false)        |
|  * Emulação de Headers Oficiais (anthropic-beta, user-agent)           |
+------------------------------------------------------------------------+
              /                                          \
             / (Direct HTTPS)                             \ (Direct HTTPS)
            v                                              v
+---------------------------+                +---------------------------+
|   ANTHROPIC CLOUD API     |                |    CHATGPT CODEX BACKEND  |
| api.anthropic.com/v1/...  |                | chatgpt.com/backend-api/..|
+---------------------------+                +---------------------------+
```

### 2.1 Princípios Fundamentais do Proxy
1. **Zero Model Inference no Proxy:** O proxy não roda nenhum LLM, não usa Ollama, não resume nada. Ele é um roteador HTTP assíncrono de altíssima performance construído em FastAPI e `httpx`.
2. **Coleta Segura de Credenciais:**
   - **Claude Pro/Team:** Extrai as credenciais OAuth diretamente da cadeia de chaves do macOS (`security find-generic-password -s "Claude Code-credentials"`).
   - **OpenAI Codex:** Extrai o token de acesso e `account_id` de `~/.codex/auth.json`.
3. **Preservação de Pureza Semântica:** O prompt que sai do LangGraph chega 100% inalterado aos servidores da Anthropic ou OpenAI, sem que nenhum harness insira git status ou hooks.
4. **Streaming Bidirecional SSE:** Suporte completo a Server-Sent Events (SSE) compatível com a OpenAI API Specification, permitindo visualização de tokens e respostas em tempo real.

---

## 3. O Padrão Monolítico ReAct (`react_agent.py`)

No laboratório, implementamos inicialmente o baseline canônico **ReAct (Reasoning + Acting)**:

```
[Pergunta do Usuário]
        |
        v
+---> [Thought: "Preciso calcular o tamanho da memória..."]
|       |
|       v
|     [Action: calculate("15000 * 128 / (1024 * 1024)")]
|       |
|       v
|     [Observation: "1.8310546875 MB"]
+-------+ (Repete o ciclo até a resposta final)
        |
        v
[Final Answer: "A memória necessária é 1.83 MB."]
```

### 3.1 Vantagens
- Simplicidade conceitual.
- Implementação direta com um único agente e um único loop condicional.

### 3.2 Gargalos Arquiteturais do ReAct
1. **Inchaço de Contexto (Context Bloat):** Todas as iterações anteriores, tool outputs brutos e pensamentos intermediários permanecem acumulados na mesma lista plana de mensagens.
2. **Falta de Memória Persistente:** O agente não aprende entre sessões. Se você rodar uma segunda pergunta, o ReAct parte da estaca zero.
3. **Inexistência de Ontologia:** O ReAct não possui uma estrutura conceitual de domínio. Se ele descobre um fato sobre a infraestrutura, esse fato se perde assim que o loop termina.
4. **Acomodação de Tarefas Conflitantes:** O mesmo modelo precisa ser o planejador estratégico, o leitor de regras de negócio, o operador de ferramentas e o redator final. Isso gera sobrecarga de atenção no LLM.

---

## 4. A Arquitetura DeepAgents com LangGraph (`deep_agents_graph.py`)

Para superar as limitações do ReAct e estudar arquiteturas agenticas de ponta, dividimos o problema em **dois DeepAgents com papéis desacoplados** operando sobre um grafo de estados (`DeepAgentState`).

### 4.1 O que define um "DeepAgent"?
Um DeepAgent diferencia-se de um agente básico por possuir:
1. **Representação Interna de Estado:** Mantém uma ontologia e memória episódica além do histórico de chat.
2. **Separação entre Planejamento Cognitivo e Execução Tática:** Não executa ferramentas impulsivamente; gera primeiro um contrato formal de diretiva.
3. **Capacidade Reflexiva e Aprendizado:** Analisa as evidências colhidas para atualizar o seu grafo de conhecimento antes de responder ao usuário.

### 4.2 Arquitetura dos Dois Agentes

```
                             [START]
                                |
                                v
     +------------------------------------------------------+
     | 🧠 DeepAgent 1: Memory & Ontology Planner            |
     |                                                      |
     | 1. Entity Linking contra o Grafo de Domínio          |
     | 2. Recuperação de Triplas Semânticas Ativas          |
     | 3. Formulação do "Directive Contract"                |
     +------------------------------------------------------+
                                |
                                | (Transfere Estado com Diretiva)
                                v
     +------------------------------------------------------+
     | ⚙️ DeepAgent 2: Execution Agent (Orquestrador)       |
     |                                                      |
     | Executa a diretiva coordenando Subagentes/Tools:     |
     |  * calculate        (Aritmética Segura com AST)      |
     |  * python_eval      (Runtime Python Isolado)         |
     |  * system_inspect   (Sonda de Ambiente e SO)         |
     |  * lab_knowledge    (Base de Conhecimento do Lab)    |
     |                                                      |
     | Produz o Evidence Trace estruturado                  |
     +------------------------------------------------------+
                                |
                                | (Transfere Estado com Evidências)
                                v
     +------------------------------------------------------+
     | 🧠 DeepAgent 1: Memory & Ontology Reflector          |
     |                                                      |
     | 1. Avalia o Evidence Trace da execução               |
     | 2. Extrai Novas Entidades e Triplas Semânticas       |
     | 3. Atualiza a Ontologia (Evolução do Grafo)          |
     | 4. Atualiza a Memória Episódica da Sessão            |
     | 5. Sintetiza a Resposta Final Aterrada (Grounded)    |
     +------------------------------------------------------+
                                |
                                v
                              [END]
```

### 4.3 O Modelo de Dados do Estado (`DeepAgentState`)
```python
class DeepAgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_goal: str
    ontology: Dict[str, Any]          # {"entities": {id: Entity}, "triples": [Triple]}
    memory: Dict[str, Any]            # {"episodic": [...], "working": {...}}
    directive: Dict[str, Any]         # Contrato gerado pelo DeepAgent 1 para o DeepAgent 2
    execution_trace: List[str]        # Log de ações dos subagentes e outputs de tools
    execution_result: Dict[str, Any]  # Resumo estruturado do DeepAgent 2
    reflection: Dict[str, Any]        # Fatos descobertos e delta ontológico
    final_output: str                 # Resposta final apresentada ao usuário
    iteration_count: int
```

### 4.4 Ontologia Inicial e Dinâmica de Aprendizado
O grafo inicia com entidades fundamentais (`LangGraph`, `DeepAgent`, `KnowledgeGraph`, `GraphRAG`, `SubscriptionProxy`).  
Quando uma pergunta envolve, por exemplo, o sistema operacional ou cálculos de memória, o **Reflector** extrai novas entidades (ex: `macOS_Host`, `Darwin_Kernel`, `MemoryAllocationResult`) e estabelece relações como:
```
(SubscriptionProxy) -[runs_on]-> (macOS_Host)
(GraphRAG) -[consumes_memory]-> (MemoryAllocationResult)
```
Em modo interativo, essa ontologia **permanece no estado da sessão**, expandindo continuamente a base de conhecimento do laboratório.

---

## 5. Matriz Comparativa de Arquiteturas

| Dimensão | CLI Loopback Subprocess | Authenticated Reverse Proxy | ReAct Monolítico | LangGraph DeepAgents |
| :--- | :--- | :--- | :--- | :--- |
| **Pureza Semântica** | ❌ Baixa (Harness pollution, git logs) | ✅ 100% Pura (OpenAI/Anthropic APIs) | ⚠️ Moderada (Context incha rápido) | ✅ Alta (Separação de papéis em nós) |
| **Latência por Turno** | ❌ Alta (Cold-start do binário CLI) | ✅ Mínima (Streaming direto via HTTP/SSE) | ⚡ Rápida em passos simples | 🧠 Média (Múltiplas fases cognitivas deliberadas) |
| **Capacidade de Memória** | ❌ Nenhuma | ❌ Apenas transporte stateless | ⚠️ Fraca (Apenas histórico imediato de chat) | ✅ Forte (Memória episódica + Grafo ontológico) |
| **Resistência a Alucinações**| ❌ Baixa (Prompts conflitantes do CLI) | ✅ Depende do modelo cloud | ⚠️ Média (Loop único pode entrar em looping) | ✅ Alta (Reflexão e grounding pós-execução) |
| **Evolução de Domínio** | ❌ Estática | ❌ Estática | ❌ Estática | ✅ Dinâmica (Extração contínua de triplas) |

---

## 6. Questionário de Validação de Conhecimento e Estudo de Arquitetura

Utilize este banco de questões para testar seu domínio técnico sobre os conceitos desenvolvidos neste laboratório.

---

### Módulo A: Transporte de Modelos e Poluição de Harness

#### Questão A1: O que constitui "Harness Pollution" e por que ela afeta negativamente agentes de software?
- **Cenário:** Um engenheiro decide empacotar um agente criando um wrapper em torno de `claude -p "$PROMPT"` ou `codex exec "$PROMPT"`.
- **Critérios de Resposta Esperada:**
  1. Identificar que ferramentas de CLI para humanos injetam automaticamente estado do git, status de hooks, warnings de MCP e instruções de sistema de "assistente de terminal".
  2. Explicar como a injeção desse ruído quebra o raciocínio determinístico do modelo e exaure desnecessariamente a janela de contexto.
  3. Descrever a quebra dos parsers de agentes devido a códigos de escape ANSI e saídas interativas não-estruturadas.
- **Referência no Código:** [`src/subscription_proxy.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/subscription_proxy.py).

#### Questão A2: Qual a diferença arquitetural entre um CLI Loopback e um Reverse-Authenticated MITM Proxy?
- **Critérios de Resposta Esperada:**
  1. O CLI Loopback depende do executável local e sofre com cold-starts e hooks.
  2. O Reverse Proxy atua exclusivamente na camada de rede (HTTP REST/SSE), coletando tokens locais e falando com os endpoints oficiais de nuvem sem nenhuma inferência de modelo intermediária.
  3. O Reverse Proxy emula a especificação canônica da OpenAI (`/v1/chat/completions`), tornando-o drop-in replacement para qualquer SDK (LangChain, LlamaIndex, AutoGen).

#### Questão A3: Como o `subscription_proxy.py` contorna a restrição de ferramentas da Anthropic ao utilizar OAuth Tokens?
- **Critérios de Resposta Esperada:**
  1. Detalhar o uso do header `anthropic-beta: claude-code-20250219`.
  2. Explicar o mapeamento de esquemas de `tools` do formato OpenAI (`{"type": "function", "function": {...}}`) para o formato Anthropic (`{"name": "...", "description": "...", "input_schema": {...}}`).

---

### Módulo B: O Padrão ReAct vs. Padrões Multi-Agente

#### Questão B1: Quais são os 3 maiores pontos de falha do ciclo canônico ReAct (Thought-Action-Observation)?
- **Critérios de Resposta Esperada:**
  1. **Loop Infinito de Ação:** O agente repete a mesma ação com pequenas variações de parâmetros se a observação for inconclusiva.
  2. **Context Window Saturation:** Como o histórico é linear, o acúmulo de outputs brutos de ferramentas satura a janela de contexto.
  3. **Ausência de Camada Epistêmica:** O agente não possui separação entre *o que ele sabe com certeza* (ontologia) e *o que ele observou temporariamente* (scratchpad).
- **Referência no Código:** [`src/react_agent.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/react_agent.py).

#### Questão B2: Por que a parada do ReAct é vulnerável a formatos de Stop Sequence?
- **Critérios de Resposta Esperada:**
  1. O modelo pode gerar `Observation:` por conta própria se não houver stop sequence estrita no LLM.
  2. Se a stop sequence for truncada por variações de espaços em branco (ex: `\nObservation:` vs `Observation:`), o modelo pode alucinar o resultado da ferramenta em vez de pausar para a execução real.

---

### Módulo C: Arquitetura DeepAgents e Engenharia de Grafos de Conhecimento

#### Questão C1: O que é um "Directive Contract" e por que ele é superior a passar a pergunta direta do usuário para o executor?
- **Critérios de Resposta Esperada:**
  1. A pergunta do usuário frequentemente contém ambiguidades, premissas implícitas e falta de direcionamento técnico.
  2. O DeepAgent 1 contextualiza a pergunta com a ontologia existente e traduz o objetivo em um contrato formal contendo: *Subtasks*, *Hypotheses*, *Required Findings* e *Constrained Tools*.
  3. Isso isola o agente executor de distrações conversacionais e estabelece uma meta clara e verificável.
- **Referência no Código:** `memory_plan_node` em [`src/deep_agents_graph.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/deep_agents_graph.py#L225).

#### Questão C2: Como o DeepAgent 1 executa "Entity Linking" antes de planejar?
- **Critérios de Resposta Esperada:**
  1. Varredura do texto da meta contra os identificadores e aliases das entidades cadastradas na ontologia.
  2. Inclusão das definições e atributos das entidades casadas no prompt de planejamento.
  3. Recuperação das triplas conectadas (1-hop neighbors) para enriquecer a base conceitual da instrução.

#### Questão C3: Qual o papel da fase de "Reflection" (`memory_reflect_node`) na consolidação da ontologia?
- **Critérios de Resposta Esperada:**
  1. O Reflector não apenas responde ao usuário; ele analisa criticamente o `execution_trace`.
  2. Extrai novos conceitos identificados durante a execução de ferramentas (ex: características da CPU, métricas de memória) e gera novas entidades formais.
  3. Constrói e valida novas triplas semânticas (`subject`, `predicate`, `object`), persistindo o aprendizado para os próximos ciclos de interação.
- **Referência no Código:** `memory_reflect_node` em [`src/deep_agents_graph.py`](file:///Users/matheusborges/github/graph-engineering-lab/src/deep_agents_graph.py#L380).

---

### Módulo D: Orquestração com LangGraph e Gerenciamento de Estado

#### Questão D1: Como o `DeepAgentState` gerencia a mutabilidade de dados e o acúmulo de mensagens?
- **Critérios de Resposta Esperada:**
  1. Uso do operador `Annotated[List[BaseMessage], add_messages]` para permitir agregação idempotente de mensagens sem sobrescrever o histórico.
  2. Manutenção de dicionários explícitos para `ontology` e `memory`, garantindo que os nós downstream recebam cópias imutáveis ou deltas controlados do estado global.

#### Questão D2: Por que encapsular os nós dentro de uma classe `DeepAgentsWorkflow(llm)` em vez de funções globais soltas?
- **Critérios de Resposta Esperada:**
  1. Resolução limpa de injeção de dependências: o cliente LLM parametrizado e configurado é compartilhado via `self.llm` por todos os métodos de nó.
  2. Evita assinaturas de função conflitantes na compilação do LangGraph (onde argumentos extras como `config` ou `state` fora de padrão geravam erros de runtime).
  3. Facilita testes unitários e instanciação múltipla com diferentes backends (ex: instanciar um workflow com Claude e outro com Codex).

---

## 7. Como Executar e Validar o Ecossistema

### 7.1 Iniciar o Proxy de Assinaturas
```bash
# Terminal 1: Iniciar proxy apontando para ChatGPT Codex ou Claude
.venv/bin/python src/subscription_proxy.py --port 8000 --backend codex
```

### 7.2 Executar o Teste Automatizado do DeepAgents Graph
```bash
# Terminal 2: Executa o ciclo completo (Plan -> Execute -> Reflect -> Graph Evolution)
.venv/bin/python src/deep_agents_graph.py --model codex --test
```

### 7.3 Visualizar o Grafo Mermaid do Fluxo
```bash
.venv/bin/python src/deep_agents_graph.py --mermaid
```

### 7.4 Modo Interativo Studio (com Expansão de Ontologia ao Vivo)
```bash
.venv/bin/python src/deep_agents_graph.py --model codex
```
- Digite perguntas de teste que envolvam cálculos, inspeções do sistema e conceitos de grafos.
- Digite `graph` a qualquer momento para ver o grafo crescendo e aprendendo novas relações.
