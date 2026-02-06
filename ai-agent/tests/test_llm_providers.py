"""
Testes unitários para LLM providers.

Testa AnthropicLLM, OpenAILLM, LocalLLM, MockLLM e factory.
Todos os testes usam mocks (não requerem API keys reais).
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

_mock_llm_config = {
    "provider": "mock",
    "system_prompt": "Você é um assistente de teste.",
    "max_tokens": 500,
    "temperature": 0.7,
    "timeout": 30,
    "max_history_turns": 20,
}

_mock_anthropic_config = {
    "api_key": "test-anthropic-key",
    "model": "claude-3-haiku-20240307",
}

_mock_openai_config = {
    "api_key": "test-openai-key",
    "model": "gpt-4o-mini",
    "base_url": "",
}

_mock_local_config = {
    "api_key": "not-needed",
    "model": "local-model",
    "base_url": "http://localhost:8080/v1",
}


@pytest.fixture(autouse=True)
def mock_configs(monkeypatch):
    """Mock configs para todos os testes."""
    monkeypatch.setattr("providers.llm.LLM_CONFIG", _mock_llm_config)
    monkeypatch.setattr("providers.llm.ANTHROPIC_LLM_CONFIG", _mock_anthropic_config)
    monkeypatch.setattr("providers.llm.OPENAI_LLM_CONFIG", _mock_openai_config)
    monkeypatch.setattr("providers.llm.LOCAL_LLM_CONFIG", _mock_local_config)


# ==================== MockLLM Tests ====================

class TestMockLLM:
    """Testes para MockLLM provider."""

    def test_generate_returns_response(self):
        """Verifica que generate retorna resposta."""
        from providers.llm import MockLLM
        llm = MockLLM()
        response = llm.generate("olá")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_generate_stream_yields_chunks(self):
        """Verifica que generate_stream retorna chunks."""
        from providers.llm import MockLLM
        llm = MockLLM()
        chunks = list(llm.generate_stream("olá"))
        assert len(chunks) > 0

    def test_supports_streaming(self):
        """Verifica que MockLLM não suporta streaming real."""
        from providers.llm import MockLLM
        llm = MockLLM()
        assert not llm.supports_streaming

    def test_reset_conversation(self):
        """Verifica que reset limpa histórico."""
        from providers.llm import MockLLM
        llm = MockLLM()
        # MockLLM.generate() não adiciona ao conversation_history (é mock simples),
        # então populamos manualmente para testar o reset
        llm.conversation_history.append({"role": "user", "content": "olá"})
        llm.conversation_history.append({"role": "assistant", "content": "Oi!"})
        assert len(llm.conversation_history) > 0
        llm.reset_conversation()
        assert len(llm.conversation_history) == 0


# ==================== AnthropicLLM Tests ====================

class TestAnthropicLLM:
    """Testes para AnthropicLLM provider."""

    @pytest.fixture
    def mock_anthropic_module(self):
        """Mock do módulo anthropic."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_module.Anthropic.return_value = mock_client
        return mock_module, mock_client

    def test_generate_returns_text(self, mock_anthropic_module):
        """Verifica que generate retorna texto da resposta."""
        mock_module, mock_client = mock_anthropic_module

        # Mock response
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Olá! Como posso ajudar?"
        mock_response.content = [mock_content]
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.llm import AnthropicLLM
            llm = AnthropicLLM()
            llm.client = mock_client

            response = llm.generate("olá")
            assert "Olá" in response

    def test_tool_calling_extraction(self, mock_anthropic_module):
        """Verifica extração de tool calls da resposta Anthropic."""
        mock_module, mock_client = mock_anthropic_module

        # Mock response com tool_use
        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "Vou transferir você."

        mock_tool = MagicMock()
        mock_tool.type = "tool_use"
        mock_tool.id = "call_123"
        mock_tool.name = "transfer_call"
        mock_tool.input = {"target": "1001", "reason": "Solicitação do cliente"}

        mock_response = MagicMock()
        mock_response.content = [mock_text, mock_tool]
        mock_response.stop_reason = "tool_use"
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.llm import AnthropicLLM
            llm = AnthropicLLM()
            llm.client = mock_client

            response = llm.generate("transfira para o ramal 1001")
            assert len(llm.pending_tool_calls) > 0
            assert llm.pending_tool_calls[0]["name"] == "transfer_call"

    def test_supports_streaming(self, mock_anthropic_module):
        """Verifica que AnthropicLLM suporta streaming."""
        mock_module, mock_client = mock_anthropic_module
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.llm import AnthropicLLM
            llm = AnthropicLLM()
            assert llm.supports_streaming

    def test_history_truncation(self, mock_anthropic_module):
        """Verifica truncamento do histórico."""
        mock_module, mock_client = mock_anthropic_module

        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Resposta."
        mock_response.content = [mock_content]
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.llm import AnthropicLLM
            llm = AnthropicLLM()
            llm.client = mock_client
            llm.max_history_turns = 3

            # Gera mais de 3 turnos
            for i in range(10):
                llm.generate(f"mensagem {i}")

            # _truncate_history() é chamado ANTES de adicionar a nova mensagem,
            # então após a última chamada: trunca para max*2, depois adiciona user+assistant = max*2+2
            max_msgs = llm.max_history_turns * 2 + 2
            assert len(llm.conversation_history) <= max_msgs


# ==================== OpenAI LLM Tests ====================

class TestOpenAILLM:
    """Testes para OpenAILLM provider."""

    @pytest.fixture
    def mock_openai_module(self):
        """Mock do módulo openai."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_module.OpenAI.return_value = mock_client
        return mock_module, mock_client

    def test_generate_returns_text(self, mock_openai_module):
        """Verifica que generate retorna texto."""
        mock_module, mock_client = mock_openai_module

        mock_message = MagicMock()
        mock_message.content = "Olá! Como posso ajudar?"
        mock_message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_module}):
            from providers.llm import OpenAILLM
            llm = OpenAILLM()
            llm.client = mock_client
            response = llm.generate("olá")
            assert "Olá" in response

    def test_tool_calls_extraction(self, mock_openai_module):
        """Verifica extração de tool calls OpenAI."""
        mock_module, mock_client = mock_openai_module

        # Mock tool call na resposta
        mock_tc = MagicMock()
        mock_tc.id = "call_456"
        mock_tc.function.name = "end_call"
        mock_tc.function.arguments = '{"reason": "Finalizado"}'

        mock_message = MagicMock()
        mock_message.content = "Encerrando a chamada."
        mock_message.tool_calls = [mock_tc]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_module}):
            from providers.llm import OpenAILLM
            llm = OpenAILLM()
            llm.client = mock_client
            llm.generate("encerre a chamada")
            assert len(llm.pending_tool_calls) > 0
            assert llm.pending_tool_calls[0]["name"] == "end_call"

    def test_supports_streaming(self, mock_openai_module):
        """Verifica que OpenAILLM suporta streaming."""
        mock_module, mock_client = mock_openai_module
        with patch.dict("sys.modules", {"openai": mock_module}):
            from providers.llm import OpenAILLM
            llm = OpenAILLM()
            assert llm.supports_streaming

    def test_streaming_with_fragmented_tool_calls(self, mock_openai_module):
        """Verifica que tool calls fragmentados em streaming são resolvidos."""
        from providers.llm import _resolve_streaming_tool_calls

        # Simula acumulador de streaming
        tool_calls_acc = {
            0: {
                "id": "call_789",
                "name": "transfer_call",
                "arguments": '{"target": "1002", "reason": "teste"}',
            }
        }

        result = _resolve_streaming_tool_calls(tool_calls_acc)
        assert len(result) == 1
        assert result[0]["name"] == "transfer_call"
        assert result[0]["input"]["target"] == "1002"

    def test_history_truncation(self, mock_openai_module):
        """Verifica truncamento do histórico OpenAI."""
        mock_module, mock_client = mock_openai_module

        mock_message = MagicMock()
        mock_message.content = "Resposta."
        mock_message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_module}):
            from providers.llm import OpenAILLM
            llm = OpenAILLM()
            llm.client = mock_client
            llm.max_history_turns = 3

            for i in range(10):
                llm.generate(f"mensagem {i}")

            # _truncate_history() é chamado ANTES de adicionar a nova mensagem,
            # então após a última chamada: trunca para max*2, depois adiciona user+assistant = max*2+2
            max_msgs = llm.max_history_turns * 2 + 2
            assert len(llm.conversation_history) <= max_msgs


# ==================== Generate Sentences Tests ====================

class TestGenerateSentences:
    """Testes para generate_sentences (split por frases)."""

    def test_single_sentence(self):
        """Verifica que uma frase única é retornada."""
        from providers.llm import MockLLM
        llm = MockLLM()

        # Override generate_stream para controlar output
        llm.generate_stream = lambda msg: iter(["Olá, como vai?"])
        sentences = list(llm.generate_sentences("teste"))
        assert len(sentences) >= 1

    def test_multiple_sentences(self):
        """Verifica split de múltiplas frases."""
        from providers.llm import MockLLM
        llm = MockLLM()

        llm.generate_stream = lambda msg: iter(["Primeira frase. Segunda frase. Terceira!"])
        sentences = list(llm.generate_sentences("teste"))
        assert len(sentences) == 3

    def test_streaming_sentences(self):
        """Verifica que frases são geradas incrementalmente."""
        from providers.llm import MockLLM
        llm = MockLLM()

        # Simula streaming chunk por chunk
        chunks = ["Olá, ", "como vai? ", "Tudo bem. ", "Obrigado!"]
        llm.generate_stream = lambda msg: iter(chunks)
        sentences = list(llm.generate_sentences("teste"))
        assert len(sentences) >= 2

    def test_empty_buffer_not_yielded(self):
        """Verifica que buffer vazio não gera sentença."""
        from providers.llm import MockLLM
        llm = MockLLM()

        llm.generate_stream = lambda msg: iter([""])
        sentences = list(llm.generate_sentences("teste"))
        assert len(sentences) == 0


# ==================== Factory Tests ====================

class TestLLMFactory:
    """Testes para factory create_llm_provider."""

    def test_create_mock_provider(self):
        """Verifica criação de MockLLM."""
        from providers.llm import create_llm_provider, MockLLM
        llm = create_llm_provider()  # config diz "mock"
        assert isinstance(llm, MockLLM)

    def test_create_anthropic_provider(self):
        """Verifica criação de AnthropicLLM."""
        mock_module = MagicMock()
        mock_module.Anthropic.return_value = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            with patch("providers.llm.LLM_CONFIG", {**_mock_llm_config, "provider": "anthropic"}):
                from providers.llm import create_llm_provider, AnthropicLLM
                llm = create_llm_provider()
                assert isinstance(llm, AnthropicLLM)

    def test_create_openai_provider(self):
        """Verifica criação de OpenAILLM."""
        mock_module = MagicMock()
        mock_module.OpenAI.return_value = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_module}):
            with patch("providers.llm.LLM_CONFIG", {**_mock_llm_config, "provider": "openai"}):
                from providers.llm import create_llm_provider, OpenAILLM
                llm = create_llm_provider()
                assert isinstance(llm, OpenAILLM)
