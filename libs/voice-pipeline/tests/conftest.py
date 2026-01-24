"""Pytest fixtures and mock providers for voice-pipeline tests.

This module provides reusable fixtures for testing the voice pipeline components.
Mock implementations are defined in mocks.py.

Usage:
    # In your test file, fixtures are automatically available:
    async def test_my_pipeline(mock_asr, mock_llm, mock_tts):
        chain = mock_asr | mock_llm | mock_tts
        result = await chain.ainvoke(audio_bytes)

    # Or use the fixture factories for customization:
    async def test_custom(create_mock_asr):
        asr = create_mock_asr(response="Custom text", latency=0.1)
"""

from typing import AsyncIterator, Callable

import pytest

from voice_pipeline import Pipeline, PipelineConfig

# Import mocks from mocks.py
from tests.mocks import (
    MockASR,
    MockLLM,
    MockTTS,
    MockVAD,
    MockRealtime,
    MockTransport,
    create_pcm16_audio,
    create_silence,
    create_audio_chunks,
)


# ==============================================================================
# Pytest Fixtures
# ==============================================================================


# --- Audio Fixtures ---


@pytest.fixture
def audio_sample() -> bytes:
    """1 second of test audio at 16kHz."""
    return create_pcm16_audio(1.0, 16000)


@pytest.fixture
def audio_chunks() -> list[bytes]:
    """List of 20ms audio chunks (50 chunks = 1 second)."""
    return create_audio_chunks(1.0, 0.02, 16000)


@pytest.fixture
def silence_sample() -> bytes:
    """1 second of silence at 16kHz."""
    return create_silence(1.0, 16000)


# --- Mock Provider Fixtures ---


@pytest.fixture
def mock_asr() -> MockASR:
    """Default MockASR instance."""
    return MockASR()


@pytest.fixture
def mock_llm() -> MockLLM:
    """Default MockLLM instance."""
    return MockLLM()


@pytest.fixture
def mock_tts() -> MockTTS:
    """Default MockTTS instance."""
    return MockTTS()


@pytest.fixture
def mock_vad() -> MockVAD:
    """Default MockVAD instance."""
    return MockVAD()


@pytest.fixture
def mock_realtime() -> MockRealtime:
    """Default MockRealtime instance."""
    return MockRealtime()


@pytest.fixture
def mock_transport() -> MockTransport:
    """Default MockTransport instance."""
    return MockTransport()


# --- Factory Fixtures ---


@pytest.fixture
def create_mock_asr() -> Callable[..., MockASR]:
    """Factory for creating MockASR with custom config."""
    def factory(**kwargs) -> MockASR:
        return MockASR(**kwargs)
    return factory


@pytest.fixture
def create_mock_llm() -> Callable[..., MockLLM]:
    """Factory for creating MockLLM with custom config."""
    def factory(**kwargs) -> MockLLM:
        return MockLLM(**kwargs)
    return factory


@pytest.fixture
def create_mock_tts() -> Callable[..., MockTTS]:
    """Factory for creating MockTTS with custom config."""
    def factory(**kwargs) -> MockTTS:
        return MockTTS(**kwargs)
    return factory


@pytest.fixture
def create_mock_vad() -> Callable[..., MockVAD]:
    """Factory for creating MockVAD with custom config."""
    def factory(**kwargs) -> MockVAD:
        return MockVAD(**kwargs)
    return factory


# --- Pipeline Fixtures ---


@pytest.fixture
def pipeline_config() -> PipelineConfig:
    """Default pipeline configuration."""
    return PipelineConfig(
        system_prompt="You are a helpful voice assistant.",
        language="en",
    )


@pytest.fixture
def mock_pipeline(
    pipeline_config: PipelineConfig,
    mock_asr: MockASR,
    mock_llm: MockLLM,
    mock_tts: MockTTS,
    mock_vad: MockVAD,
) -> Pipeline:
    """Pipeline with all mock providers."""
    return Pipeline(
        config=pipeline_config,
        asr=mock_asr,
        llm=mock_llm,
        tts=mock_tts,
        vad=mock_vad,
    )


# --- Async Stream Fixtures ---


@pytest.fixture
def audio_stream_factory() -> Callable[[list[bytes]], AsyncIterator[bytes]]:
    """Factory for creating async audio streams."""
    async def create_stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk
    return create_stream


@pytest.fixture
def text_stream_factory() -> Callable[[list[str]], AsyncIterator[str]]:
    """Factory for creating async text streams."""
    async def create_stream(texts: list[str]) -> AsyncIterator[str]:
        for text in texts:
            yield text
    return create_stream
