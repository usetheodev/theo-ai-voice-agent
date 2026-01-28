# VoicePipeline - Plano de Implementação Completo

**Versão:** 1.0
**Data:** 2026-01-28
**Autor:** Rafael Augusto Mendes
**Status:** Draft para Aprovação

---

## Sumário Executivo

Este documento apresenta o plano de implementação para resolver todos os gaps identificados nas auditorias do VoicePipeline. O plano está organizado em **4 EPICs**, **8 Sprints**, e **47 MicroTasks**.

### Timeline Estimado

```
Sprint 1-2: Foundation (Bugs Críticos)     [Semanas 1-4]
Sprint 3-4: Observability (Callbacks)       [Semanas 5-8]
Sprint 5-6: Robustness (Retry, Cancel)      [Semanas 9-12]
Sprint 7-8: Features (Memory, MCP)          [Semanas 13-16]
```

### Métricas de Sucesso

| Métrica | Atual | Meta |
|---------|-------|------|
| Testes passando | 580 | 650+ |
| Cobertura de código | ~70% | 85%+ |
| Bugs críticos | 8 | 0 |
| Latency P95 (agent loop) | ~2s | <1.5s |

---

## EPIC 1: Foundation - Correção de Bugs Críticos

**Objetivo:** Corrigir todos os bugs que afetam funcionalidade core
**Duração:** 4 semanas (Sprint 1-2)
**Owner:** Core Team

### Sprint 1: Agent Loop Bugs

**Duração:** 2 semanas
**Objetivo:** Corrigir bugs no AgentLoop e componentes relacionados

---

#### TASK-1.1: Fix `_think_and_act_stream` state propagation

**Descrição:** O método `_think_and_act_stream` modifica o estado internamente mas não propaga corretamente para o caller.

**Evidência:**
```python
# agents/loop.py:327-398
async def _think_and_act_stream(self, state: AgentState) -> AsyncIterator[tuple[str, bool]]:
    state.status = AgentStatus.THINKING  # Modifica in-place
    # ...
    if collected_tool_calls:
        state = self._process_response(state, response)  # ← Reatribui localmente
        state.iteration += 1
    # Estado modificado NÃO é retornado ao caller
```

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 1.1.1 | Refatorar `_think_and_act_stream` para retornar `(token, state)` | 2h | Método retorna tupla com state atualizado |
| 1.1.2 | Atualizar `run_stream` para usar novo retorno | 1h | Loop usa state retornado |
| 1.1.3 | Adicionar testes para state propagation em streaming | 2h | 3+ testes cobrindo edge cases |
| 1.1.4 | Atualizar docstrings com novo comportamento | 30m | Docstrings atualizados |

**ADR-001: State Propagation in Streaming**
```
Status: Proposed
Context: O método _think_and_act_stream é um async generator que modifica
         state internamente, mas generators não podem "retornar" valores
         além do yield.

Decision: Refatorar para yield (token, is_final, state_delta) onde state_delta
          contém apenas as mudanças a serem aplicadas. O caller aplica os deltas.

Alternatives Considered:
  1. Modificar state in-place apenas (atual) - Não funciona com reatribuição
  2. Usar contextvars para propagar state - Muito implícito
  3. Retornar state junto com token - Escolhido

Consequences:
  - API do generator muda (breaking change interno)
  - Mais explícito e testável
  - Performance: overhead mínimo
```

---

#### TASK-1.2: Separar feedback de tokens de resposta

**Descrição:** Quando `ToolFeedbackConfig` está habilitado, as frases de feedback ("Let me check...") são yielded como tokens normais e acabam salvos no memory.

**Evidência:**
```python
# agents/loop.py:236-243
if self.tool_feedback and self.tool_feedback.enabled:
    feedback = self.tool_feedback.get_phrase(tool_name)
    yield feedback  # ← Emitido como token normal

# agents/base.py:336-345
async for token in self._loop.run_stream(user_input, initial_state=state):
    full_response.append(token)  # ← Feedback incluído aqui
    yield token

await self.memory.save_context(user_input, "".join(full_response))
# Memory salva: "Let me check... The time is 14:30"
```

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 1.2.1 | Criar `StreamEvent` dataclass com tipos de evento | 1h | Dataclass com enum de tipos |
| 1.2.2 | Refatorar `run_stream` para yield `StreamEvent` | 2h | Todos os yields usam StreamEvent |
| 1.2.3 | Atualizar `VoiceAgent.astream` para filtrar feedback | 1h | Memory não recebe feedback |
| 1.2.4 | Adicionar `astream_events` para quem quer todos os eventos | 1h | Novo método expõe todos os eventos |
| 1.2.5 | Manter compatibilidade com `astream` antigo | 1h | Método wrapper que extrai apenas tokens |
| 1.2.6 | Testes para separação de eventos | 2h | Testes verificam tipos de evento |

**Implementação Proposta:**
```python
# Novo em agents/events.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any

class StreamEventType(Enum):
    TOKEN = "token"           # Token de resposta do LLM
    FEEDBACK = "feedback"     # Frase de feedback durante tool execution
    TOOL_START = "tool_start" # Início de execução de tool
    TOOL_END = "tool_end"     # Fim de execução de tool
    THINKING = "thinking"     # Início de fase de pensamento
    ERROR = "error"           # Erro ocorrido

@dataclass
class StreamEvent:
    type: StreamEventType
    data: str
    metadata: dict[str, Any] = None

    @property
    def is_response_token(self) -> bool:
        return self.type == StreamEventType.TOKEN
```

---

#### TASK-1.3: Fix input ignorado com initial_state

**Descrição:** Quando `initial_state` é fornecido, o parâmetro `input` é completamente ignorado, causando confusão na API.

**Evidência:**
```python
# agents/loop.py:161-182
async def run(self, input: str, initial_state: Optional[AgentState] = None) -> str:
    if initial_state is not None:
        state = initial_state  # ← input ignorado!
    else:
        state = AgentState(max_iterations=self.max_iterations)
        state.add_user_message(input)
```

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 1.3.1 | Adicionar validação: input deve estar em initial_state | 1h | Warning se input não encontrado |
| 1.3.2 | Documentar comportamento esperado | 30m | Docstring atualizado |
| 1.3.3 | Testes para ambos os cenários | 1h | Testes cobrem edge cases |

---

#### TASK-1.4: Fix Anthropic system message handling

**Descrição:** `AgentMessage.to_anthropic_dict()` converte system messages incorretamente para role="user".

**Evidência:**
```python
# agents/state.py:145-148
def to_anthropic_dict(self) -> dict[str, Any]:
    return {
        "role": self.role if self.role != "system" else "user",  # ← Incorreto
        "content": self.content,
    }
```

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 1.4.1 | Remover conversão system→user | 30m | System messages não convertidas |
| 1.4.2 | Atualizar `AgentState.to_messages()` para filtrar system | 1h | System prompt tratado separadamente |
| 1.4.3 | Documentar que system prompt deve ir no parâmetro dedicado | 30m | Docstring atualizado |
| 1.4.4 | Testes para formato Anthropic | 1h | Testes validam formato correto |

---

### Sprint 2: Tool System Bugs

**Duração:** 2 semanas
**Objetivo:** Corrigir bugs no sistema de tools e executor

---

#### TASK-2.1: Fix Ollama tool arguments format

**Descrição:** Ollama retorna arguments como dict, mas `ToolCall.from_openai()` espera string JSON.

**Evidência:**
```python
# tools/executor.py:43-54
@classmethod
def from_openai(cls, call: dict[str, Any]) -> "ToolCall":
    func = call.get("function", call)
    raw_args = func.get("arguments", "{}")
    if isinstance(raw_args, str):
        arguments = json.loads(raw_args)
    elif isinstance(raw_args, dict):
        arguments = raw_args  # ← Já tratado! Bug foi corrigido?
```

**Verificação necessária:** Confirmar se o código atual já trata este caso.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 2.1.1 | Verificar implementação atual | 30m | Análise do código |
| 2.1.2 | Adicionar testes com ambos os formatos | 1h | Testes passam para dict e string |
| 2.1.3 | Adicionar testes de integração com Ollama | 2h | Teste E2E com Ollama real |

---

#### TASK-2.2: Implementar cancelamento em tool execution

**Descrição:** Tools em execução paralela não podem ser canceladas durante barge-in.

**Evidência:**
```python
# tools/executor.py:265-300 - Já tem cancel_event!
async def execute_many(
    self,
    calls: Sequence[ToolCall],
    parallel: bool = True,
    cancel_event: Optional[asyncio.Event] = None,  # ← Já existe!
) -> list[ToolResult]:
```

**Verificação:** O código já suporta cancelamento! Verificar se está sendo usado.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 2.2.1 | Verificar se cancel_event é propagado do AgentLoop | 1h | Análise de fluxo |
| 2.2.2 | Expor cancel_event na API pública do VoiceAgent | 1h | Método `cancel()` disponível |
| 2.2.3 | Testes de cancelamento | 2h | Testes verificam cancelamento funciona |

---

#### TASK-2.3: Melhorar error handling em execute_many

**Descrição:** Tracebacks são perdidos quando tools falham em execução paralela.

**Evidência:**
```python
# tools/executor.py:291-300
raw_results = await asyncio.gather(*tasks, return_exceptions=True)
return [
    r if isinstance(r, ToolResult) else ToolResult(
        success=False,
        output=None,
        error=f"Tool execution failed: {r}",  # ← Traceback perdido
    )
    for r in raw_results
]
```

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 2.3.1 | Capturar traceback completo em metadata | 1h | Traceback disponível em result.metadata |
| 2.3.2 | Adicionar logging de erro com traceback | 30m | Logger registra erro completo |
| 2.3.3 | Testes para error handling | 1h | Testes verificam traceback preservado |

---

## EPIC 2: Observability - Sistema de Callbacks

**Objetivo:** Implementar sistema de callbacks completo para observabilidade
**Duração:** 4 semanas (Sprint 3-4)
**Owner:** Core Team

### Sprint 3: Callback Infrastructure

**Duração:** 2 semanas
**Objetivo:** Criar infraestrutura base de callbacks

---

#### TASK-3.1: Definir interface de callbacks

**Descrição:** Criar `BaseAgentCallback` seguindo padrões do LangChain.

**Referência LangChain:**
```python
# langchain_core/callbacks/base.py
class BaseCallbackHandler:
    def on_llm_start(self, serialized, prompts, **kwargs): ...
    def on_llm_end(self, response, **kwargs): ...
    def on_tool_start(self, serialized, input_str, **kwargs): ...
    def on_tool_end(self, output, **kwargs): ...
    def on_agent_action(self, action, **kwargs): ...
    def on_agent_finish(self, finish, **kwargs): ...
```

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 3.1.1 | Criar `callbacks/base.py` com `BaseAgentCallback` | 2h | Interface abstrata definida |
| 3.1.2 | Definir eventos: LLM, Tool, Agent | 1h | Todos os eventos documentados |
| 3.1.3 | Criar `AgentCallbackManager` para múltiplos handlers | 2h | Manager funcional |
| 3.1.4 | Testes para callback manager | 2h | Testes cobrem registro e dispatch |

**Implementação Proposta:**
```python
# callbacks/base.py
from abc import ABC
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

@dataclass
class CallbackContext:
    run_id: UUID
    parent_run_id: Optional[UUID] = None
    tags: list[str] = None
    metadata: dict[str, Any] = None

class BaseAgentCallback(ABC):
    """Base class for agent callbacks."""

    # LLM Events
    async def on_llm_start(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when LLM starts generating."""
        pass

    async def on_llm_token(
        self,
        token: str,
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called for each streamed token."""
        pass

    async def on_llm_end(
        self,
        response: "LLMResponse",
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when LLM finishes."""
        pass

    async def on_llm_error(
        self,
        error: Exception,
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when LLM errors."""
        pass

    # Tool Events
    async def on_tool_start(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when tool starts executing."""
        pass

    async def on_tool_end(
        self,
        tool_name: str,
        result: "ToolResult",
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when tool finishes."""
        pass

    async def on_tool_error(
        self,
        tool_name: str,
        error: Exception,
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when tool errors."""
        pass

    # Agent Events
    async def on_agent_start(
        self,
        input: str,
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when agent loop starts."""
        pass

    async def on_agent_action(
        self,
        action: str,
        tool_calls: list["ToolCall"],
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when agent decides to call tools."""
        pass

    async def on_agent_finish(
        self,
        response: str,
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when agent finishes with response."""
        pass

    async def on_agent_error(
        self,
        error: Exception,
        *,
        context: CallbackContext,
        **kwargs,
    ) -> None:
        """Called when agent errors."""
        pass
```

---

#### TASK-3.2: Criar callback handlers built-in

**Descrição:** Implementar handlers comuns: logging, tracing, metrics.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 3.2.1 | `LoggingCallback` - logs estruturados | 2h | Handler funcional com logs JSON |
| 3.2.2 | `TracingCallback` - integração OpenTelemetry | 3h | Spans criados para cada evento |
| 3.2.3 | `MetricsCallback` - métricas Prometheus | 2h | Contadores e histogramas |
| 3.2.4 | `ConsoleCallback` - output para debugging | 1h | Print colorido para terminal |
| 3.2.5 | Testes para cada handler | 3h | Testes unitários completos |

**Implementação `LoggingCallback`:**
```python
# callbacks/logging.py
import logging
import json
from datetime import datetime

class LoggingCallback(BaseAgentCallback):
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger("voice_pipeline.agent")

    async def on_agent_start(self, input: str, *, context: CallbackContext, **kwargs):
        self.logger.info(json.dumps({
            "event": "agent_start",
            "run_id": str(context.run_id),
            "input": input[:100],
            "timestamp": datetime.utcnow().isoformat(),
        }))

    async def on_llm_start(self, messages, tools, *, context: CallbackContext, **kwargs):
        self.logger.debug(json.dumps({
            "event": "llm_start",
            "run_id": str(context.run_id),
            "message_count": len(messages),
            "tool_count": len(tools),
        }))

    async def on_tool_start(self, tool_name, arguments, *, context: CallbackContext, **kwargs):
        self.logger.info(json.dumps({
            "event": "tool_start",
            "run_id": str(context.run_id),
            "tool": tool_name,
            "args": arguments,
        }))

    # ... outros eventos
```

---

### Sprint 4: Callback Integration

**Duração:** 2 semanas
**Objetivo:** Integrar callbacks no AgentLoop e componentes

---

#### TASK-4.1: Integrar callbacks no AgentLoop

**Descrição:** Adicionar emissão de callbacks em todos os pontos relevantes do loop.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 4.1.1 | Adicionar `callbacks` parameter ao `__init__` | 30m | Parâmetro aceito |
| 4.1.2 | Criar `CallbackManager` interno | 1h | Manager inicializado |
| 4.1.3 | Emitir `on_agent_start` no início do loop | 30m | Evento emitido |
| 4.1.4 | Emitir `on_llm_start/end` em `_think_and_act` | 1h | Eventos emitidos |
| 4.1.5 | Emitir `on_tool_start/end` no ToolNode | 1h | Eventos emitidos |
| 4.1.6 | Emitir `on_agent_finish/error` no fim | 30m | Eventos emitidos |
| 4.1.7 | Propagar callbacks via RunnableConfig | 2h | Config propaga callbacks |
| 4.1.8 | Testes de integração | 3h | Testes E2E com callbacks |

**Implementação no AgentLoop:**
```python
# agents/loop.py (modificado)
class AgentLoop:
    def __init__(
        self,
        llm: LLMInterface,
        tools: Optional[list[VoiceTool]] = None,
        callbacks: Optional[list[BaseAgentCallback]] = None,  # NOVO
        # ...
    ):
        self.callback_manager = CallbackManager(callbacks or [])
        # ...

    async def run(self, input: str, initial_state: Optional[AgentState] = None) -> str:
        context = CallbackContext(run_id=uuid4())

        await self.callback_manager.on_agent_start(input, context=context)

        try:
            # ... loop existente ...

            while state.should_continue():
                await self.callback_manager.on_llm_start(
                    messages=state.to_messages(),
                    tools=self.executor.to_openai_tools(),
                    context=context,
                )

                state = await self._think_and_act(state)

                await self.callback_manager.on_llm_end(response, context=context)

                # ... resto do loop ...

            await self.callback_manager.on_agent_finish(
                response=state.final_response,
                context=context,
            )

        except Exception as e:
            await self.callback_manager.on_agent_error(e, context=context)
            raise
```

---

#### TASK-4.2: Integrar callbacks no VoiceAgent

**Descrição:** Expor callbacks na API pública do VoiceAgent.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 4.2.1 | Adicionar `callbacks` ao `VoiceAgent.__init__` | 30m | Parâmetro aceito |
| 4.2.2 | Propagar para `AgentLoop` | 30m | Loop recebe callbacks |
| 4.2.3 | Adicionar ao `VoiceAgentBuilder` | 1h | Builder suporta `.callbacks([...])` |
| 4.2.4 | Documentar uso de callbacks | 1h | Exemplos no docstring |
| 4.2.5 | Testes de uso via VoiceAgent | 2h | Testes E2E |

---

## EPIC 3: Robustness - Retry, Timeout, Cancelamento

**Objetivo:** Tornar o sistema robusto para produção
**Duração:** 4 semanas (Sprint 5-6)
**Owner:** Core Team

### Sprint 5: Retry e Error Handling

**Duração:** 2 semanas
**Objetivo:** Implementar retry inteligente e melhor error handling

---

#### TASK-5.1: Implementar retry para chamadas LLM

**Descrição:** LLM calls devem ter retry com exponential backoff para erros transientes.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 5.1.1 | Definir erros retryable vs fatal | 1h | Lista documentada |
| 5.1.2 | Implementar decorator `@with_retry` | 2h | Decorator funcional |
| 5.1.3 | Aplicar no `_think_and_act` | 1h | LLM calls com retry |
| 5.1.4 | Configurar max attempts e backoff | 1h | Config disponível |
| 5.1.5 | Emitir callback `on_retry` | 30m | Callback emitido |
| 5.1.6 | Testes de retry | 2h | Testes cobrem cenários |

**Implementação Proposta:**
```python
# utils/retry.py
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    RateLimitError,  # Definir
)

def with_llm_retry(max_attempts: int = 3):
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=log_retry_attempt,
    )
```

---

#### TASK-5.2: Implementar circuit breaker

**Descrição:** Quando um provider falha repetidamente, parar de chamar temporariamente.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 5.2.1 | Implementar `CircuitBreaker` class | 2h | Classe funcional |
| 5.2.2 | Integrar em `BaseProvider` | 1h | Providers usam circuit breaker |
| 5.2.3 | Configurar thresholds | 1h | Config disponível |
| 5.2.4 | Emitir callback `on_circuit_open/close` | 1h | Callbacks emitidos |
| 5.2.5 | Testes de circuit breaker | 2h | Testes cobrem estados |

---

### Sprint 6: Cancelamento e Timeout

**Duração:** 2 semanas
**Objetivo:** Permitir cancelamento graceful e timeouts configuráveis

---

#### TASK-6.1: Implementar cancelamento no AgentLoop

**Descrição:** Permitir cancelar o loop de fora durante execução.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 6.1.1 | Adicionar `cancel_event` ao AgentLoop | 1h | Parâmetro aceito |
| 6.1.2 | Verificar cancelamento em cada iteração | 1h | Loop verifica evento |
| 6.1.3 | Propagar para ToolNode | 1h | Tools canceladas |
| 6.1.4 | Retornar estado parcial em cancelamento | 1h | Estado preservado |
| 6.1.5 | Expor `cancel()` no VoiceAgent | 1h | Método público |
| 6.1.6 | Testes de cancelamento | 2h | Testes cobrem cenários |

**Implementação:**
```python
# agents/loop.py (modificado)
class AgentLoop:
    def __init__(self, ..., cancel_event: asyncio.Event = None):
        self._cancel_event = cancel_event or asyncio.Event()

    def cancel(self):
        """Request cancellation of the current run."""
        self._cancel_event.set()

    async def run(self, input: str, ...) -> str:
        self._cancel_event.clear()  # Reset para nova execução

        while state.should_continue():
            if self._cancel_event.is_set():
                state.status = AgentStatus.CANCELLED
                break

            state = await self._think_and_act(state)
            # ...
```

---

#### TASK-6.2: Implementar timeout global

**Descrição:** Limite de tempo total para execução do agent.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 6.2.1 | Adicionar `timeout_seconds` ao AgentLoop | 30m | Parâmetro aceito |
| 6.2.2 | Implementar com `asyncio.wait_for` | 1h | Timeout funcional |
| 6.2.3 | Cleanup em timeout | 1h | Tools canceladas em timeout |
| 6.2.4 | Emitir callback `on_timeout` | 30m | Callback emitido |
| 6.2.5 | Testes de timeout | 1h | Testes cobrem cenário |

---

## EPIC 4: Features - Memory Avançado e MCP

**Objetivo:** Implementar features avançadas identificadas nas auditorias
**Duração:** 4 semanas (Sprint 7-8)
**Owner:** Core Team

### Sprint 7: Memory System Enhancement

**Duração:** 2 semanas
**Objetivo:** Implementar SummaryMemory e melhorias

---

#### TASK-7.1: Implementar ConversationSummaryMemory

**Descrição:** Memória que resume automaticamente quando o buffer fica grande.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 7.1.1 | Criar `ConversationSummaryMemory` class | 3h | Classe funcional |
| 7.1.2 | Implementar lógica de sumarização | 2h | Summary gerado pelo LLM |
| 7.1.3 | Definir threshold para trigger | 1h | Configurável |
| 7.1.4 | Integrar com EpisodicMemory | 2h | Composição funciona |
| 7.1.5 | Testes completos | 2h | Testes cobrem cenários |

**Implementação Proposta:**
```python
# memory/summary.py
class ConversationSummaryMemory(VoiceMemory):
    def __init__(
        self,
        llm: LLMInterface,
        max_messages: int = 20,
        summary_threshold: int = 15,
    ):
        self.llm = llm
        self.max_messages = max_messages
        self.summary_threshold = summary_threshold
        self._messages: list[dict] = []
        self._summary: str = ""

    async def load_context(self, query: str = None) -> MemoryContext:
        return MemoryContext(
            messages=self._messages[-self.max_messages:],
            summary=self._summary,
        )

    async def save_context(self, user_input: str, assistant_output: str) -> None:
        self._messages.append({"role": "user", "content": user_input})
        self._messages.append({"role": "assistant", "content": assistant_output})

        if len(self._messages) > self.summary_threshold:
            await self._summarize_old_messages()

    async def _summarize_old_messages(self) -> None:
        old_messages = self._messages[:-self.max_messages]
        self._messages = self._messages[-self.max_messages:]

        prompt = f"""Summarize this conversation history concisely:

{self._format_messages(old_messages)}

Previous summary: {self._summary}

New summary:"""

        self._summary = await self.llm.generate([
            {"role": "user", "content": prompt}
        ])
```

---

#### TASK-7.2: Adicionar TokenBufferMemory

**Descrição:** Memória limitada por tokens em vez de mensagens.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 7.2.1 | Criar `ConversationTokenBufferMemory` class | 2h | Classe funcional |
| 7.2.2 | Implementar contagem de tokens | 1h | Tokenizer configurável |
| 7.2.3 | Truncar mensagens antigas | 1h | Truncamento funciona |
| 7.2.4 | Testes com diferentes tokenizers | 1h | Testes passam |

---

### Sprint 8: MCP Enhancements

**Duração:** 2 semanas
**Objetivo:** Completar implementação MCP

---

#### TASK-8.1: Implementar WebSocket transport

**Descrição:** Adicionar suporte a WebSocket no MCPClient.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 8.1.1 | Implementar `_connect_websocket` | 3h | Conexão funcional |
| 8.1.2 | Implementar bidirectional messaging | 2h | Send/receive funcionam |
| 8.1.3 | Implementar reconnect automático | 2h | Reconnect com backoff |
| 8.1.4 | Testes com mock WebSocket server | 2h | Testes cobrem cenários |

---

#### TASK-8.2: Implementar MCP Server

**Descrição:** Permitir que VoicePipeline exponha suas tools via MCP.

**MicroTasks:**

| ID | Tarefa | Esforço | DoD |
|----|--------|---------|-----|
| 8.2.1 | Criar `MCPServer` class | 3h | Classe base funcional |
| 8.2.2 | Implementar HTTP transport | 2h | HTTP endpoint funciona |
| 8.2.3 | Implementar SSE transport | 3h | SSE streaming funciona |
| 8.2.4 | Adaptar VoiceTools para MCP | 2h | Conversão automática |
| 8.2.5 | Testes E2E client→server | 2h | Comunicação funciona |

---

## ADRs (Architecture Decision Records)

### ADR-001: State Propagation in Streaming

```markdown
# ADR-001: State Propagation in Streaming

## Status
Proposed

## Context
O método `_think_and_act_stream` é um async generator que modifica state
internamente, mas generators não podem "retornar" valores além do yield.
Isso causa bugs onde modificações no state não são vistas pelo caller.

## Decision
Refatorar para yield `StreamEvent` que inclui referência ao state atualizado.
O caller é responsável por atualizar sua referência local.

## Alternatives Considered
1. **Modificar state in-place apenas** - Não funciona quando há reatribuição
2. **Usar contextvars** - Muito implícito, difícil de debugar
3. **Yield (token, state)** - Overhead de copiar state a cada token
4. **Yield deltas** - Escolhido: yield eventos com mudanças incrementais

## Consequences
- API do generator muda (breaking change interno)
- Mais explícito e testável
- Permite callbacks para cada tipo de evento
- Overhead mínimo: deltas são pequenos
```

### ADR-002: Callback System Design

```markdown
# ADR-002: Callback System Design

## Status
Proposed

## Context
VoicePipeline precisa de observabilidade para produção (logs, tracing, metrics).
LangChain tem um sistema de callbacks maduro que podemos usar como referência.

## Decision
Implementar sistema de callbacks inspirado no LangChain, mas simplificado:
- `BaseAgentCallback` com métodos para cada evento
- `CallbackManager` para gerenciar múltiplos handlers
- Callbacks são async-first (podem fazer I/O)
- Propagação via `RunnableConfig`

## Alternatives Considered
1. **Eventos/Pub-Sub** - Mais flexível mas mais complexo
2. **Decorators** - Menos intrusivo mas difícil de desabilitar
3. **Mixins** - Complexo de gerenciar múltiplos
4. **Callbacks** - Escolhido: padrão conhecido, fácil de usar

## Consequences
- API clara e familiar (similar ao LangChain)
- Handlers podem ser sync ou async
- Permite composição de múltiplos handlers
- Pequeno overhead por callback call
```

### ADR-003: StreamEvent Type System

```markdown
# ADR-003: StreamEvent Type System

## Status
Proposed

## Context
O streaming atual mistura tokens de resposta com feedback verbal.
Callers não conseguem distinguir os tipos de conteúdo.

## Decision
Criar `StreamEvent` dataclass com tipo discriminado:
- TOKEN: tokens da resposta final
- FEEDBACK: frases de feedback durante tool execution
- TOOL_START/END: markers de início/fim de tool
- THINKING: marker de fase de pensamento
- ERROR: erros ocorridos

## Alternatives Considered
1. **Dois streams separados** - Complexo de gerenciar
2. **Prefixos em string** - Frágil, fácil de quebrar
3. **Múltiplos métodos** - API inchada
4. **Typed events** - Escolhido: extensível, typesafe

## Consequences
- API ligeiramente mais complexa
- Necessário wrapper para compatibilidade com `astream` antigo
- Permite extensão futura com novos tipos de evento
- Melhor experiência para consumidores
```

---

## Definition of Done (DoD) Global

### Para cada MicroTask

- [ ] Código implementado
- [ ] Type hints em todos os métodos públicos
- [ ] Docstrings com Args/Returns/Raises
- [ ] Testes unitários passando
- [ ] Sem warnings de linting (ruff)
- [ ] Code review aprovado

### Para cada Task

- [ ] Todas as MicroTasks concluídas
- [ ] Testes de integração passando
- [ ] Documentação atualizada
- [ ] CHANGELOG entry adicionado
- [ ] Performance não degradou (benchmark)

### Para cada Sprint

- [ ] Todas as Tasks concluídas
- [ ] Demo funcional
- [ ] Docs atualizados no README
- [ ] Release notes preparados
- [ ] Retrospectiva realizada

### Para cada EPIC

- [ ] Todos os Sprints concluídos
- [ ] Documentação completa
- [ ] Migration guide (se breaking changes)
- [ ] Anúncio de release
- [ ] Métricas de sucesso atingidas

---

## Cronograma Resumido

```
Semana 1-2:   Sprint 1 - Agent Loop Bugs
Semana 3-4:   Sprint 2 - Tool System Bugs
Semana 5-6:   Sprint 3 - Callback Infrastructure
Semana 7-8:   Sprint 4 - Callback Integration
Semana 9-10:  Sprint 5 - Retry e Error Handling
Semana 11-12: Sprint 6 - Cancelamento e Timeout
Semana 13-14: Sprint 7 - Memory Enhancement
Semana 15-16: Sprint 8 - MCP Enhancements
```

---

## Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Breaking changes em API pública | Alta | Alto | Manter wrappers de compatibilidade |
| Performance degradada com callbacks | Média | Médio | Callbacks são lazy-evaluated |
| Complexidade aumentada | Média | Médio | Documentação clara, exemplos |
| Dependências externas (tenacity, etc) | Baixa | Baixo | Manter opcionais |

---

## Próximos Passos

1. **Revisar este plano** com o time
2. **Priorizar** quais EPICs são mais urgentes
3. **Criar issues** no GitHub para cada Task
4. **Iniciar Sprint 1** após aprovação

---

*Plano criado por Rafael Augusto Mendes*
*Baseado nas auditorias: AUDIT.md, AUDIT_LANGCHAIN_COMPARISON.md, REVIEW_AGENT_LOOP.md*
