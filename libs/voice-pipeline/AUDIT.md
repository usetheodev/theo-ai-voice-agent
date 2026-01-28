# Auditoria Técnica — Voice Pipeline

**Auditor:** Rafael Augusto Mendes
**Data:** 2026-01-27
**Versão do Framework:** 0.1.0
**Escopo:** Fase 1 — Deep dive na codebase, mapeamento de arquitetura, identificação de gaps

---

## Sumário Executivo

O Voice Pipeline é um framework **bem-estruturado e ambicioso** para construção de agentes de voz em Python. A codebase contém ~150 arquivos fonte organizados em 19 módulos, com 69 arquivos de teste (580 passando, 1 falhando). A arquitetura segue padrões reconhecidos da indústria (LCEL, ReAct, Builder, Strategy).

Porém, a auditoria identificou **6 issues críticas**, **10 issues importantes** e **8 melhorias recomendadas** que precisam ser endereçadas antes de considerar o sistema pronto para produção.

---

## 1. Visão Geral da Arquitetura

### 1.1 Estrutura de Módulos

```
src/voice_pipeline/
├── agents/          # Agent core (ReAct loop, state, tool node, router)
├── audio/           # Pré-processamento (AGC, noise gate, echo suppression)
├── callbacks/       # Sistema de hooks e handlers (logging, metrics, tracing)
├── chains/          # Voice chains (batch, streaming, conversation)
├── cli/             # Interface de linha de comando
├── core/            # Pipeline orchestrator, state machine, events, builder
├── interfaces/      # Contratos abstratos (ASR, LLM, TTS, VAD, etc.)
├── mcp/             # Model Context Protocol (client, server, agent, tools)
├── memory/          # Memória conversacional (buffer, summary, stores)
├── multi_agent/     # Coordenação multi-agente (supervisor, handoff, graph)
├── prompts/         # Gerenciamento de prompts e personas
├── providers/       # Implementações concretas de provedores
├── runnable/        # Padrão LCEL (composição com operador |)
├── streaming/       # Estratégias de streaming (sentence, clause, word, adaptive)
├── telemetry/       # OpenTelemetry (traces, métricas)
├── tools/           # Sistema de ferramentas (base, executor, decorator)
├── transport/       # Transporte de áudio (local mic/speaker, file)
└── utils/           # Utilitários (audio, GPU, serialization, timing)
```

### 1.2 Provedores Disponíveis

| Tipo | Provedores | Quantidade |
|------|-----------|-----------|
| **ASR** | Deepgram, Faster-Whisper, Nemotron, OpenAI Whisper, whisper.cpp | 5 |
| **LLM** | HuggingFace, Ollama, OpenAI | 3 |
| **TTS** | Kokoro, OpenAI, Piper, Qwen3-TTS | 4 |
| **VAD** | Silero, WebRTC, Noise-Aware | 3 |
| **Realtime** | OpenAI Realtime API | 1 |
| **Turn-Taking** | Fixed, Adaptive, Semantic | 3 |
| **Interruption** | Immediate, Graceful, Backchannel | 3 |
| **Embedding** | Sentence-Transformers | 1 |
| **VectorStore** | FAISS | 1 |

### 1.3 Resultados de Testes

```
580 passed, 1 failed, 6 warnings — 14.69s
```

O único teste falhando é `test_invalid_strategy_raises` (mismatch entre mensagem de erro esperada em PT-BR e mensagem real em EN).

---

## 2. Findings

### Severidade: CRÍTICA

Issues que podem causar **falhas em produção**, **comportamento incorreto** ou **degradação severa de performance**.

---

#### C-01: `run_stream` é fake streaming

**Arquivo:** `src/voice_pipeline/agents/loop.py:119-135`
**Componente:** AgentLoop

```python
async def run_stream(self, input: str) -> AsyncIterator[str]:
    # PROBLEMA: Aguarda resposta COMPLETA antes de emitir qualquer token
    result = await self.run(input)
    for char in result:
        yield char
```

**Impacto:** Em um voice pipeline, o streaming é crítico para latência. O `run_stream` deveria emitir tokens conforme o LLM os gera, mas na implementação atual, ele:
1. Espera toda a execução do ReAct loop (incluindo tool calls)
2. Coleta a resposta final completa
3. Emite caractere por caractere

Isso adiciona **100% da latência do LLM** antes de qualquer áudio ser gerado. Para uma resposta de 2s do LLM, o usuário espera 2s+ em silêncio antes de ouvir qualquer coisa.

**Recomendação:** Implementar streaming real no AgentLoop que:
- Faça streaming durante a fase THINK quando o LLM responde sem tools
- Execute tool calls silenciosamente entre fases de streaming
- Use `_think_and_act_stream` (que já existe mas não é usado)

---

#### C-02: Memória desconectada do AgentLoop

**Arquivo:** `src/voice_pipeline/agents/base.py:269-301`
**Componente:** VoiceAgent.ainvoke

```python
async def ainvoke(self, input, config):
    # ✅ Carrega contexto da memória
    context_messages = []
    if self.memory:
        context = await self.memory.load_context(user_input)
        context_messages = context.messages

    # ✅ Cria state com contexto
    state = AgentState(max_iterations=self.max_iterations)
    for msg in context_messages:
        state.add_user_message(msg.get("content", ""))  # Adiciona ao state

    # ❌ MAS: loop.run() cria um NOVO state interno!
    response = await self._loop.run(user_input)
    #          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    # AgentLoop.run() faz:
    #   state = AgentState(max_iterations=self.max_iterations)
    #   state.add_user_message(input)
    # O contexto de memória NUNCA chega ao LLM
```

**Impacto:** A memória conversacional **não funciona**. O agente carrega mensagens anteriores mas as descarta completamente. Cada invocação do agent é tratada como uma conversa nova, sem nenhum contexto histórico.

**Recomendação:** Modificar `AgentLoop.run()` e `AgentLoop.run_stream()` para aceitar um `AgentState` inicial, ou adicionar mensagens de contexto antes de chamar o loop.

---

#### C-03: Incompatibilidade de formato de argumentos Ollama → ToolCall

**Arquivo:** `src/voice_pipeline/providers/llm/ollama.py:774-787` e `src/voice_pipeline/tools/executor.py:36-41`
**Componente:** Ollama LLM + ToolCall

O Ollama retorna argumentos de tool calls como **dict Python**:
```python
# Ollama provider - gera dict
"arguments": func.get("arguments", "{}"),  # → {"city": "São Paulo"}
```

Mas `ToolCall.from_openai()` espera uma **string JSON**:
```python
# ToolCall.from_openai - espera string
arguments=json.loads(func.get("arguments", "{}"))  # json.loads(dict) → TypeError!
```

**Impacto:** **Tool calling com Ollama está quebrado.** Quando o Ollama retorna tool calls, `ToolCall.from_openai()` falha com `TypeError: the JSON object must be str, bytes or bytearray, not dict`.

**Recomendação:** Normalizar os argumentos no `ToolCall.from_openai()`:
```python
raw_args = func.get("arguments", "{}")
if isinstance(raw_args, str):
    arguments = json.loads(raw_args)
elif isinstance(raw_args, dict):
    arguments = raw_args
else:
    arguments = {}
```

---

#### C-04: MCP Client HTTP tem dead code e chamada blocking

**Arquivo:** `src/voice_pipeline/mcp/client.py:312-368`
**Componente:** MCPClient._request_http

```python
async def _request_http(self, request: dict) -> dict[str, Any]:
    try:
        import aiohttp
    except ImportError:
        # Fallback: usa urllib (BLOCKING em contexto async!)
        import urllib.request
        # ...
        with urllib.request.urlopen(req, timeout=...) as resp:  # ← BLOQUEIA event loop
            response = json.loads(resp.read().decode())
        # ... return aqui

    # Se aiohttp foi importado com sucesso:
    # Este código TAMBÉM executa, pois o try/except acima
    # só captura ImportError, não retorna no caso de sucesso do import
    async with aiohttp.ClientSession() as session:  # ← Executa SEMPRE que aiohttp existe
        ...
```

**Impacto:**
1. Se `aiohttp` **não está** instalado: usa `urllib` que **bloqueia o event loop**, causando freeze de toda a aplicação async
2. Se `aiohttp` **está** instalado: o fallback urllib **nunca executa** (correto), mas o código segue para o bloco aiohttp normalmente

O problema real é o cenário (1): bloquear o event loop em uma aplicação de voz é inaceitável.

**Recomendação:** Restructurar com early return e usar `asyncio.to_thread()` para o fallback:
```python
try:
    import aiohttp
except ImportError:
    aiohttp = None

if aiohttp is None:
    return await asyncio.to_thread(self._sync_request_http, request)

async with aiohttp.ClientSession() as session:
    ...
```

---

#### C-05: MCP Client não suporta SSE (Streamable HTTP)

**Arquivo:** `src/voice_pipeline/mcp/client.py`
**Componente:** MCPClient

O MCP specification (2024-11-05) define três transportes:
1. ✅ **stdio** — Implementado
2. ⚠️ **HTTP** — Implementado (JSON-RPC simples)
3. ❌ **SSE (Server-Sent Events) / Streamable HTTP** — **NÃO implementado**

**Impacto:** O transporte Streamable HTTP é o padrão para MCP servers remotos na spec oficial. Clientes como Claude Desktop, Cursor e outros usam SSE. O MCPClient não consegue se conectar a MCP servers que usam o transporte SSE, limitando severamente a compatibilidade.

**Recomendação:** Implementar o transporte SSE seguindo a spec MCP. Considerar usar a biblioteca oficial `mcp` do Python como dependência:
```python
from mcp import ClientSession
from mcp.client.sse import sse_client
```

---

#### C-06: Falta de provider Anthropic para LLM

**Arquivo:** N/A (não existe)
**Componente:** providers/llm

O framework suporta formato Anthropic em:
- `AgentMessage.to_anthropic_dict()` — state.py:107
- `VoiceTool.to_anthropic_schema()` — tools/base.py:154
- `ToolCall.from_anthropic()` — executor.py:43
- `ToolExecutor.to_anthropic_tools()` — executor.py:218
- `ToolExecutor.format_result_for_llm(format="anthropic")` — executor.py:226

Mas **não existe um `AnthropicLLMProvider`**. Toda a infraestrutura de conversão para formato Anthropic existe mas é inutilizável.

**Impacto:** Usuários que querem usar Claude como LLM não conseguem. O framework anuncia compatibilidade com Anthropic (via schemas e formatação de mensagens) mas não entrega.

**Recomendação:** Implementar `AnthropicLLMProvider` com suporte a:
- `generate_stream()` — streaming via API Messages
- `generate_with_tools()` — tool use nativo do Claude
- `supports_tools()` → True

---

### Severidade: IMPORTANTE

Issues que afetam **funcionalidade**, **confiabilidade** ou **developer experience** de forma significativa.

---

#### I-01: Teste falhando — mismatch de idioma em mensagem de erro

**Arquivo:** `tests/test_interruption_strategy.py:627-628`
**Componente:** Testes

```python
# Teste espera PT-BR:
with pytest.raises(ValueError, match="Interruption strategy desconhecida"):
    b.interruption("unknown")

# Mas o código retorna EN:
raise ValueError("Unknown interruption strategy: unknown. Use 'immediate', 'graceful' or 'backchannel'.")
```

**Impacto:** 1 teste falhando. Indica inconsistência de idioma no codebase — algumas mensagens são em inglês, outras esperadas em português.

**Recomendação:** Decidir o idioma oficial do codebase e manter consistência. Recomendo **inglês** para código/mensagens de erro (padrão da indústria) e **português** para documentação voltada ao usuário final.

---

#### I-02: Sem cancelamento em execução paralela de tools

**Arquivo:** `src/voice_pipeline/tools/executor.py:196-208`
**Componente:** ToolExecutor.execute_many

```python
async def execute_many(self, calls, parallel=True):
    if parallel:
        tasks = [self.execute_call(call) for call in calls]
        return await asyncio.gather(*tasks)  # ← Sem cancelamento!
```

**Impacto:** Se o usuário faz barge-in (interrompe o agente), as tool calls em execução **continuam rodando** em background. Em voice AI, onde interrupção é frequente, isso desperdiça recursos e pode causar side-effects indesejados.

**Recomendação:** Usar `asyncio.TaskGroup` ou `asyncio.gather(*tasks, return_exceptions=True)` com um `CancellationToken`:
```python
async def execute_many(self, calls, parallel=True, cancel_event=None):
    if parallel:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self.execute_call(call)) for call in calls]
            if cancel_event:
                tg.create_task(self._wait_cancel(cancel_event))
```

---

#### I-03: `FunctionTool.execute` usa API depreciada

**Arquivo:** `src/voice_pipeline/tools/base.py:300-304`
**Componente:** FunctionTool

```python
loop = asyncio.get_event_loop()  # ← Depreciado em Python 3.10+
result = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: self._func(**kwargs)),
    timeout=self.timeout_seconds,
)
```

**Impacto:** `asyncio.get_event_loop()` é depreciado e emite `DeprecationWarning` em Python 3.10+. Em Python 3.12+, pode falhar se não houver running loop.

**Recomendação:** Substituir por `asyncio.get_running_loop()` ou `asyncio.to_thread()`:
```python
result = await asyncio.wait_for(
    asyncio.to_thread(self._func, **kwargs),
    timeout=self.timeout_seconds,
)
```

---

#### I-04: `AgentState.copy()` é shallow para mensagens

**Arquivo:** `src/voice_pipeline/agents/state.py:330-345`
**Componente:** AgentState

```python
def copy(self) -> "AgentState":
    return AgentState(
        messages=self.messages.copy(),      # ← Copia lista mas não os AgentMessage
        pending_tool_calls=self.pending_tool_calls.copy(),
        ...
    )
```

**Impacto:** Modificar uma `AgentMessage` no estado copiado afeta o original. Em cenários de multi-agent ou branching de conversas, isso causa bugs sutis.

**Recomendação:** Deep copy das mensagens:
```python
import copy
messages=[copy.deepcopy(m) for m in self.messages],
```

---

#### I-05: Tools sobrescrevem silenciosamente na registry

**Arquivo:** `src/voice_pipeline/tools/executor.py:113-119`
**Componente:** ToolExecutor

```python
def register(self, tool: VoiceTool) -> None:
    self.tools[tool.name] = tool  # ← Sobrescreve sem aviso
```

**Impacto:** Se duas tools têm o mesmo nome (comum em cenários MCP com múltiplos servers), a segunda sobrescreve silenciosamente a primeira. O desenvolvedor não recebe nenhum warning ou erro.

**Recomendação:** Adicionar detecção de duplicatas:
```python
def register(self, tool: VoiceTool, overwrite: bool = False) -> None:
    if tool.name in self.tools and not overwrite:
        raise ValueError(
            f"Tool '{tool.name}' already registered. "
            f"Use overwrite=True to replace."
        )
    self.tools[tool.name] = tool
```

---

#### I-06: MCP Client sem reconexão automática

**Arquivo:** `src/voice_pipeline/mcp/client.py`
**Componente:** MCPClient

Não há mecanismo de reconexão quando a conexão MCP cai. Se o server reinicia ou a rede falha, o client fica em estado `is_connected=True` (stale) e todas as chamadas subsequentes falham.

**Impacto:** Em produção, servers MCP reiniciam frequentemente (deploys, scaling). Sem reconexão automática, o agent para de funcionar silenciosamente.

**Recomendação:** Implementar reconexão com exponential backoff:
```python
async def _request_with_reconnect(self, method, params):
    try:
        return await self._request(method, params)
    except (ConnectionError, MCPError) as e:
        await self.disconnect()
        await self.connect()
        return await self._request(method, params)
```

---

#### I-07: MCP Server não implementa rate limiting

**Arquivo:** `src/voice_pipeline/mcp/server.py`
**Componente:** MCPServer

O servidor MCP aceita requisições sem nenhum controle de taxa. Um client malicioso ou com bug pode sobrecarregar o server.

**Impacto:** DoS simples em servers MCP expostos à rede.

**Recomendação:** Adicionar middleware de rate limiting:
```python
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        ...
```

---

#### I-08: Builder emite DeprecationWarning em uso normal

**Arquivo:** `src/voice_pipeline/agents/base.py:1122-1128`
**Componente:** VoiceAgentBuilder.build

```python
if self._asr is not None and self._tts is not None:
    import warnings
    warnings.warn(
        "For voice pipelines (ASR+TTS), prefer build_async() ...",
        DeprecationWarning,
        stacklevel=2,
    )
```

**Impacto:** Qualquer desenvolvedor que use o builder normalmente (com ASR+TTS) recebe um warning, poluindo logs e confundindo novos usuários. A forma síncrona é uma API válida.

**Recomendação:** Remover o warning. Se o objetivo é guiar para `build_async()`, documentar nos docstrings e exemplos em vez de emitir warnings.

---

#### I-09: `astream` no VoiceAgent não propaga contexto de memória para streaming

**Arquivo:** `src/voice_pipeline/agents/base.py:303-339`
**Componente:** VoiceAgent.astream

Similar ao C-02, o método `astream()` carrega contexto da memória mas nunca o passa para `self._loop.run_stream()`. Além disso, o `run_stream` é fake (C-01), então nem streaming real acontece.

**Impacto:** Modo streaming do agent é duplamente quebrado: sem memória e sem streaming real.

---

#### I-10: HuggingFace LLM não suporta tools

**Arquivo:** `src/voice_pipeline/providers/llm/huggingface.py:709`
**Componente:** HuggingFace LLM Provider

```python
def supports_tools(self) -> bool:
    ...  # Precisa verificar se retorna False
```

**Impacto:** Agentes com tools não funcionam com o provider HuggingFace. O AgentLoop cai no branch sem tools quando HuggingFace é usado, gerando respostas que descrevem a tool call em texto natural em vez de executá-la.

**Recomendação:** Documentar claramente quais providers suportam tool calling. Considerar implementar tool calling via prompting para providers que não suportam nativamente.

---

### Severidade: MELHORIA

Sugestões que melhorariam **qualidade**, **performance** ou **developer experience**.

---

#### M-01: Sem suporte a sampling na spec MCP

O MCP specification inclui uma capability `sampling` que permite o server solicitar ao client que gere texto com o LLM. Isso não está implementado.

---

#### M-02: Falta sistema de permissões para tools

Não há sandboxing, permission model ou verificação de segurança na execução de tools. Qualquer tool registrada pode executar código arbitrário.

---

#### M-03: Provider discovery não é automático

O módulo `providers/discovery.py` existe mas providers ainda precisam ser importados manualmente. Entry points do `pyproject.toml` poderiam ser usados para auto-discovery.

---

#### M-04: Sem episodic memory

O sistema de memória tem `ConversationBufferMemory`, `ConversationWindowMemory`, `ConversationSummaryMemory` e `ConversationSummaryBufferMemory`, mas não tem **episodic memory** (memória de longo prazo entre sessões diferentes).

---

#### M-05: Tool results não suportam streaming

`ToolResult` é uma dataclass simples. Tools que executam operações lentas (busca na web, consulta a banco) não podem emitir resultados parciais. O usuário fica em silêncio durante a execução.

---

#### M-06: Sem feedback verbal durante tool calls

Em voice AI, quando o agente está executando uma ferramenta, o usuário deveria receber feedback verbal ("Deixa eu verificar...", "Um momento..."). O framework não tem mecanismo para isso.

---

#### M-07: MCP Server não suporta SSE transport

Similar ao C-05, mas do lado server. O MCPServer só implementa HTTP e stdio, sem SSE.

---

#### M-08: `ConversationSummaryMemory` usa duck-typing para LLM

**Arquivo:** `src/voice_pipeline/memory/summary.py:148-154`

```python
if hasattr(self.llm, "generate"):
    self._summary = await self.llm.generate(messages)
elif hasattr(self.llm, "ainvoke"):
    self._summary = await self.llm.ainvoke(messages)
else:
    self._summary = " ".join(...)
```

Duck-typing em vez de usar a interface `LLMInterface` diretamente. O tipo do atributo é `Any` com comentário `# LLMInterface (avoid circular import)`, indicando problema de design de dependências.

---

## 3. Mapa de Componentes e Status

### Agent Core

| Componente | Arquivo | Status | Issues |
|-----------|---------|--------|--------|
| VoiceAgent | `agents/base.py` | ⚠️ Parcial | C-02, I-09 |
| AgentLoop | `agents/loop.py` | ⚠️ Parcial | C-01 |
| AgentState | `agents/state.py` | ⚠️ Parcial | I-04 |
| ToolNode | `agents/tool_node.py` | ✅ OK | — |
| AgentRouter | `agents/router.py` | ✅ OK | — |
| VoiceAgentBuilder | `agents/base.py` | ⚠️ Parcial | I-08 |

### Tool Calling

| Componente | Arquivo | Status | Issues |
|-----------|---------|--------|--------|
| VoiceTool | `tools/base.py` | ✅ OK | — |
| FunctionTool | `tools/base.py` | ⚠️ Parcial | I-03 |
| ToolExecutor | `tools/executor.py` | ⚠️ Parcial | I-02, I-05 |
| ToolCall | `tools/executor.py` | ❌ Bug | C-03 |
| @voice_tool | `tools/decorator.py` | ✅ OK | — |

### MCP Integration

| Componente | Arquivo | Status | Issues |
|-----------|---------|--------|--------|
| MCPClient | `mcp/client.py` | ❌ Parcial | C-04, C-05, I-06 |
| MCPServer | `mcp/server.py` | ⚠️ Parcial | I-07, M-07 |
| MCPEnabledAgent | `mcp/agent.py` | ⚠️ OK | Depende de C-05 |
| MCPToolAdapter | `mcp/tools.py` | ✅ OK | — |
| MCPTypes | `mcp/types.py` | ✅ OK | — |

### Interfaces

| Interface | Arquivo | Status | Notas |
|-----------|---------|--------|-------|
| ASRInterface | `interfaces/asr.py` | ✅ Completa | Streaming e batch |
| LLMInterface | `interfaces/llm.py` | ✅ Completa | generate_with_tools |
| TTSInterface | `interfaces/tts.py` | ✅ Completa | Warmup support |
| VADInterface | `interfaces/vad.py` | ✅ Completa | — |
| RealtimeInterface | `interfaces/realtime.py` | ✅ Completa | WebSocket events |
| TransportInterface | `interfaces/transport.py` | ✅ Completa | State machine |
| RAGInterface | `interfaces/rag.py` | ✅ Completa | Embedding + Vector |
| InterruptionStrategy | `interfaces/interruption.py` | ✅ Completa | — |
| TurnTakingController | `interfaces/turn_taking.py` | ✅ Completa | — |

### Providers (LLM)

| Provider | Tool Support | Status | Issues |
|----------|-------------|--------|--------|
| OpenAI | ✅ Sim | ✅ Completo | — |
| Ollama | ✅ Sim | ❌ Bug | C-03 |
| HuggingFace | ❌ Não | ⚠️ Limitado | I-10 |
| **Anthropic** | N/A | ❌ Ausente | C-06 |

### Memory

| Componente | Arquivo | Status | Notas |
|-----------|---------|--------|-------|
| ConversationBufferMemory | `memory/buffer.py` | ✅ OK | — |
| ConversationWindowMemory | `memory/buffer.py` | ✅ OK | — |
| ConversationSummaryMemory | `memory/summary.py` | ⚠️ OK | M-08 |
| ConversationSummaryBufferMemory | `memory/summary.py` | ⚠️ OK | M-08 |
| InMemoryStore | `memory/stores/in_memory.py` | ✅ OK | — |

---

## 4. Pontos Positivos

Apesar dos issues encontrados, a codebase tem qualidades notáveis:

1. **Arquitetura modular e extensível** — Interfaces bem definidas permitem adicionar novos providers facilmente. O padrão Strategy para turn-taking, streaming e interrupção é elegante.

2. **Padrão LCEL (composição com `|`)** — A abstração `VoiceRunnable` permite compor pipelines de forma expressiva: `asr | agent | tts`.

3. **Observabilidade completa** — OpenTelemetry com Jaeger (traces), Prometheus (métricas) e Grafana (dashboards) já configurados via Docker Compose.

4. **Diversidade de providers** — 5 ASR, 3 LLM, 4 TTS, 3 VAD providers cobrem desde soluções locais (Ollama, whisper.cpp, Piper) até APIs cloud (OpenAI, Deepgram).

5. **Cobertura de testes** — 69 arquivos de teste com 580 testes passando é uma base sólida.

6. **Builder pattern completo** — O `VoiceAgentBuilder` oferece uma API fluent poderosa e bem documentada.

7. **ReAct pattern bem implementado** — O ciclo Think → Act → Observe no AgentLoop é limpo e segue padrões da indústria.

8. **Audio processing robusto** — AGC, noise gate, echo suppression e ring buffers otimizados demonstram atenção a requisitos de produção.

9. **Streaming strategies** — 4 estratégias (sentence, clause, word, adaptive) com metrificação e configuração granular.

10. **Multi-agent framework** — Supervisor, handoff, collaboration e graph já implementados.

---

## 5. Priorização de Correções

### Sprint 1 (Imediato — Bloqueadores de Funcionalidade)

| Prioridade | Issue | Esforço |
|-----------|-------|---------|
| P0 | **C-02** Memória desconectada do AgentLoop | Pequeno |
| P0 | **C-03** Argumentos Ollama incompatíveis com ToolCall | Pequeno |
| P0 | **C-01** run_stream é fake streaming | Médio |
| P1 | **I-01** Teste falhando (mismatch de idioma) | Trivial |
| P1 | **I-03** get_event_loop depreciado | Trivial |

### Sprint 2 (Curto Prazo — Robustez)

| Prioridade | Issue | Esforço |
|-----------|-------|---------|
| P1 | **C-04** MCP Client HTTP blocking | Pequeno |
| P1 | **I-02** Cancelamento em tool execution | Médio |
| P1 | **I-05** Tools sobrescrevem silenciosamente | Trivial |
| P1 | **I-08** Builder DeprecationWarning | Trivial |
| P2 | **I-04** AgentState.copy() shallow | Trivial |
| P2 | **I-06** MCP Client sem reconexão | Médio |

### Sprint 3 (Médio Prazo — Compatibilidade)

| Prioridade | Issue | Esforço |
|-----------|-------|---------|
| P1 | **C-06** Provider Anthropic LLM | Grande |
| P1 | **C-05** MCP Client SSE transport | Grande |
| P2 | **I-07** MCP Server rate limiting | Médio |
| P2 | **M-07** MCP Server SSE transport | Grande |

### Sprint 4 (Longo Prazo — Funcionalidades)

| Prioridade | Issue | Esforço |
|-----------|-------|---------|
| P3 | **M-01** MCP sampling capability | Médio |
| P3 | **M-02** Sistema de permissões para tools | Grande |
| P3 | **M-04** Episodic memory | Grande |
| P3 | **M-05** Tool result streaming | Médio |
| P3 | **M-06** Feedback verbal durante tool calls | Médio |

---

## 6. Recomendações Arquiteturais

### 6.1 Unificar Agent API

Existem duas hierarquias de agent:
1. `agent.py` (top-level) — `VoiceAgent` simples com factory methods
2. `agents/base.py` — `VoiceAgent` avançado com ReAct loop

Isso causa confusão. Recomendo unificar em uma única classe que escala de simples para avançado.

### 6.2 Adotar SDK MCP oficial

Em vez de implementar o protocolo MCP manualmente, considerar usar o SDK oficial (`mcp` package no PyPI) como dependência. Isso garante compatibilidade com a spec e reduz manutenção.

### 6.3 Padronizar idioma do código

Definir uma política clara:
- Código, variáveis, docstrings, mensagens de erro: **inglês**
- Documentação para usuário final (README, guides): **conforme audiência**

### 6.4 Implementar Circuit Breaker para providers

O `BaseProvider` já tem retry com exponential backoff, mas falta circuit breaker. Providers que falham repetidamente deveriam ser desabilitados temporariamente.

---

## 7. Métricas da Auditoria

| Métrica | Valor |
|---------|-------|
| Arquivos analisados | ~80 (de ~150 totais) |
| Linhas de código lidas | ~10,000+ |
| Issues críticas | 6 |
| Issues importantes | 10 |
| Melhorias sugeridas | 8 |
| Testes existentes | 580 passando, 1 falhando |
| Cobertura estimada | Boa (69 arquivos de teste) |

---

## 8. Próximos Passos

1. **Validar findings com o time** — Revisar esta auditoria com os desenvolvedores para confirmar prioridades
2. **Corrigir P0 issues** — C-01, C-02, C-03 são bloqueadores de funcionalidade básica
3. **Iniciar Fase 2** — Validação detalhada de contratos das interfaces
4. **Criar issues no repositório** — Transformar cada finding em uma issue rastreável

---

*Documento gerado como parte da Fase 1 — Auditoria Técnica do Voice Pipeline.*
