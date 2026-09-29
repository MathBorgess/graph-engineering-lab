# captured/ — payloads brutos sanitizados

Requests interceptados pelo `mitm_proxy.py` (Claude Code via `claude -p`, Codex via `codex debug prompt-input` e chamadas JSON-RPC de MCP).

Antes de publicar, os identificadores pessoais foram trocados por placeholders (mesma estrutura, valores removidos):

| Placeholder | O que era |
|---|---|
| `<REDACTED_EMAIL>` | e-mail da conta |
| `<REDACTED_DEVICE_ID>` | `metadata.user_id.device_id` |
| `<REDACTED_ACCOUNT_UUID>` | `metadata.user_id.account_uuid` e sufixos de caminhos `.../synced/<org>_<account>/` |
| `<REDACTED_ORG_UUID>` | id da organização nesses mesmos caminhos |
| `<REDACTED_SESSION_ID>` | `metadata.user_id.session_id` |
| `/Users/<user>` | diretório home local |

O que continua nos arquivos, de propósito, por ser o objeto do estudo: system prompts, schemas de tools e MCPs, listagens de skills e o texto integral dos turnos. Não há tokens, chaves ou credenciais (varredura por `sk-ant-`, `accessToken`, `refreshToken`, `claudeAiOauth`, `ghp_`, `AKIA`, `-----BEGIN`).

Tamanhos: os arquivos são JSON indentado; o request real em JSON compacto é ~25% menor (ex.: 474 KB no arquivo, ~360 KB no corpo).

## Limites das capturas (lidos do código do proxy e dos próprios arquivos)

- **Só requests.** O caminho de streaming do `mitm_proxy.py` repassa a resposta sem gravá-la; por isso não há `usage`, contagem de tokens nem acerto de cache nas capturas. Tudo aqui é estrutura e bytes.
- **Cada request do Claude aparece duas vezes**, primeiro com `stream: true` e depois idêntico com `stream: false`. Consistente com o harness voltando a não-streaming quando o stream via proxy falha, mas a causa não foi investigada; os tempos de latência do relatório incluem esse retorno e não são medidas limpas.
- **Claude foi capturado em modo headless** (`claude -p`, `cc_entrypoint=sdk-cli`, identidade "Claude agent built on the Claude Agent SDK"), não em sessão interativa.
- **Codex:** o proxy só recebeu 19 chamadas JSON-RPC `initialize` (MCP). O prompt do Codex vem de `codex debug prompt-input`, não de tráfego de inferência.
- Reproduzir os números: `python ../analyze_payloads.py`.
