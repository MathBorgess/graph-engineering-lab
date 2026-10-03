# Proxies nativos do laboratório

## Estrutura

- `codex.py`: `/v1/responses`, porta 8000; credenciais locais do Codex.
- `claude.py`: `/v1/messages`, porta 8001; credenciais locais do Claude Code.
- `client.py`: construtor LangChain para cada provedor.
- `auth.py`: leitura das credenciais existentes, sem renovar tokens.
- `transport.py`: HTTP/SSE compartilhado, sem conversão de tools.
- `tests/`: contratos offline com clientes LangChain reais e upstreams simulados.

## Executar

Na raiz do repositório:

```bash
pip install -r proxy/requirements.txt
python -m proxy.codex
# Em outro terminal:
python -m proxy.claude
```

`python src/subscription_proxy.py --backend codex|claude` continua como launcher.
Use `--port` para alterar a porta. `/health` informa que o servidor está rodando;
não verifica autenticação nem disponibilidade de modelos.

## Usar com LangChain ou Deep Agents

```python
from langchain_core.tools import tool
from proxy.client import create_model

@tool
def add(a: int, b: int) -> int:
    """Soma dois inteiros."""
    return a + b

model = create_model("codex", "gpt-6-sol")
# Ou: create_model("claude", "claude-sonnet-4-6")
llm = model.bind_tools([add])
messages = [{"role": "user", "content": "Some 2 e 3 usando add."}]
reply = llm.invoke(messages)
messages.append(reply)
for call in reply.tool_calls:
    messages.append(add.invoke(call))
if reply.tool_calls:
    final = llm.invoke(messages)
```

Em Deep Agents, passe o modelo sem `bind_tools` a
`create_deep_agent(model=model, tools=[add])`; o agente gerencia o ciclo.
Escolha um modelo concreto aceito pela conta. Rode exemplos com a raiz no caminho
Python, por exemplo `python -m ...`.

O Codex recebe `store=False` e `stream=True` no upstream. Quando o cliente pede
uma resposta sem streaming, o transporte retorna o objeto completo de
`response.completed`; término prematuro retorna 502. Quando o cliente pede
streaming, os eventos seguem sem tradução. Claude mantém o corpo Messages.

## Testar

```bash
python -m unittest discover -s proxy/tests -v
```

Os testes verificam schemas, `tool_choice`, IDs, argumentos e retorno da tool nos
dois provedores, streaming e resposta incompleta. Nenhum teste acessa credenciais
reais ou executa inferência remota. A compatibilidade live com as assinaturas é
**não verificada**. O gate do experimento exige um probe real de ida e volta.

Os scripts históricos de `src/` precisam migrar a construção do modelo para
`create_model()`. Não há `/v1/chat/completions`, aliases de modelo ou lista fictícia
de modelos. O escopo desta alteração é a pasta do proxy e seu launcher.

Referências: [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai),
[ChatAnthropic](https://docs.langchain.com/oss/python/integrations/chat/anthropic).
