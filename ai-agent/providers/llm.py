"""
LLM (Large Language Model) - Processa texto e gera respostas
Suporta: Anthropic Claude, OpenAI GPT
Versão com streaming para reduzir latência
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Generator, Optional

from config import LLM_CONFIG

logger = logging.getLogger("ai-agent.llm")


class LLMProvider(ABC):
    """Interface base para provedores de LLM"""

    def __init__(self):
        self.conversation_history: List[Dict[str, str]] = []
        self.system_prompt = LLM_CONFIG["system_prompt"]

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
                        yield sentence
                else:
                    break

        # Yield resto do buffer
        if buffer.strip():
            yield buffer.strip()

    def reset_conversation(self):
        """Limpa histórico da conversa"""
        self.conversation_history = []
        logger.info("🔄 Histórico de conversa limpo")

    @property
    def supports_streaming(self) -> bool:
        """Indica se o provedor suporta streaming real"""
        return False


class AnthropicLLM(LLMProvider):
    """LLM usando Anthropic Claude com suporte a streaming"""

    def __init__(self):
        super().__init__()
        self.client = None
        self._init_client()

    def _init_client(self):
        """Inicializa cliente Anthropic"""
        try:
            import anthropic
            api_key = LLM_CONFIG["anthropic_api_key"]
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY não configurada")
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info("✅ Cliente Anthropic inicializado (streaming habilitado)")
        except ImportError:
            logger.error("Anthropic não instalado. Execute: pip install anthropic")
            raise

    @property
    def supports_streaming(self) -> bool:
        return True

    def generate(self, user_message: str) -> str:
        """Gera resposta usando Claude (modo batch)"""
        if not self.client:
            return "Desculpe, não consegui processar sua mensagem."

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            response = self.client.messages.create(
                model=LLM_CONFIG["model"],
                max_tokens=LLM_CONFIG["max_tokens"],
                system=self.system_prompt,
                messages=self.conversation_history,
                timeout=LLM_CONFIG["timeout"]
            )

            assistant_message = response.content[0].text

            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            logger.info(f"🤖 LLM: '{assistant_message}'")
            return assistant_message

        except Exception as e:
            logger.error(f"Erro no LLM Anthropic: {e}")
            return "Desculpe, tive um problema ao processar sua mensagem."

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """Gera resposta usando Claude com streaming"""
        if not self.client:
            yield "Desculpe, não consegui processar sua mensagem."
            return

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            full_response = ""

            # Usa streaming API
            with self.client.messages.stream(
                model=LLM_CONFIG["model"],
                max_tokens=LLM_CONFIG["max_tokens"],
                system=self.system_prompt,
                messages=self.conversation_history,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            # Salva resposta completa no histórico
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

            logger.info(f"🤖 LLM (stream): '{full_response[:50]}...'")

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
            logger.info("✅ Cliente OpenAI inicializado para LLM (streaming habilitado)")
        except ImportError:
            logger.error("OpenAI não instalado. Execute: pip install openai")
            raise

    @property
    def supports_streaming(self) -> bool:
        return True

    def generate(self, user_message: str) -> str:
        """Gera resposta usando GPT (modo batch)"""
        if not self.client:
            return "Desculpe, não consegui processar sua mensagem."

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)

            response = self.client.chat.completions.create(
                model=LLM_CONFIG.get("openai_model", "gpt-3.5-turbo"),
                max_tokens=LLM_CONFIG["max_tokens"],
                temperature=LLM_CONFIG["temperature"],
                messages=messages,
                timeout=LLM_CONFIG["timeout"]
            )

            assistant_message = response.choices[0].message.content

            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            logger.info(f"🤖 LLM: '{assistant_message}'")
            return assistant_message

        except Exception as e:
            logger.error(f"Erro no LLM OpenAI: {e}")
            return "Desculpe, tive um problema ao processar sua mensagem."

    def generate_stream(self, user_message: str) -> Generator[str, None, None]:
        """Gera resposta usando GPT com streaming"""
        if not self.client:
            yield "Desculpe, não consegui processar sua mensagem."
            return

        try:
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)

            full_response = ""

            # Usa streaming API
            stream = self.client.chat.completions.create(
                model=LLM_CONFIG.get("openai_model", "gpt-3.5-turbo"),
                max_tokens=LLM_CONFIG["max_tokens"],
                temperature=LLM_CONFIG["temperature"],
                messages=messages,
                stream=True
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_response += text
                    yield text

            # Salva resposta completa no histórico
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

            logger.info(f"🤖 LLM (stream): '{full_response[:50]}...'")

        except Exception as e:
            logger.error(f"Erro no LLM OpenAI streaming: {e}")
            yield "Desculpe, tive um problema ao processar sua mensagem."


class MockLLM(LLMProvider):
    """LLM mock para testes (não requer API)"""

    def __init__(self):
        super().__init__()
        logger.info("✅ Mock LLM inicializado (modo teste)")

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
                logger.info(f"🤖 LLM (mock): '{response}'")
                return response

        default = f"Você disse: {user_message}. Como posso ajudar?"
        logger.info(f"🤖 LLM (mock): '{default}'")
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
    """Factory para criar provedor LLM"""
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
    elif provider == "mock":
        return MockLLM()
    else:
        logger.warning(f"Provedor LLM não suportado: {provider}. Usando mock.")
        return MockLLM()
