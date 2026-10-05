# Graph Engineering Lab — Agentes de voz

Vocabulário do experimento 05 para distinguir comportamento conversacional, memória e resultados operacionais.

## Linguagem

**Agente de voz**:
Sistema com entrada e saída por fala que pode conduzir uma tarefa usando ferramentas e contexto.
_Evitar_: Usar S2S nativo como sinônimo de qualquer aplicação de voz.

**Cascata de voz**:
Composição que transcreve fala, produz uma resposta textual e sintetiza a fala de saída.
_Evitar_: Modelo S2S nativo.

**S2S nativo**:
Modelo que recebe e gera fala sem exigir uma transcrição textual externa como intermediário obrigatório da resposta.
_Evitar_: Confundir modelo com o sistema completo de tools, memória e transporte.

**Turno de voz**:
Unidade de participação na conversa associada à fala de um participante e à resposta correspondente; pode ser interrompida.
_Evitar_: Sessão.

**Barge-in**:
Entrada de fala do usuário durante a fala do agente, tratada como interrupção da resposta em curso.
_Evitar_: Cancelamento da ação operacional.

**Confirmação de ação**:
Manifestação explícita do usuário vinculada aos parâmetros da alteração que o agente propõe executar.
_Evitar_: Inferir aprovação de uma preferência lembrada.

**Resultado operacional**:
Estado verificável no sistema responsável pela tarefa após uma ação, independente do que o agente disse.
_Evitar_: Resposta do agente como prova de sucesso.

**Memória de sessão**:
Contexto da conversa atual, incluindo informações necessárias para continuar a tarefa.
_Evitar_: Memória entre sessões.

**Memória entre sessões**:
Informação selecionada sobre o usuário, com origem e validade, disponível em conversas futuras.
_Evitar_: Histórico inteiro, base documental, estado atual da agenda.

**Resposta útil**:
Fala que entrega o resultado solicitado ou obtém uma informação necessária para prosseguir.
_Evitar_: Contar um aviso de espera como conclusão da tarefa.

**Piloto real**:
Uso por uma pessoa além do desenvolvedor para realizar uma tarefa e avaliar sua utilidade.
_Evitar_: Fixture sintética como evidência de uso real.
