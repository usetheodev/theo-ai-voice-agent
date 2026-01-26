"""Testes de invariantes arquiteturais.

Estes testes garantem que decisões arquiteturais sejam mantidas
e não regridam silenciosamente.
"""

import inspect

import pytest


# =============================================================================
# Single Source of Truth
# =============================================================================


class TestSingleSourceOfTruth:
    """Garantir que não há duplicação de domain concepts."""

    def test_conversation_state_single_definition(self):
        """ConversationState deve existir apenas em core.state_machine."""
        from voice_pipeline.core.state_machine import ConversationState as CoreState
        from voice_pipeline import ConversationState as PublicState

        assert CoreState is PublicState

    def test_conversation_state_chains_reexport(self):
        """chains/ deve re-exportar o mesmo ConversationState."""
        from voice_pipeline.core.state_machine import ConversationState as CoreState
        from voice_pipeline.chains import ConversationState as ChainsState

        assert CoreState is ChainsState

    def test_conversation_state_has_full_duplex(self):
        """ConversationState público deve ter FULL_DUPLEX."""
        from voice_pipeline import ConversationState

        assert hasattr(ConversationState, "FULL_DUPLEX")

    def test_conversation_state_has_all_states(self):
        """ConversationState deve ter todos os estados esperados."""
        from voice_pipeline import ConversationState

        expected = {"IDLE", "LISTENING", "PROCESSING", "SPEAKING", "INTERRUPTED", "FULL_DUPLEX"}
        actual = {member.name for member in ConversationState}
        assert expected.issubset(actual), f"Faltando: {expected - actual}"


# =============================================================================
# Dependency Direction
# =============================================================================


class TestDependencyDirection:
    """Garantir que dependências fluem top-down."""

    def test_interfaces_dont_import_providers(self):
        """interfaces/ não deve importar de providers/."""
        import voice_pipeline.interfaces as iface_mod

        source = inspect.getsource(iface_mod)
        assert "from voice_pipeline.providers" not in source

    def test_runnable_doesnt_import_interfaces(self):
        """runnable/ não deve importar de interfaces/."""
        import voice_pipeline.runnable.base as runnable_mod

        source = inspect.getsource(runnable_mod)
        assert "from voice_pipeline.interfaces" not in source

    def test_runnable_doesnt_import_chains(self):
        """runnable/ não deve importar de chains/."""
        import voice_pipeline.runnable.base as runnable_mod

        source = inspect.getsource(runnable_mod)
        assert "from voice_pipeline.chains" not in source

    def test_interfaces_dont_import_chains(self):
        """interfaces/ não deve importar de chains/."""
        import voice_pipeline.interfaces as iface_mod

        source = inspect.getsource(iface_mod)
        assert "from voice_pipeline.chains" not in source


# =============================================================================
# Contract Stability
# =============================================================================


class TestContractStability:
    """Garantir que contratos críticos existem."""

    def test_asr_interface_has_transcribe_stream(self):
        from voice_pipeline.interfaces.asr import ASRInterface

        assert hasattr(ASRInterface, "transcribe_stream")

    def test_llm_interface_has_generate_stream(self):
        from voice_pipeline.interfaces.llm import LLMInterface

        assert hasattr(LLMInterface, "generate_stream")

    def test_tts_interface_has_synthesize_stream(self):
        from voice_pipeline.interfaces.tts import TTSInterface

        assert hasattr(TTSInterface, "synthesize_stream")

    def test_voice_runnable_has_pipe_operator(self):
        from voice_pipeline.runnable.base import VoiceRunnable

        assert hasattr(VoiceRunnable, "__or__")

    def test_asr_has_streaming_input_property(self):
        """ASR deve declarar streaming via interface, não heurística."""
        from voice_pipeline.interfaces.asr import ASRInterface

        assert hasattr(ASRInterface, "supports_streaming_input")
        # Default deve ser False
        assert ASRInterface.supports_streaming_input.fget is not None


# =============================================================================
# Registry Integrity
# =============================================================================


class TestRegistryIntegrity:
    """Garantir que Registry está populado."""

    def test_registry_has_asr_providers(self):
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        providers = registry.list_asr()
        assert len(providers) > 0, "Nenhum provider ASR registrado"

    def test_registry_has_llm_providers(self):
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        providers = registry.list_llm()
        assert len(providers) > 0, "Nenhum provider LLM registrado"

    def test_registry_has_tts_providers(self):
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        providers = registry.list_tts()
        assert len(providers) > 0, "Nenhum provider TTS registrado"

    def test_registry_has_vad_providers(self):
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        providers = registry.list_vad()
        assert len(providers) > 0, "Nenhum provider VAD registrado"

    def test_registry_singleton_consistency(self):
        """get_registry() deve sempre retornar o mesmo singleton."""
        from voice_pipeline.providers.registry import get_registry

        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


# =============================================================================
# No Leaky Abstractions
# =============================================================================


class TestNoLeakyAbstractions:
    """Garantir que abstrações não vazam implementação."""

    def test_no_hardcoded_provider_names_in_streaming(self):
        """StreamingVoiceChain não deve ter nomes de providers hardcoded."""
        import voice_pipeline.chains.streaming as streaming_mod

        source = inspect.getsource(streaming_mod)
        # Não deve ter heurísticas de nome de provider
        assert "_is_realtime_asr" not in source, (
            "_is_realtime_asr() não deveria existir — usar supports_streaming_input"
        )

    def test_deepgram_declares_streaming_input(self):
        """Deepgram deve declarar supports_streaming_input = True."""
        from voice_pipeline.providers.asr.deepgram import DeepgramASRProvider

        provider = DeepgramASRProvider(api_key="test")
        assert provider.supports_streaming_input is True

    def test_memory_contract_is_typed(self):
        """ConversationChain deve usar VoiceMemory tipado, não Any."""
        from voice_pipeline.chains.conversation import ConversationChain

        source = inspect.getsource(ConversationChain.__init__)
        assert "Optional[Any]" not in source, "memory não deve ser Optional[Any]"

    def test_llm_input_no_trailing_any(self):
        """LLMInput não deve ter Any como fallback."""
        from voice_pipeline.interfaces.llm import LLMInput
        import typing

        args = typing.get_args(LLMInput)
        from typing import Any

        assert Any not in args, f"LLMInput contém Any: {args}"


# =============================================================================
# Chain Inheritance
# =============================================================================


class TestChainInheritance:
    """Garantir hierarquia de chains."""

    def test_base_voice_chain_exists(self):
        """BaseVoiceChain deve ser importável."""
        from voice_pipeline.chains.base_voice_chain import BaseVoiceChain

        assert BaseVoiceChain is not None

    def test_voice_chain_inherits_from_base(self):
        from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
        from voice_pipeline.chains.base import VoiceChain

        assert issubclass(VoiceChain, BaseVoiceChain)

    def test_conversation_chain_inherits_from_base(self):
        from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
        from voice_pipeline.chains.conversation import ConversationChain

        assert issubclass(ConversationChain, BaseVoiceChain)

    def test_streaming_chain_inherits_from_base(self):
        from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        assert issubclass(StreamingVoiceChain, BaseVoiceChain)

    def test_parallel_chain_inherits_from_base(self):
        from voice_pipeline.chains.base_voice_chain import BaseVoiceChain
        from voice_pipeline.chains.streaming import ParallelStreamingChain

        assert issubclass(ParallelStreamingChain, BaseVoiceChain)

    def test_base_voice_chain_is_public(self):
        """BaseVoiceChain deve ser acessível via import público."""
        from voice_pipeline import BaseVoiceChain

        assert BaseVoiceChain is not None

    def test_all_chains_share_common_api(self):
        """Todas as chains devem ter os métodos comuns do BaseVoiceChain."""
        from voice_pipeline.chains.base_voice_chain import BaseVoiceChain

        expected_attrs = ["_add_message", "messages", "ainvoke", "reset", "astream"]
        for attr in expected_attrs:
            assert hasattr(BaseVoiceChain, attr), f"BaseVoiceChain faltando: {attr}"


# =============================================================================
# Lifecycle
# =============================================================================


class TestLifecycle:
    """Garantir que lifecycle management está consistente."""

    def test_base_provider_has_ensure_connected(self):
        """BaseProvider deve ter _ensure_connected()."""
        from voice_pipeline.providers.base import BaseProvider

        assert hasattr(BaseProvider, "_ensure_connected")

    def test_base_provider_has_async_context_manager(self):
        """BaseProvider deve suportar async with."""
        from voice_pipeline.providers.base import BaseProvider

        assert hasattr(BaseProvider, "__aenter__")
        assert hasattr(BaseProvider, "__aexit__")


# =============================================================================
# No Dead Code
# =============================================================================


class TestNoDeadCode:
    """Garantir que dead code foi removido."""

    def test_no_output_loop_in_pipeline(self):
        """Pipeline não deve ter _output_loop (dead code removido)."""
        from voice_pipeline.core.pipeline import Pipeline

        assert not hasattr(Pipeline, "_output_loop"), (
            "_output_loop é dead code e deveria ter sido removido"
        )
