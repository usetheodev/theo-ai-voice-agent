"""Tests for QuickPipeline and provider aliases.

These tests verify that:
1. QuickPipeline.local() imports work correctly
2. Provider aliases are properly defined
3. Providers can be imported from voice_pipeline directly
"""

import pytest


class TestQuickPipelineImports:
    """Test that QuickPipeline imports work correctly."""

    def test_quick_pipeline_import(self):
        """QuickPipeline can be imported from voice_pipeline."""
        from voice_pipeline import QuickPipeline

        assert QuickPipeline is not None

    def test_quick_pipeline_local_method_exists(self):
        """QuickPipeline.local() method exists and is callable."""
        from voice_pipeline import QuickPipeline

        assert hasattr(QuickPipeline, "local")
        assert callable(QuickPipeline.local)

    def test_quick_pipeline_openai_method_exists(self):
        """QuickPipeline.openai() method exists and is callable."""
        from voice_pipeline import QuickPipeline

        assert hasattr(QuickPipeline, "openai")
        assert callable(QuickPipeline.openai)

    def test_quick_pipeline_realtime_openai_method_exists(self):
        """QuickPipeline.realtime_openai() method exists and is callable."""
        from voice_pipeline import QuickPipeline

        assert hasattr(QuickPipeline, "realtime_openai")
        assert callable(QuickPipeline.realtime_openai)


class TestProviderAliases:
    """Test that provider aliases are correctly defined."""

    def test_whisper_asr_alias(self):
        """WhisperASR is an alias for WhisperCppASRProvider."""
        from voice_pipeline.providers import WhisperASR, WhisperCppASRProvider

        assert WhisperASR is WhisperCppASRProvider

    def test_openai_asr_alias(self):
        """OpenAIASR is an alias for OpenAIASRProvider."""
        from voice_pipeline.providers import OpenAIASR, OpenAIASRProvider

        assert OpenAIASR is OpenAIASRProvider

    def test_ollama_llm_alias(self):
        """OllamaLLM is an alias for OllamaLLMProvider."""
        from voice_pipeline.providers import OllamaLLM, OllamaLLMProvider

        assert OllamaLLM is OllamaLLMProvider

    def test_openai_llm_alias(self):
        """OpenAILLM is an alias for OpenAILLMProvider."""
        from voice_pipeline.providers import OpenAILLM, OpenAILLMProvider

        assert OpenAILLM is OpenAILLMProvider

    def test_kokoro_tts_alias(self):
        """KokoroTTS is an alias for KokoroTTSProvider."""
        from voice_pipeline.providers import KokoroTTS, KokoroTTSProvider

        assert KokoroTTS is KokoroTTSProvider

    def test_openai_tts_alias(self):
        """OpenAITTS is an alias for OpenAITTSProvider."""
        from voice_pipeline.providers import OpenAITTS, OpenAITTSProvider

        assert OpenAITTS is OpenAITTSProvider

    def test_silero_vad_alias(self):
        """SileroVAD is an alias for SileroVADProvider."""
        from voice_pipeline.providers import SileroVAD, SileroVADProvider

        assert SileroVAD is SileroVADProvider

    def test_webrtc_vad_alias(self):
        """WebRTCVAD is an alias for WebRTCVADProvider."""
        from voice_pipeline.providers import WebRTCVAD, WebRTCVADProvider

        assert WebRTCVAD is WebRTCVADProvider

    def test_openai_realtime_alias(self):
        """OpenAIRealtime is an alias for OpenAIRealtimeProvider."""
        from voice_pipeline.providers import OpenAIRealtime, OpenAIRealtimeProvider

        assert OpenAIRealtime is OpenAIRealtimeProvider


class TestRootLevelImports:
    """Test that providers can be imported from voice_pipeline directly."""

    def test_import_whisper_asr_from_root(self):
        """WhisperASR can be imported from voice_pipeline."""
        from voice_pipeline import WhisperASR

        assert WhisperASR is not None

    def test_import_ollama_llm_from_root(self):
        """OllamaLLM can be imported from voice_pipeline."""
        from voice_pipeline import OllamaLLM

        assert OllamaLLM is not None

    def test_import_kokoro_tts_from_root(self):
        """KokoroTTS can be imported from voice_pipeline."""
        from voice_pipeline import KokoroTTS

        assert KokoroTTS is not None

    def test_import_silero_vad_from_root(self):
        """SileroVAD can be imported from voice_pipeline."""
        from voice_pipeline import SileroVAD

        assert SileroVAD is not None

    def test_import_openai_providers_from_root(self):
        """OpenAI providers can be imported from voice_pipeline."""
        from voice_pipeline import OpenAIASR, OpenAILLM, OpenAITTS, OpenAIRealtime

        assert OpenAIASR is not None
        assert OpenAILLM is not None
        assert OpenAITTS is not None
        assert OpenAIRealtime is not None

    def test_import_full_provider_names_from_root(self):
        """Full provider names can be imported from voice_pipeline."""
        from voice_pipeline import (
            WhisperCppASRProvider,
            OllamaLLMProvider,
            KokoroTTSProvider,
            SileroVADProvider,
        )

        assert WhisperCppASRProvider is not None
        assert OllamaLLMProvider is not None
        assert KokoroTTSProvider is not None
        assert SileroVADProvider is not None


class TestProviderInstantiation:
    """Test that providers can be instantiated."""

    def test_whisper_asr_instantiation(self):
        """WhisperASR can be instantiated without errors."""
        from voice_pipeline import WhisperASR

        # Should not raise on instantiation
        provider = WhisperASR(model="base")
        assert provider is not None
        assert provider.name == "WhisperCppASR"

    def test_ollama_llm_instantiation(self):
        """OllamaLLM can be instantiated without errors."""
        from voice_pipeline import OllamaLLM

        provider = OllamaLLM(model="llama3")
        assert provider is not None
        assert provider.name == "OllamaLLM"

    def test_kokoro_tts_instantiation(self):
        """KokoroTTS can be instantiated without errors."""
        from voice_pipeline import KokoroTTS

        provider = KokoroTTS(voice="af_bella")
        assert provider is not None
        assert provider.name == "KokoroTTS"

    def test_silero_vad_instantiation(self):
        """SileroVAD can be instantiated without errors."""
        from voice_pipeline import SileroVAD

        provider = SileroVAD()
        assert provider is not None
        assert provider.name == "SileroVAD"
