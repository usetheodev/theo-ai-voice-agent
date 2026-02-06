"""
LLM (Large Language Model) - Processa texto e gera respostas

Providers suportados:
- Anthropic Claude (API cloud)
- OpenAI GPT (API cloud)
- Local (Docker Model Runner, vLLM, Ollama - OpenAI-compatible)

Todos os providers suportam streaming para reduzir latência.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Generator, Optional

from config import LLM_CONFIG

logger = logging.getLogger("ai-agent.llm")


def _load_tools_openai() -> List[Dict]:
    """Carrega CALL_TOOLS no formato OpenAI (formato canonico)."""
    try:
        from tools.call_actions import CALL_TOOLS
        return CALL_TOOLS
    except ImportError:
        logger.debug("Tools de chamada nao disponiveis")
        return []


def _convert_tools_to_anthropic(tools: List[Dict]) -> List[Dict]:
    """Converte tools do formato OpenAI para formato Anthropic API."""
    anthropic_tools = []
    for tool in tools:
        fn = tool.get("function", {})
        anthropic_tools.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return anthropic_tools


def _extract_openai_tool_calls(message) -> List[Dict]:
    """Extrai tool calls de uma resposta OpenAI (batch) para formato interno."""
    tool_calls = []
    if not message.tool_calls:
        return tool_calls
    for tc in message.tool_calls:
        try:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            args = {}
            logger.warning(f"Falha ao parsear tool call arguments: {tc.function.arguments}")
        tool_calls.append({
            "id": tc.id,
            "name": tc.function.name,
            "input": args,
        })
    return tool_calls


class LLMProvider(ABC):
    """Interface base para provedores de LLM"""

    def __init__(self):
        self.conversation_history: List[Dict[str, str]] = []
        self.system_prompt = LLM_CONFIG["system_prompt"]
        self.pending_tool_calls: List[Dict] = []
        # Cache tools at init (avoids re-loading on every request)
        self._tools_openai: List[Dict] = _load_tools_openai()

    @abstractmethod
    def generate(self, user_message: str) -> str:
        """Gera resposta para mensagem do usuário (modo batch)"""
        pass

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """
        Gera resposta em streaming (modo incremental).
        Yield tokens/chunks conforme são gerados.

        Override este método para suportar streaming real.
        Implementação default faz fallback para generate().
        """
        response = self.generate(user_message)
        yield response

    def generate_sentences(self, user_message: str) -> Generator[str, None, None]:
        """
        Gera resposta e yield frases completas.
        Útil para TTS streaming - sintetiza frase por frase.
        """
        buffer = ""
        sentence_endings = re.compile(r'[.!?]+\s*')
        sentence_count = 0

        for chunk in self.generate_stream(user_message):
            buffer += chunk

            # Procura por frases completas
            while True:
                match = sentence_endings.search(buffer)
                if match:
                    # Encontrou fim de frase
                    sentence = buffer[:match.end()].strip()
                    buffer = buffer[match.end():]

                    if sentence:
                        sentence_count += 1
                        logger.debug(f" Sentença {sentence_count}: {sentence}")
                        yield sentence
                else:
                    break

        # Yield resto do buffer
        if buffer.strip():
            sentence_count += 1
            logger.debug(f" Sentença final {sentence_count}: {buffer.strip()}")
            yield buffer.strip()

        logger.info(f" Total sentenças geradas: {sentence_count}")

    def reset_conversation(self):
        """Limpa histórico da conversa"""
        self.conversation_history = []
        logger.info(" Histórico de conversa limpo")

    @property
    def supports_streaming(self) -> bool:
        """Indica se o provedor suporta streaming real"""
        return False


class AnthropicLLM(LLMProvider):
    """LLM usando Anthropic Claude com suporte a streaming"""

    def __init__(self):
        super().__init__()
        self.client = None
        self._tools_anthropic = _convert_tools_to_anthropic(self._tools_openai) if self._tools_openai else []
        self._init_client()

    def _init_client(self):
        """Inicializa cliente Anthropic"""
        try:
            import anthropic
            api_key = LLM_CONFIG["anthropic_api_key"]
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY não configurada")
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info(" Cliente Anthropic inicializado (streaming habilitado)")
        except ImportError:
            logger.error("Anthropic não instalado. Execute: pip install anthropic")
            raise

    @property
    def supports_streaming(self) -> bool:
        return True

    def _extract_tool_calls(self, response) -> None:
        """Extrai tool calls de resposta Anthropic e popula self.pending_tool_calls."""
        if response.stop_reason == "tool_use":
            for block in response.content:
                if block.type == "tool_use":
                    self.pending_tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    logger.info(f"Tool call detectado: {block.name}({block.input})")

    def _save_response_to_history(self, response, text_content: str) -> None:
        """Salva resposta Anthropic no historico com tool_result sintetico se necessario.

        CRITICO: A API Anthropic exige que apos uma mensagem assistant com tool_use,
        a proxima mensagem seja user com tool_result. Sem isso, a proxima chamada
        retorna erro 400. Como as tools sao executadas fora do LLM (pelo media-server),
        adicionamos um tool_result sintetico para manter o historico valido.
        """
        if response.stop_reason == "tool_use":
            content_blocks = []
            for block in response.content:
                if block.type == "text":
                    content_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    content_blocks.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            self.conversation_history.append({
                "role": "assistant",
                "content": content_blocks
            })
            # Synthetic tool_result para manter historico valido
            if self.pending_tool_calls:
                tool_results = [{
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": "Action queued for execution.",
                } for tc in self.pending_tool_calls]
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results,
                })
        else:
            self.conversation_history.append({
                "role": "assistant",
                "content": text_content
            })

    def generate(self, user_message: str) -> str:
        """Gera resposta usando Claude (modo batch) com suporte a tool calling."""
        if not self.client:
            return "Desculpe, nao consegui processar sua mensagem."

        self.pending_tool_calls = []

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            request_kwargs = {
                "model": LLM_CONFIG["model"],
                "max_tokens": LLM_CONFIG["max_tokens"],
                "system": self.system_prompt,
                "messages": self.conversation_history,
                "timeout": LLM_CONFIG["timeout"],
            }
            if self._tools_anthropic:
                request_kwargs["tools"] = self._tools_anthropic

            response = self.client.messages.create(**request_kwargs)

            # Extract text
            assistant_message = ""
            for block in response.content:
                if block.type == "text":
                    assistant_message += block.text

            self._extract_tool_calls(response)
            self._save_response_to_history(response, assistant_message)

            logger.info(f" LLM: '{assistant_message}'")
            if self.pending_tool_calls:
                logger.info(f"Tool calls pendentes (batch): {len(self.pending_tool_calls)}")

            return assistant_message

        except Exception as e:
            logger.error(f"Erro no LLM Anthropic: {e}")
            return "Desculpe, tive um problema ao processar sua mensagem."

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """Gera resposta usando Claude com streaming e suporte a tool calling."""
        if not self.client:
            yield "Desculpe, nao consegui processar sua mensagem."
            return

        self.pending_tool_calls = []

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            full_response = ""

            stream_kwargs = {
                "model": LLM_CONFIG["model"],
                "max_tokens": LLM_CONFIG["max_tokens"],
                "system": self.system_prompt,
                "messages": self.conversation_history,
            }
            if self._tools_anthropic:
                stream_kwargs["tools"] = self._tools_anthropic

            with self.client.messages.stream(**stream_kwargs) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

                final_message = stream.get_final_message()
                self._extract_tool_calls(final_message)
                self._save_response_to_history(final_message, full_response)

            logger.info(f" LLM (stream completo): '{full_response}'")
            if self.pending_tool_calls:
                logger.info(f"Tool calls pendentes: {len(self.pending_tool_calls)}")

        except Exception as e:
            logger.error(f"Erro no LLM Anthropic streaming: {e}")
            yield "Desculpe, tive um problema ao processar sua mensagem."


class OpenAILLM(LLMProvider):
    """LLM usando OpenAI GPT com suporte a streaming"""

    def __init__(self):
        super().__init__()
        self.client = None
        self._init_client()

    def _init_client(self):
        """Inicializa cliente OpenAI"""
        try:
            from openai import OpenAI
            api_key = LLM_CONFIG["openai_api_key"]
            if not api_key:
                raise ValueError("OPENAI_API_KEY não configurada")
            self.client = OpenAI(api_key=api_key)
            logger.info(" Cliente OpenAI inicializado para LLM (streaming habilitado)")
        except ImportError:
            logger.error("OpenAI não instalado. Execute: pip install openai")
            raise

    @property
    def supports_streaming(self) -> bool:
        return True

    def _save_openai_tool_history(self, assistant_message: str) -> None:
        """Salva resposta OpenAI no historico com tool_calls e tool results sinteticos."""
        if self.pending_tool_calls:
            tool_calls_history = [{
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["input"]),
                }
            } for tc in self.pending_tool_calls]
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message or None,
                "tool_calls": tool_calls_history,
            })
            # Synthetic tool results para manter historico valido
            for tc in self.pending_tool_calls:
                self.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "Action queued for execution.",
                })
        else:
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message,
            })

    def generate(self, user_message: str) -> str:
        """Gera resposta usando GPT (modo batch) com suporte a tool calling."""
        if not self.client:
            return "Desculpe, não consegui processar sua mensagem."

        self.pending_tool_calls = []

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)

            request_kwargs = {
                "model": LLM_CONFIG.get("openai_model", "gpt-3.5-turbo"),
                "max_tokens": LLM_CONFIG["max_tokens"],
                "temperature": LLM_CONFIG["temperature"],
                "messages": messages,
                "timeout": LLM_CONFIG["timeout"],
            }
            if self._tools_openai:
                request_kwargs["tools"] = self._tools_openai

            response = self.client.chat.completions.create(**request_kwargs)
            message = response.choices[0].message
            assistant_message = message.content or ""

            # Extract tool calls
            self.pending_tool_calls = _extract_openai_tool_calls(message)
            for tc in self.pending_tool_calls:
                logger.info(f"Tool call detectado (batch): {tc['name']}({tc['input']})")

            self._save_openai_tool_history(assistant_message)

            logger.info(f" LLM: '{assistant_message}'")
            if self.pending_tool_calls:
                logger.info(f"Tool calls pendentes (batch): {len(self.pending_tool_calls)}")
            return assistant_message

        except Exception as e:
            logger.error(f"Erro no LLM OpenAI: {e}")
            return "Desculpe, tive um problema ao processar sua mensagem."

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """Gera resposta usando GPT com streaming e suporte a tool calling."""
        if not self.client:
            yield "Desculpe, não consegui processar sua mensagem."
            return

        self.pending_tool_calls = []

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)

            full_response = ""

            stream_kwargs = {
                "model": LLM_CONFIG.get("openai_model", "gpt-3.5-turbo"),
                "max_tokens": LLM_CONFIG["max_tokens"],
                "temperature": LLM_CONFIG["temperature"],
                "messages": messages,
                "stream": True,
            }
            if self._tools_openai:
                stream_kwargs["tools"] = self._tools_openai

            stream = self.client.chat.completions.create(**stream_kwargs)

            # Acumula tool calls fragmentados (streaming envia em pedacos)
            tool_calls_acc: Dict[int, Dict] = {}

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    full_response += delta.content
                    yield delta.content

                # Tool calls (acumulados chunk a chunk)
                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        idx = tc_chunk.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_chunk.id:
                            tool_calls_acc[idx]["id"] = tc_chunk.id
                        if tc_chunk.function and tc_chunk.function.name:
                            tool_calls_acc[idx]["name"] = tc_chunk.function.name
                        if tc_chunk.function and tc_chunk.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_chunk.function.arguments

            # Processa tool calls acumulados
            for idx in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                    logger.warning(f"Falha ao parsear tool call arguments: {tc['arguments']}")
                self.pending_tool_calls.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": args,
                })
                logger.info(f"Tool call detectado: {tc['name']}({args})")

            self._save_openai_tool_history(full_response)

            logger.info(f" LLM (stream completo): '{full_response}'")
            if self.pending_tool_calls:
                logger.info(f"Tool calls pendentes: {len(self.pending_tool_calls)}")

        except Exception as e:
            logger.error(f"Erro no LLM OpenAI streaming: {e}")
            yield "Desculpe, tive um problema ao processar sua mensagem."


class LocalLLM(LLMProvider):
    """
    LLM local usando Docker Model Runner, vLLM, Ollama ou qualquer servidor OpenAI-compatible.

    Suporta streaming e não requer API key.

    Configuração:
        LOCAL_LLM_BASE_URL: URL do servidor (ex: http://localhost:12434/engines/llama.cpp/v1)
        LOCAL_LLM_MODEL: Nome do modelo (ex: ai/smollm3)

    Modelos recomendados para voz (baixa latência):
        - ai/functiongemma (270M) - function-calling, edge devices
        - ai/smollm3 (3.1B) - chat em tempo real
        - ai/phi4 (~3B) - raciocínio compacto
    """

    def __init__(self):
        super().__init__()
        self.client = None
        self.model = None
        self._init_client()

    def _init_client(self):
        """Inicializa cliente OpenAI apontando para servidor local"""
        try:
            from openai import OpenAI

            base_url = LLM_CONFIG.get("local_base_url", "http://localhost:12434/engines/llama.cpp/v1")
            self.model = LLM_CONFIG.get("local_model", "ai/smollm3")

            # Docker Model Runner e similares não precisam de API key real
            self.client = OpenAI(
                api_key="not-needed",
                base_url=base_url,
                timeout=LLM_CONFIG["timeout"]
            )

            logger.info(f"Cliente LLM Local inicializado")
            logger.info(f"  Base URL: {base_url}")
            logger.info(f"  Modelo: {self.model}")

        except ImportError:
            logger.error("OpenAI não instalado. Execute: pip install openai")
            raise
        except Exception as e:
            logger.error(f"Erro ao inicializar LLM Local: {e}")
            raise

    @property
    def supports_streaming(self) -> bool:
        return True

    def _extract_content(self, message) -> str:
        """
        Extrai conteudo da mensagem (modo batch).

        Para modelos de raciocinio (SmolLM3, DeepSeek R1, QwQ, etc):
        - reasoning_content: pensamento interno do modelo (logado para debug)
        - content: resposta final para o usuario (retornado para TTS)
        """
        # Loga reasoning para debug (pensamento interno do modelo)
        reasoning = getattr(message, 'reasoning_content', None)
        if reasoning:
            logger.debug(f"[reasoning] {reasoning}")

        # Retorna apenas content (resposta final para TTS)
        return getattr(message, 'content', None) or ""

    def _save_openai_tool_history(self, assistant_message: str) -> None:
        """Salva resposta OpenAI-compatible no historico com tool_calls e tool results sinteticos."""
        if self.pending_tool_calls:
            tool_calls_history = [{
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["input"]),
                }
            } for tc in self.pending_tool_calls]
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message or None,
                "tool_calls": tool_calls_history,
            })
            for tc in self.pending_tool_calls:
                self.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "Action queued for execution.",
                })
        else:
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message,
            })

    def generate(self, user_message: str) -> str:
        """Gera resposta usando modelo local (modo batch) com tool calling."""
        if not self.client:
            return "Desculpe, não consegui processar sua mensagem."

        self.pending_tool_calls = []

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)

            request_kwargs = {
                "model": self.model,
                "max_tokens": LLM_CONFIG["max_tokens"],
                "temperature": LLM_CONFIG["temperature"],
                "messages": messages,
            }
            if self._tools_openai:
                request_kwargs["tools"] = self._tools_openai

            response = self.client.chat.completions.create(**request_kwargs)

            message = response.choices[0].message
            assistant_message = self._extract_content(message)

            self.pending_tool_calls = _extract_openai_tool_calls(message)
            for tc in self.pending_tool_calls:
                logger.info(f"Tool call detectado (batch): {tc['name']}({tc['input']})")

            self._save_openai_tool_history(assistant_message)

            logger.info(f"LLM Local: '{assistant_message}'")
            if self.pending_tool_calls:
                logger.info(f"Tool calls pendentes (batch): {len(self.pending_tool_calls)}")

            return assistant_message

        except Exception as e:
            logger.error(f"Erro no LLM Local: {e}")
            return "Desculpe, tive um problema ao processar sua mensagem."

    def _extract_delta_content(self, delta) -> str:
        """
        Extrai conteudo do delta de streaming.

        Para modelos de raciocinio (SmolLM3, DeepSeek R1, QwQ, etc):
        - reasoning_content: pensamento interno do modelo (ignorado para TTS)
        - content: resposta final para o usuario (retornado para TTS)
        """
        # Loga reasoning para debug (pensamento interno do modelo)
        reasoning = getattr(delta, 'reasoning_content', None)
        if reasoning:
            logger.debug(f"[reasoning] {reasoning}")

        # Retorna apenas content (resposta final para TTS)
        return getattr(delta, 'content', None) or ""

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """Gera resposta usando modelo local com streaming e tool calling."""
        if not self.client:
            yield "Desculpe, não consegui processar sua mensagem."
            return

        self.pending_tool_calls = []

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)

            stream_kwargs = {
                "model": self.model,
                "max_tokens": LLM_CONFIG["max_tokens"],
                "temperature": LLM_CONFIG["temperature"],
                "messages": messages,
                "stream": True,
            }
            if self._tools_openai:
                stream_kwargs["tools"] = self._tools_openai

            stream = self.client.chat.completions.create(**stream_kwargs)

            full_response = ""
            tool_calls_acc: Dict[int, Dict] = {}

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                text = self._extract_delta_content(delta)
                if text:
                    full_response += text
                    yield text

                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        idx = tc_chunk.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_chunk.id:
                            tool_calls_acc[idx]["id"] = tc_chunk.id
                        if tc_chunk.function and tc_chunk.function.name:
                            tool_calls_acc[idx]["name"] = tc_chunk.function.name
                        if tc_chunk.function and tc_chunk.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_chunk.function.arguments

            for idx in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                    logger.warning(f"Falha ao parsear tool call arguments: {tc['arguments']}")
                self.pending_tool_calls.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": args,
                })
                logger.info(f"Tool call detectado: {tc['name']}({args})")

            self._save_openai_tool_history(full_response)

            logger.info(f"LLM Local (stream completo): '{full_response}'")
            if self.pending_tool_calls:
                logger.info(f"Tool calls pendentes: {len(self.pending_tool_calls)}")

        except Exception as e:
            logger.error(f"Erro no LLM Local streaming: {e}")
            yield "Desculpe, tive um problema ao processar sua mensagem."


class MockLLM(LLMProvider):
    """LLM mock para testes (não requer API)"""

    def __init__(self):
        super().__init__()
        logger.info("Mock LLM inicializado (modo teste)")

    def generate(self, user_message: str) -> str:
        """Gera resposta mock"""
        responses = {
            "olá": "Olá! Como posso ajudá-lo hoje?",
            "oi": "Oi! Em que posso ajudar?",
            "tchau": "Até logo! Tenha um bom dia!",
            "obrigado": "De nada! Posso ajudar em mais alguma coisa?",
        }

        user_lower = user_message.lower()
        for key, response in responses.items():
            if key in user_lower:
                logger.info(f" LLM (mock): '{response}'")
                return response

        default = f"Você disse: {user_message}. Como posso ajudar?"
        logger.info(f" LLM (mock): '{default}'")
        return default

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """Simula streaming para mock"""
        response = self.generate(user_message)
        # Simula streaming palavra por palavra
        words = response.split()
        for i, word in enumerate(words):
            if i < len(words) - 1:
                yield word + " "
            else:
                yield word


def create_llm_provider() -> LLMProvider:
    """
    Factory para criar provedor LLM.

    Providers disponíveis:
        - anthropic: Claude API (requer ANTHROPIC_API_KEY)
        - openai: OpenAI API (requer OPENAI_API_KEY)
        - local: Docker Model Runner, vLLM, Ollama (OpenAI-compatible)
        - mock: Respostas simuladas para testes

    Configuração via variável de ambiente LLM_PROVIDER.
    """
    provider = LLM_CONFIG["provider"]

    if provider == "anthropic":
        try:
            return AnthropicLLM()
        except Exception as e:
            logger.warning(f"Falha ao criar Anthropic LLM: {e}. Usando mock.")
            return MockLLM()
    elif provider == "openai":
        try:
            return OpenAILLM()
        except Exception as e:
            logger.warning(f"Falha ao criar OpenAI LLM: {e}. Usando mock.")
            return MockLLM()
    elif provider == "local":
        try:
            return LocalLLM()
        except Exception as e:
            logger.warning(f"Falha ao criar Local LLM: {e}. Usando mock.")
            logger.warning("Verifique se o servidor local está rodando.")
            return MockLLM()
    elif provider == "mock":
        return MockLLM()
    else:
        logger.warning(f"Provedor LLM não suportado: {provider}. Usando mock.")
        return MockLLM()
