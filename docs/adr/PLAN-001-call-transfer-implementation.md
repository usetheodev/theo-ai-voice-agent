# PLAN-001: Implementacao de Transfer Assistida via AMI

**Referencia:** ADR-001-call-control-ami-over-ari.md
**Data:** 2026-02-05
**Status:** Aguardando aprovacao

---

## Prerequisitos

Antes de iniciar: confirmar que a task anterior (AI Transcribe / branch create_ai_transcribe) esta 100% implementada.

---

## Fluxo Tecnico Completo (como o codigo vai funcionar)

```
1. Caller liga para 2000
   Asterisk executa: Set(PJSIP_HEADER(add,X-Caller-Channel)=${CHANNEL})
   Asterisk executa: Dial(PJSIP/2000,60,tT)

2. Media Server (account.py onIncomingCall)
   Extrai header X-Caller-Channel de prm.rdata.wholeMsg
   Cria MyCall com caller_channel="PJSIP/1004-00000001"

3. Conversa normal (ZERO mudanca no fluxo existente)
   StreamingAudioPort captura RTP → AI Agent (STT→LLM→TTS)
   StreamingPlaybackPort reproduz resposta → Caller ouve

4. LLM decide transferir (tool calling)
   LLM retorna texto: "Vou transferir voce para o suporte, aguarde"
   LLM retorna tool_use: transfer_call(target="1001")
   Texto vai para TTS normalmente (caller ouve a frase)

5. Apos streaming completo (websocket.py _process_and_respond_stream)
   AI Agent envia: ResponseEndMessage
   AI Agent detecta pending_tool_call
   AI Agent envia: CallActionMessage(action=TRANSFER, target="1001")

6. Media Server recebe CallActionMessage
   Armazena acao pendente no MyCall
   Aguarda playback_finished (buffer do playback_port esvaziar)
   Caller ouviu a frase completa

7. Media Server executa AMI Redirect
   AMI: Redirect(Channel=PJSIP/1004-00000001, Context=transfer-assistida, Exten=1001)
   Asterisk move caller para [transfer-assistida]
   Canal 2000 recebe DISCONNECT → cleanup normal (onCallState → _stop_conversation → _cleanup)

8. Asterisk executa dialplan [transfer-assistida]
   Playback(please-hold) → MOH → Dial(PJSIP/1001,30,tTm(default))
   Se 1001 atende → conectado
   Se 1001 nao atende → Dial(PJSIP/2000) (fallback para AI Agent, nova sessao)
```

---

## Spike (Validacao antes de implementar)

### SPIKE-01: Confirmar prm.rdata.wholeMsg no pjsua2 Python

**O que:** Verificar se o Python binding do pjsua2 expoe `prm.rdata.wholeMsg` no `onIncomingCall()`.

**Como testar:**
```python
# Em account.py, dentro de onIncomingCall():
try:
    whole_msg = prm.rdata.wholeMsg
    logger.info(f"SIP MSG: {whole_msg[:200]}")
except AttributeError as e:
    logger.error(f"rdata.wholeMsg NAO disponivel: {e}")
```

**Se funcionar:** Prosseguir com parsing de header.
**Se NAO funcionar:** Usar AMI Event subscription como fallback:
- Inscrever no evento AMI `Dial` que contem `Channel` (caller) e `DestChannel` (2000)
- Correlacionar pelo callIdString

**DoD:** Log mostra a mensagem SIP completa com headers, OU fallback definido.

### SPIKE-02: Confirmar AMI Redirect durante Dial() ativo

**O que:** Confirmar que `AMI Redirect` no caller channel durante `Dial(PJSIP/2000)` ativo:
1. Cancela o Dial()
2. Move caller para novo contexto
3. Canal 2000 recebe hangup (DISCONNECT)

**Como testar:**
```bash
# Terminal 1: AMI
telnet asterisk-pabx 5038
Action: Login
Username: media-server
Secret: <senha>

# Terminal 2: Fazer chamada de 1004 para 2000

# Terminal 1: Redirect
Action: Redirect
Channel: PJSIP/1004-00000001
Context: transfer-assistida
Exten: 1001
Priority: 1
```

**DoD:** Caller e redirecionado, canal 2000 recebe DISCONNECT, sem canais orfaos.

---

## Fases de Implementacao

---

## FASE 0: Configuracao Asterisk

### Task 0.1: Criar manager.conf

**Arquivo:** `asterisk/config/manager.conf` (novo)

**O que fazer:**
- Criar arquivo com AMI habilitado na porta 5038
- Criar usuario `media-server` com permissoes `call,system` (read) e `call,originate,system` (write)
- Restringir acesso a rede Docker (172.16.0.0/12)

**DoD:**
- [ ] Arquivo existe em asterisk/config/manager.conf
- [ ] `docker exec asterisk-pabx asterisk -rx "manager show users"` mostra usuario media-server
- [ ] `telnet asterisk-pabx 5038` de dentro da rede Docker funciona
- [ ] Login com credenciais do media-server retorna "Authentication accepted"

---

### Task 0.2: Modificar extensions.conf - Header X-Caller-Channel

**Arquivo:** `asterisk/config/extensions.conf`

**O que fazer:**
- Na extensao 2000 do contexto [interno], adicionar `Set(PJSIP_HEADER(add,X-Caller-Channel)=${CHANNEL})` ANTES do Dial

**Mudanca:**
```
; ANTES (atual):
exten => 2000,1,Dial(PJSIP/2000,60,tT)

; DEPOIS:
exten => 2000,1,Set(PJSIP_HEADER(add,X-Caller-Channel)=${CHANNEL})
 same => n,Dial(PJSIP/2000,60,tT)
```

**DoD:**
- [ ] `dialplan show interno` mostra Set() antes do Dial()
- [ ] `pjsip set logger on` mostra header X-Caller-Channel no INVITE para 2000
- [ ] Chamadas existentes continuam funcionando normalmente (regressao zero)

---

### Task 0.3: Criar contexto [transfer-assistida] no dialplan

**Arquivo:** `asterisk/config/extensions.conf`

**O que fazer:**
- Criar contexto [transfer-assistida] com:
  - Playback de mensagem de espera
  - Dial() para ramal destino com MOH
  - Fallback para AI Agent (ramal 2000) se destino nao atender
  - Hangup em caso de erro

**Codigo:**
```ini
[transfer-assistida]
; Transfer assistida pelo AI Agent via AMI
; Caller chega aqui via AMI Redirect
exten => _X.,1,Answer()
 same => n,Playback(please-hold-while-transferring)
 same => n,Dial(PJSIP/${EXTEN},30,tTm(default))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done:no-answer)
 same => n(done),Hangup()
 same => n(no-answer),Playback(the-party-you-are-calling&is-not-available)
 same => n,Dial(PJSIP/2000,60,tT)
 same => n,Hangup()
```

**DoD:**
- [ ] `dialplan show transfer-assistida` mostra extensoes
- [ ] Contexto nao e acessivel diretamente (seguranca - apenas via AMI Redirect)
- [ ] Sons referenciados existem no Asterisk (ou criar custom se necessario)

---

### Task 0.4: Montar manager.conf no docker-compose

**Arquivo:** `docker-compose.yml`

**O que fazer:**
- Adicionar volume mount de manager.conf no servico asterisk
- Adicionar porta 5038 exposta internamente (NAO para o host, apenas rede Docker)

**DoD:**
- [ ] Container asterisk inicia sem erros com manager.conf
- [ ] `docker exec sip-media-server python -c "import socket; s=socket.socket(); s.connect(('asterisk-pabx',5038)); print(s.recv(100)); s.close()"` recebe banner AMI
- [ ] Servicos existentes continuam funcionando

---

### Task 0.5: Copiar manager.conf no entrypoint

**Arquivo:** `asterisk/scripts/docker-entrypoint.sh`

**O que fazer:**
- Adicionar copia do manager.conf template para /etc/asterisk/ (mesmo padrao do pjsip.conf)

**DoD:**
- [ ] `docker exec asterisk-pabx cat /etc/asterisk/manager.conf` mostra conteudo correto
- [ ] AMI funciona apos restart do container

---

## FASE 1: Protocolo ASP - Mensagem call.action

### Task 1.1: Adicionar enums CallActionType e MessageType.CALL_ACTION

**Arquivo:** `shared/asp_protocol/enums.py`

**O que fazer:**
```python
class CallActionType(str, Enum):
    """Tipos de acao de controle de chamada."""
    TRANSFER = "transfer"
    HANGUP = "hangup"

class MessageType(str, Enum):
    # ... existentes ...
    CALL_ACTION = "call.action"
```

**DoD:**
- [ ] `from asp_protocol.enums import CallActionType, MessageType` funciona
- [ ] `MessageType.CALL_ACTION.value == "call.action"`
- [ ] `CallActionType.TRANSFER.value == "transfer"`

---

### Task 1.2: Criar CallActionMessage dataclass

**Arquivo:** `shared/asp_protocol/messages.py`

**O que fazer:**
- Criar dataclass `CallActionMessage` seguindo o padrao existente (herdar ASPMessage)
- Campos: session_id, action (CallActionType), target (Optional[str]), reason (Optional[str]), timestamp
- Implementar to_dict(), from_dict(), to_json()

**Formato JSON:**
```json
{
    "type": "call.action",
    "session_id": "uuid...",
    "action": "transfer",
    "target": "1001",
    "reason": "Cliente solicitou suporte tecnico",
    "timestamp": "2026-02-05T..."
}
```

**DoD:**
- [ ] CallActionMessage serializa para JSON correto
- [ ] CallActionMessage deserializa de JSON correto
- [ ] Roundtrip: `from_dict(msg.to_dict())` == original
- [ ] `parse_message()` reconhece e cria CallActionMessage corretamente

---

### Task 1.3: Registrar no registry

**Arquivo:** `shared/asp_protocol/messages.py`

**O que fazer:**
- Adicionar `MessageType.CALL_ACTION.value: CallActionMessage` em `_MESSAGE_TYPES`

**DoD:**
- [ ] `parse_message('{"type":"call.action","session_id":"x","action":"transfer","target":"1001"}')` retorna CallActionMessage

---

## FASE 2: Media Server - AMI Client e Call Control

### Task 2.1: Criar modulo AMI Client

**Arquivo:** `media-server/ami/__init__.py` e `media-server/ami/client.py` (novos)

**O que fazer:**
- Implementar AMIClient com:
  - `connect(host, port)`: Abre socket TCP
  - `login(username, secret)`: Autentica no AMI
  - `redirect(channel, context, exten, priority=1)`: Executa AMI Redirect
  - `close()`: Fecha conexao
  - Parsing de respostas AMI (key: value\r\n format)
  - Timeout em operacoes (configuravel)
  - Logging por operacao com ActionID para correlacao
  - Reconexao automatica (backoff exponencial)

**Protocolo AMI (referencia):**
```
→ Action: Login\r\nUsername: x\r\nSecret: y\r\n\r\n
← Response: Success\r\nMessage: Authentication accepted\r\n\r\n

→ Action: Redirect\r\nActionID: uuid\r\nChannel: PJSIP/1004-00000001\r\nContext: transfer-assistida\r\nExten: 1001\r\nPriority: 1\r\n\r\n
← Response: Success\r\nMessage: Redirect successful\r\n\r\n
```

**NAO implementar (YAGNI):**
- Event subscription (nao precisa para v1)
- Originate (futuro)
- Qualquer outro comando

**DoD:**
- [ ] `AMIClient.connect()` conecta ao Asterisk na porta 5038
- [ ] `AMIClient.login()` autentica com sucesso
- [ ] `AMIClient.redirect()` move canal para outro contexto
- [ ] Timeout funciona (nao trava se Asterisk nao responder)
- [ ] Reconexao automatica apos perda de conexao
- [ ] Logs estruturados com ActionID

---

### Task 2.2: Configuracao AMI no config.py

**Arquivo:** `media-server/config.py`

**O que fazer:**
- Adicionar `AMI_CONFIG` com:
  - `host`: env `AMI_HOST` (default: "asterisk-pabx")
  - `port`: env `AMI_PORT` (default: 5038)
  - `username`: env `AMI_USERNAME` (default: "media-server")
  - `secret`: env `AMI_SECRET` (obrigatorio, sem default)
  - `timeout`: env `AMI_TIMEOUT` (default: 5.0)
  - `reconnect_interval`: env `AMI_RECONNECT_INTERVAL` (default: 5.0)

**DoD:**
- [ ] Config carrega de env vars
- [ ] Falha com mensagem clara se AMI_SECRET nao definido
- [ ] Valores default sao corretos para ambiente Docker

---

### Task 2.3: Extrair X-Caller-Channel do SIP INVITE

**Arquivo:** `media-server/sip/account.py`

**Depende de:** SPIKE-01 (validar prm.rdata.wholeMsg)

**O que fazer:**
- No `onIncomingCall()`, extrair header `X-Caller-Channel` do SIP INVITE
- Usar `prm.rdata.wholeMsg` para obter mensagem SIP completa
- Parsear header com string matching simples (nao regex pesado - e callback SIP)
- Passar `caller_channel` como parametro para MyCall

**Codigo (account.py, dentro de onIncomingCall):**
```python
# Extrair caller channel do header SIP
caller_channel = None
try:
    whole_msg = prm.rdata.wholeMsg
    for line in whole_msg.split('\r\n'):
        if line.lower().startswith('x-caller-channel:'):
            caller_channel = line.split(':', 1)[1].strip()
            break
    if caller_channel:
        logger.info(f"[{cid}] Caller channel: {caller_channel}")
    else:
        logger.warning(f"[{cid}] Header X-Caller-Channel nao encontrado")
except Exception as e:
    logger.warning(f"[{cid}] Erro ao extrair caller channel: {e}")
```

**Fallback se SPIKE-01 falhar:**
- Usar AMI Event subscription para capturar evento `Dial` e extrair Channel

**DoD:**
- [ ] Log mostra "Caller channel: PJSIP/1004-00000001" em chamadas recebidas
- [ ] Se header ausente, log de warning (nao erro fatal, chamada continua)
- [ ] Nenhum impacto de performance no callback SIP (parsing < 1ms)

---

### Task 2.4: Armazenar caller_channel no MyCall

**Arquivo:** `media-server/sip/call.py`

**O que fazer:**
- Adicionar parametro `caller_channel: Optional[str] = None` no `__init__` de MyCall
- Armazenar como `self.caller_channel`
- Atualizar chamada em `account.py` para passar o valor

**DoD:**
- [ ] `self.caller_channel` acessivel durante toda a vida da chamada
- [ ] Valor aparece nos logs de inicio da chamada
- [ ] MyCall funciona normalmente se caller_channel for None (backward compat)

---

### Task 2.5: Integrar AMI Client no MediaServer

**Arquivo:** `media-server/media_server.py`

**O que fazer:**
- Criar instancia de AMIClient no startup
- Conectar e logar no AMI durante inicializacao (apos Asterisk ready)
- Disponibilizar ami_client para MyCall (via account ou parametro direto)
- Desconectar no shutdown

**DoD:**
- [ ] Log mostra "AMI conectado" no startup
- [ ] AMI client acessivel a partir de MyCall
- [ ] Shutdown limpo (desconecta AMI)
- [ ] Se AMI nao disponivel, Media Server inicia normalmente (degrade graceful)

---

### Task 2.6: Callback on_call_action no adapter e client

**Arquivos:** `media-server/adapters/ai_agent_adapter.py`, `media-server/ws/client.py`

**O que fazer:**
- Adicionar callback `on_call_action: Optional[Callable[[str, str, Optional[str]], None]]`
  - Parametros: (session_id, action_type, target)
- No WebSocketClient, adicionar handler para `CallActionMessage`
- No adapter, propagar callback como os demais (on_response_start, etc.)

**DoD:**
- [ ] Callback `on_call_action` funciona como os demais callbacks
- [ ] WebSocketClient reconhece e despacha CallActionMessage
- [ ] Adapter propaga callback para o client

---

### Task 2.7: Handler de call.action no MyCall

**Arquivo:** `media-server/sip/call.py`

**O que fazer:**
- Em `_setup_response_callbacks()`, adicionar callback `on_call_action`
- Quando receber call.action tipo TRANSFER:
  1. Armazenar acao pendente: `self.pending_call_action = (action, target)`
  2. Aguardar `playback_finished` event (para caller ouvir a frase completa)
  3. Executar AMI Redirect usando `self.caller_channel`
  4. Log detalhado com session_id, action, target, caller_channel

**Fluxo critico de timing:**
```
ResponseEnd recebido
  → _on_playback_complete thread inicia
  → _wait_playback_finished() aguarda buffer esvaziar

CallActionMessage recebido (pode chegar antes ou depois de playback terminar)
  → Armazena pending_call_action

Playback termina
  → Verifica pending_call_action
  → Se TRANSFER: executa AMI Redirect
  → Se nenhum: resume streaming normalmente
```

**Guards:**
- Se `caller_channel` for None → log error, nao executa transfer
- Se AMI client nao conectado → log error, nao executa transfer
- Se AMI Redirect falha → log error, resume streaming normal (caller continua com AI)

**DoD:**
- [ ] Transfer executa SOMENTE apos playback buffer esvaziar
- [ ] Caller ouve a frase completa antes de ser redirecionado
- [ ] AMI Redirect usa caller_channel correto
- [ ] Se caller_channel ausente, log de erro e chamada continua normalmente
- [ ] Se AMI falha, chamada continua normalmente (degrade graceful)

---

## FASE 3: AI Agent - Tool Calling

### Task 3.1: Definir tools de controle de chamada

**Arquivo:** `ai-agent/tools/__init__.py` e `ai-agent/tools/call_actions.py` (novos)

**O que fazer:**
- Definir constantes com as tool definitions para Anthropic API:

```python
CALL_TOOLS = [
    {
        "name": "transfer_call",
        "description": "Transfere a chamada atual para outro ramal ou departamento. "
                       "Use quando o cliente precisa ser atendido por outra pessoa ou setor. "
                       "Antes de transferir, SEMPRE avise o cliente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Ramal ou departamento destino (ex: '1001', '1002')"
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo da transferencia para log"
                }
            },
            "required": ["target"]
        }
    },
    {
        "name": "end_call",
        "description": "Encerra a chamada atual de forma educada. "
                       "Use quando a conversa chegou ao fim natural.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Motivo do encerramento para log"
                }
            }
        }
    }
]
```

- Definir mapeamento de departamentos (configuravel):
```python
DEPARTMENT_MAP = {
    "suporte": "1001",
    "vendas": "1002",
    "financeiro": "1003",
}
```

**DoD:**
- [ ] CALL_TOOLS importavel e no formato correto da Anthropic API
- [ ] Mapeamento de departamentos configuravel via env (opcional)

---

### Task 3.2: Modificar AnthropicLLM para tool calling

**Arquivo:** `ai-agent/providers/llm.py`

**O que fazer:**
- Adicionar atributo `self.pending_tool_calls: List[Dict] = []` no LLMProvider base
- Adicionar atributo `self.tools: List[Dict] = []` no LLMProvider base
- Em AnthropicLLM.__init__(), carregar tools de CALL_TOOLS
- Modificar `generate_stream()`:
  - Passar `tools=self.tools` no `client.messages.stream()`
  - Apos stream terminar, chamar `stream.get_final_message()`
  - Se `stop_reason == "tool_use"`, extrair tool_use blocks
  - Armazenar em `self.pending_tool_calls`
  - Para tool calls de tipo call action (transfer_call, end_call): NAO fazer agentic loop
    (a acao sera executada pelo sistema, nao pelo LLM)
  - Para tools de informacao (futuro): fazer agentic loop (chamar LLM de novo com tool_result)

**Importante - conversation_history com tool_use:**
- Quando LLM retorna tool_use, o `content` da resposta contem blocks mistos (text + tool_use)
- Para manter o historico correto, salvar a resposta completa (incluindo tool_use blocks)
- Para a PROXIMA chamada, incluir tool_result message
- Para call actions (transfer), a sessao vai terminar, entao o historico nao importa

**DoD:**
- [ ] `generate_stream()` com tools: texto e yielded normalmente (TTS funciona)
- [ ] Apos stream, `self.pending_tool_calls` contem tool calls detectados
- [ ] Se LLM nao chamar nenhuma tool: comportamento identico ao atual
- [ ] `pending_tool_calls` limpo no inicio de cada `generate_stream()`

---

### Task 3.3: Propagar tool calls do pipeline para o WebSocket server

**Arquivos:**
- `ai-agent/pipeline/sentence_pipeline.py`
- `ai-agent/pipeline/conversation.py`
- `ai-agent/server/websocket.py`

**O que fazer:**

1. **SentencePipeline** (`sentence_pipeline.py`):
   - Apos `_produce_sentences()` terminar, verificar `self._llm.pending_tool_calls`
   - Expor como `self.pending_tool_calls` para o consumidor

2. **ConversationPipeline** (`conversation.py`):
   - Em `process_stream_async()`, apos o loop de sentenças, capturar `sentence_pipeline.pending_tool_calls`
   - Expor como `self.pending_tool_calls` (atributo do pipeline)

3. **AIAgentServer** (`websocket.py`):
   - Em `_process_and_respond_stream()`, apos enviar ResponseEndMessage:
   - Verificar `session.pipeline.pending_tool_calls`
   - Para cada tool call de tipo call action:
     - Criar CallActionMessage
     - Enviar via WebSocket

**Codigo (websocket.py, apos linha 532):**
```python
# Apos enviar ResponseEndMessage...

# Verifica tool calls pendentes (call actions)
if hasattr(session.pipeline, 'pending_tool_calls'):
    for tool_call in session.pipeline.pending_tool_calls:
        if tool_call["name"] in ("transfer_call", "end_call"):
            action_msg = CallActionMessage(
                session_id=session.session_id,
                action=CallActionType.TRANSFER if tool_call["name"] == "transfer_call" else CallActionType.HANGUP,
                target=tool_call.get("input", {}).get("target"),
                reason=tool_call.get("input", {}).get("reason")
            )
            await websocket.send(action_msg.to_json())
            logger.info(f"[{session.session_id[:8]}] Call action enviado: {tool_call['name']}")
    session.pipeline.pending_tool_calls = []
```

**DoD:**
- [ ] Quando LLM chama transfer_call, CallActionMessage e enviado apos ResponseEnd
- [ ] Quando LLM NAO chama nenhuma tool, comportamento identico ao atual
- [ ] pending_tool_calls e limpo apos processamento

---

### Task 3.4: Atualizar system prompt para habilitar transfer

**Arquivo:** `ai-agent/config.py`

**O que fazer:**
- Atualizar system prompt padrao para instruir o LLM sobre capacidade de transfer
- O prompt deve incluir:
  - Lista de departamentos disponiveis e ramais
  - Instrucao para SEMPRE avisar o cliente antes de transferir
  - Instrucao para confirmar com o cliente antes de transferir
  - Regras de quando usar transfer vs continuar conversa

**DoD:**
- [ ] System prompt menciona transfer como capacidade
- [ ] LLM consegue decidir quando transferir em conversa natural
- [ ] LLM sempre avisa o caller antes de transferir

---

## FASE 4: Docker e Integracao

### Task 4.1: Variavies de ambiente no docker-compose

**Arquivo:** `docker-compose.yml`

**O que fazer:**
- Adicionar variaveis AMI no servico media-server:
  - `AMI_HOST=asterisk-pabx`
  - `AMI_PORT=5038`
  - `AMI_USERNAME=media-server`
  - `AMI_SECRET=${AMI_SECRET}` (via .env)
- Adicionar `AMI_SECRET` no `.env.example`

**DoD:**
- [ ] Media Server conecta ao AMI no startup
- [ ] Credenciais nao estao hardcoded no docker-compose

---

## FASE 5: Testes de Integracao (Manuais)

### Test 5.1: Conversa normal (regressao zero)

**O que testar:**
1. Ligar de 1004 (softphone) para 2000
2. Conversar normalmente com o AI Agent
3. Desligar

**DoD:**
- [ ] Chamada conecta normalmente
- [ ] STT→LLM→TTS funciona identico ao antes
- [ ] Barge-in funciona
- [ ] Hangup cleanup sem orfaos
- [ ] Log mostra caller_channel extraido corretamente

---

### Test 5.2: Transfer assistida (cenario principal)

**O que testar:**
1. Ligar de 1004 para 2000
2. Pedir ao AI Agent: "Preciso falar com o suporte"
3. Verificar:
   - AI responde "Vou transferir voce para o suporte, aguarde"
   - Caller ouve a frase COMPLETA
   - Caller ouve MOH
   - Ramal 1001 toca
   - Atender 1001
   - Caller e 1001 conversam diretamente

**DoD:**
- [ ] Caller ouve frase de transfer ANTES de MOH (timing correto)
- [ ] MOH toca enquanto 1001 esta tocando
- [ ] Conexao caller↔1001 funciona (audio bidirecional)
- [ ] AI Agent se desconecta limpo (sem canais orfaos)
- [ ] Logs mostram: call.action enviado → AMI Redirect → DISCONNECT no Media Server

---

### Test 5.3: Fallback (destino nao atende)

**O que testar:**
1. Ligar de 1004 para 2000
2. Pedir transfer para ramal que NAO esta registrado (ex: 1003)
3. Verificar:
   - Transfer e tentada
   - Timeout de 30s
   - Caller e reconectado ao AI Agent (nova sessao)

**DoD:**
- [ ] Apos timeout, caller volta ao AI Agent
- [ ] Nova sessao funciona (pode conversar de novo)
- [ ] Sem canais ou bridges orfaos

---

### Test 5.4: Cleanup (robustez)

**O que testar:**
1. Transfer em andamento → caller desliga durante MOH
2. Transfer em andamento → AMI Redirect falha (simular)
3. Chamada sem header X-Caller-Channel → transfer nao executa, chamada continua

**DoD:**
- [ ] Todos os cenarios de falha resultam em cleanup limpo
- [ ] `asterisk -rx "core show channels"` mostra zero canais orfaos
- [ ] `asterisk -rx "bridge show all"` mostra zero bridges orfaas

---

## Riscos e Mitigacoes

| Risco | Probabilidade | Impacto | Mitigacao |
|-------|--------------|---------|-----------|
| `prm.rdata.wholeMsg` nao disponivel no pjsua2 Python | Media | Alto | SPIKE-01. Fallback: AMI Event subscription |
| AMI Redirect nao cancela Dial() corretamente | Baixa | Alto | SPIKE-02. Testar antes de implementar |
| Caller nao ouve frase completa antes de transfer | Media | Media | Aguardar playback_finished antes de AMI Redirect |
| AMI conexao cai durante operacao | Baixa | Baixo | Reconexao automatica. Se falha, chamada continua com AI |
| LLM chama transfer_call com ramal inexistente | Media | Baixo | Dialplan fallback → volta pro AI Agent |
| Contexto da conversa perdido apos fallback | Certo | Baixo | Aceitavel para v1. Sessao persistente e evolucao futura |
| Double cleanup se AMI Redirect + hangup simultaneo | Baixa | Medio | Guards no _stop_conversation (idempotente) |

---

## Ordem de Execucao Recomendada

```
SPIKE-01 e SPIKE-02 (validar premissas)
          |
    FASE 0 (Asterisk config) — pode testar com AMI CLI
          |
    FASE 1 (ASP protocol) — unit testavel isolado
          |
    +-----+-----+
    |           |
  FASE 2      FASE 3
  (Media      (AI Agent
   Server)     tool calling)
    |           |
    +-----+-----+
          |
    FASE 4 (Docker integration)
          |
    FASE 5 (Testes E2E)
```

FASE 2 e FASE 3 podem ser desenvolvidas em paralelo apos FASE 0 e FASE 1.

---

## Arquivos Novos

| Arquivo | Descricao |
|---------|-----------|
| `asterisk/config/manager.conf` | Configuracao AMI |
| `media-server/ami/__init__.py` | Package AMI |
| `media-server/ami/client.py` | Cliente AMI |
| `ai-agent/tools/__init__.py` | Package tools |
| `ai-agent/tools/call_actions.py` | Definicao de tools de chamada |

## Arquivos Modificados

| Arquivo | Mudanca |
|---------|---------|
| `asterisk/config/extensions.conf` | Header X-Caller-Channel + contexto transfer |
| `asterisk/scripts/docker-entrypoint.sh` | Copia manager.conf |
| `docker-compose.yml` | Volume manager.conf + env AMI |
| `shared/asp_protocol/enums.py` | CallActionType + MessageType.CALL_ACTION |
| `shared/asp_protocol/messages.py` | CallActionMessage + registry |
| `media-server/config.py` | AMI_CONFIG |
| `media-server/media_server.py` | AMI client lifecycle |
| `media-server/sip/account.py` | Extrair X-Caller-Channel |
| `media-server/sip/call.py` | caller_channel + on_call_action handler |
| `media-server/adapters/ai_agent_adapter.py` | Callback on_call_action |
| `media-server/ws/client.py` | Handler CallActionMessage |
| `ai-agent/providers/llm.py` | Tool calling em generate_stream() |
| `ai-agent/pipeline/sentence_pipeline.py` | Propagar pending_tool_calls |
| `ai-agent/pipeline/conversation.py` | Propagar pending_tool_calls |
| `ai-agent/server/websocket.py` | Enviar CallActionMessage |
| `ai-agent/config.py` | System prompt com instrucoes de transfer |
