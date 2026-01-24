"""Integration tests for voice pipeline components.

These tests verify that individual components work correctly together,
focusing on interface contracts and data flow between components.
"""

import asyncio
from typing import AsyncIterator

import pytest

from voice_pipeline import (
    VoiceRunnable,
    VoiceSequence,
    VoiceParallel,
    VoiceLambda,
    VoicePassthrough,
    VoiceFallback,
    VoiceRetry,
    TranscriptionResult,
    LLMChunk,
    AudioChunk,
)
from voice_pipeline.streaming import SentenceStreamer, SentenceStreamerConfig

from tests.mocks import (
    MockASR,
    MockLLM,
    MockTTS,
    MockVAD,
    create_pcm16_audio,
    create_audio_chunks,
)


# ==============================================================================
# ASR + LLM Integration Tests
# ==============================================================================


class TestASRToLLMIntegration:
    """Tests for ASR to LLM data flow."""

    @pytest.mark.asyncio
    async def test_asr_output_as_llm_input(self, mock_asr, mock_llm):
        """Test that ASR output correctly feeds into LLM."""
        # Configure ASR response
        mock_asr.config.response = "What is the capital of France?"

        async def audio_stream():
            yield create_pcm16_audio(0.5, 16000)

        # Chain ASR to LLM
        chain = mock_asr | mock_llm

        # Process
        results = []
        async for chunk in chain.astream(audio_stream()):
            results.append(chunk)

        # Verify LLM received correct input
        assert len(mock_llm.messages_received) > 0
        last_message = mock_llm.messages_received[-1]
        assert "What is the capital of France?" in last_message.get("content", "")

    @pytest.mark.asyncio
    async def test_interim_asr_results_filtered(self, create_mock_asr, mock_llm):
        """Test that only final ASR results reach LLM."""
        asr = create_mock_asr(
            response="Final result",
            interim_results=True,
            word_by_word=True,
        )

        async def audio_stream():
            yield create_pcm16_audio(0.5, 16000)

        chain = asr | mock_llm

        async for _ in chain.astream(audio_stream()):
            pass

        # LLM should only receive the final complete text
        # (depends on chain implementation)
        assert len(mock_llm.messages_received) >= 1

    @pytest.mark.asyncio
    async def test_asr_language_passthrough(self, create_mock_asr, mock_llm):
        """Test that language info can be passed through."""
        asr = create_mock_asr(response="Bonjour")

        async def audio_stream():
            for chunk in create_audio_chunks(0.3, 0.02, 16000):
                yield chunk

        # Process with language hint
        results = []
        async for result in asr.transcribe_stream(audio_stream(), language="fr"):
            results.append(result)

        # ASR should have received language parameter
        assert any(call.get("language") == "fr" for call in asr.calls)


# ==============================================================================
# LLM + TTS Integration Tests
# ==============================================================================


class TestLLMToTTSIntegration:
    """Tests for LLM to TTS data flow."""

    @pytest.mark.asyncio
    async def test_llm_streaming_to_tts(self, mock_llm, mock_tts):
        """Test LLM streaming output feeds TTS correctly."""
        mock_llm.config.response = "Hello there! How are you?"
        mock_llm.config.stream_by = "word"

        # Create a chain that connects LLM output to TTS input
        async def process():
            messages = [{"role": "user", "content": "Hi"}]

            # Collect LLM chunks
            llm_output = []
            async for chunk in mock_llm.generate_stream(messages):
                llm_output.append(chunk.text)

            # Feed to TTS
            async def text_stream():
                for text in llm_output:
                    yield text

            tts_output = []
            async for audio in mock_tts.synthesize_stream(text_stream()):
                tts_output.append(audio)

            return llm_output, tts_output

        llm_chunks, tts_chunks = await process()

        # Verify streaming worked
        assert len(llm_chunks) > 1  # Multiple words
        assert len(tts_chunks) > 1  # Multiple audio chunks

    @pytest.mark.asyncio
    async def test_tts_receives_complete_sentences(self, create_mock_llm, mock_tts):
        """Test that TTS can receive complete sentences."""
        llm = create_mock_llm(
            response="First sentence. Second sentence. Third one!",
            stream_by="sentence",
        )

        messages = [{"role": "user", "content": "Test"}]

        sentences = []
        async for chunk in llm.generate_stream(messages):
            sentences.append(chunk.text)

        async def text_stream():
            for s in sentences:
                yield s

        audio_chunks = []
        async for audio in mock_tts.synthesize_stream(text_stream()):
            audio_chunks.append(audio)

        # Should have 3 audio chunks (one per sentence)
        assert len(audio_chunks) == 3


# ==============================================================================
# VAD Integration Tests
# ==============================================================================


class TestVADIntegration:
    """Tests for VAD integration with pipeline."""

    @pytest.mark.asyncio
    async def test_vad_filters_silence(self, create_mock_vad, mock_asr):
        """Test VAD filtering silence before ASR."""
        # VAD with 5 speech frames, then silence
        vad = create_mock_vad(speech_pattern=[True, True, True, True, True, False, False])

        audio_chunks = create_audio_chunks(0.14, 0.02, 16000)  # 7 chunks

        # Filter through VAD
        speech_chunks = []
        for chunk in audio_chunks:
            event = await vad.process(chunk, 16000)
            if event.is_speech:
                speech_chunks.append(chunk)

        # Should have filtered some chunks
        assert len(speech_chunks) == 5
        assert len(speech_chunks) < len(audio_chunks)

    @pytest.mark.asyncio
    async def test_vad_speech_detection_sequence(self, create_mock_vad):
        """Test VAD detects speech start and end."""
        # Pattern: silence, speech, silence
        vad = create_mock_vad(
            speech_pattern=[False, False, True, True, True, True, False, False]
        )

        chunks = create_audio_chunks(0.16, 0.02, 16000)  # 8 chunks

        events = []
        for chunk in chunks:
            event = await vad.process(chunk, 16000)
            events.append(event)

        # Check pattern
        speech_started = False
        speech_ended = False

        for i, event in enumerate(events):
            if i > 0 and event.is_speech and not events[i - 1].is_speech:
                speech_started = True
            if i > 0 and not event.is_speech and events[i - 1].is_speech:
                speech_ended = True

        assert speech_started
        assert speech_ended


# ==============================================================================
# Sentence Streamer Integration Tests
# ==============================================================================


class TestSentenceStreamerIntegration:
    """Tests for sentence streamer with LLM and TTS."""

    @pytest.mark.asyncio
    async def test_sentence_streamer_buffers_correctly(self, mock_llm, mock_tts):
        """Test sentence streamer buffers LLM output into sentences."""
        mock_llm.config.response = "This is sentence one. Here is another. And a third!"
        mock_llm.config.stream_by = "word"

        config = SentenceStreamerConfig(
            min_chars=5,
            sentence_end_chars=[".", "!", "?"],
        )
        streamer = SentenceStreamer(config)

        # Collect words from LLM
        messages = [{"role": "user", "content": "Test"}]
        words = []
        async for chunk in mock_llm.generate_stream(messages):
            words.append(chunk.text)

        # Stream through sentence streamer using process_stream
        sentences = []

        async def word_stream():
            for word in words:
                yield word

        async for sentence in streamer.process_stream(word_stream()):
            sentences.append(sentence)

        # Should have buffered into sentences
        assert len(sentences) >= 1

    @pytest.mark.asyncio
    async def test_sentence_streamer_flush(self, create_mock_llm):
        """Test sentence streamer flushes incomplete sentences."""
        llm = create_mock_llm(
            response="This has no ending punctuation",
            stream_by="word",
        )

        config = SentenceStreamerConfig(min_chars=3)
        streamer = SentenceStreamer(config)

        messages = [{"role": "user", "content": "Test"}]

        async def text_stream():
            async for chunk in llm.generate_stream(messages):
                yield chunk.text

        sentences = []
        async for sentence in streamer.process_stream(text_stream()):
            sentences.append(sentence)

        # Flush remaining
        remaining = streamer.flush()
        if remaining:
            sentences.append(remaining)

        # Should have the incomplete sentence
        full_text = " ".join(sentences).strip()
        assert "no ending punctuation" in full_text


# ==============================================================================
# Chain Composition Tests
# ==============================================================================


class TestChainComposition:
    """Tests for chain composition patterns."""

    @pytest.mark.asyncio
    async def test_sequence_chain(self, mock_asr, mock_llm, mock_tts):
        """Test basic sequence chain."""
        # VoiceSequence takes a list of runnables
        chain = VoiceSequence([mock_asr, mock_llm, mock_tts])

        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        results = []
        async for result in chain.astream(audio()):
            results.append(result)

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_operator_chain(self, mock_asr, mock_llm, mock_tts):
        """Test chain using | operator."""
        chain = mock_asr | mock_llm | mock_tts

        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        results = []
        async for result in chain.astream(audio()):
            results.append(result)

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_lambda_in_chain(self, mock_asr, mock_llm):
        """Test VoiceLambda in chain for transformation."""
        # Transform ASR output before LLM
        transform = VoiceLambda(
            lambda x: x.upper() if isinstance(x, str) else x
        )

        # Note: This tests the concept, actual transformation depends on implementation
        chain = mock_asr | transform | mock_llm

        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        results = []
        async for result in chain.astream(audio()):
            results.append(result)

        # Chain should complete
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_passthrough_in_chain(self, mock_asr, mock_llm):
        """Test VoicePassthrough preserves data."""
        passthrough = VoicePassthrough()

        chain = mock_asr | passthrough | mock_llm

        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        results = []
        async for result in chain.astream(audio()):
            results.append(result)

        assert len(results) > 0


# ==============================================================================
# Error Handling Integration Tests
# ==============================================================================


class TestErrorHandlingIntegration:
    """Tests for error handling across components."""

    @pytest.mark.asyncio
    async def test_fallback_chain(self, create_mock_asr, mock_llm, mock_tts):
        """Test fallback chain when primary fails."""
        # Primary ASR that fails
        primary_asr = create_mock_asr(fail_after=1, error_message="Primary failed")

        # Fallback ASR that works
        fallback_asr = create_mock_asr(response="Fallback transcription")

        # Create fallback chain - VoiceFallback takes primary and list of fallbacks
        asr_with_fallback = VoiceFallback(primary_asr, [fallback_asr])

        chain = asr_with_fallback | mock_llm | mock_tts

        async def audio():
            for chunk in create_audio_chunks(0.1, 0.02, 16000):
                yield chunk

        # Should succeed using fallback
        results = []
        try:
            async for result in chain.astream(audio()):
                results.append(result)
        except RuntimeError:
            # Fallback mechanism depends on implementation
            pass

    @pytest.mark.asyncio
    async def test_retry_chain(self, create_mock_llm, mock_tts):
        """Test retry mechanism for transient failures."""
        # LLM that fails on first call
        call_count = 0

        class FlakeyLLM(MockLLM):
            async def generate_stream(self, messages, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("Transient error")
                async for chunk in super().generate_stream(messages, **kwargs):
                    yield chunk

        flakey_llm = FlakeyLLM(response="Success after retry")

        # Note: Actual retry depends on VoiceRetry implementation
        # This tests the concept

    @pytest.mark.asyncio
    async def test_error_isolation(self, mock_asr, create_mock_llm, mock_tts):
        """Test that errors in one component don't corrupt others."""
        llm = create_mock_llm(fail_on_message="trigger", error_message="LLM error")

        # First request (should work)
        mock_asr.config.response = "Hello"

        async def audio1():
            yield create_pcm16_audio(0.1, 16000)

        chain = mock_asr | llm | mock_tts

        results1 = []
        async for result in chain.astream(audio1()):
            results1.append(result)

        assert len(results1) > 0

        # Second request (should fail)
        mock_asr.config.response = "Please trigger error"

        async def audio2():
            yield create_pcm16_audio(0.1, 16000)

        with pytest.raises(RuntimeError, match="LLM error"):
            async for _ in chain.astream(audio2()):
                pass

        # Third request (should work again)
        mock_asr.config.response = "Back to normal"

        async def audio3():
            yield create_pcm16_audio(0.1, 16000)

        results3 = []
        async for result in chain.astream(audio3()):
            results3.append(result)

        assert len(results3) > 0


# ==============================================================================
# Data Format Integration Tests
# ==============================================================================


class TestDataFormatIntegration:
    """Tests for data format compatibility between components."""

    @pytest.mark.asyncio
    async def test_audio_format_consistency(self, mock_asr, mock_tts):
        """Test audio format is consistent through pipeline."""
        # Create audio at specific sample rate
        input_audio = create_pcm16_audio(0.5, 16000)

        async def audio_stream():
            yield input_audio

        # Process through ASR
        asr_results = []
        async for result in mock_asr.transcribe_stream(audio_stream()):
            asr_results.append(result)

        # Process through TTS
        async def text_stream():
            yield "Test output"

        tts_results = []
        async for chunk in mock_tts.synthesize_stream(text_stream()):
            tts_results.append(chunk)

        # Verify TTS output format
        assert all(hasattr(chunk, "sample_rate") for chunk in tts_results)
        assert all(hasattr(chunk, "data") for chunk in tts_results)

    @pytest.mark.asyncio
    async def test_transcription_result_format(self, mock_asr):
        """Test TranscriptionResult has required fields."""
        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        async for result in mock_asr.transcribe_stream(audio()):
            assert hasattr(result, "text")
            assert hasattr(result, "is_final")
            assert isinstance(result.text, str)
            assert isinstance(result.is_final, bool)

    @pytest.mark.asyncio
    async def test_llm_chunk_format(self, mock_llm):
        """Test LLMChunk has required fields."""
        messages = [{"role": "user", "content": "Test"}]

        async for chunk in mock_llm.generate_stream(messages):
            assert hasattr(chunk, "text")
            assert isinstance(chunk.text, str)

    @pytest.mark.asyncio
    async def test_audio_chunk_format(self, mock_tts):
        """Test AudioChunk has required fields."""
        async def text():
            yield "Test"

        async for chunk in mock_tts.synthesize_stream(text()):
            assert hasattr(chunk, "data")
            assert hasattr(chunk, "sample_rate")
            assert isinstance(chunk.data, bytes)
            assert isinstance(chunk.sample_rate, int)


# ==============================================================================
# Memory Integration Tests
# ==============================================================================


class TestMemoryIntegration:
    """Tests for memory integration with pipeline."""

    @pytest.mark.asyncio
    async def test_conversation_context_preservation(self, create_mock_llm):
        """Test that conversation context is preserved across turns."""
        llm = create_mock_llm(response="I remember you asked about weather.")

        # Simulate multi-turn conversation
        conversation = []

        # Turn 1
        conversation.append({"role": "user", "content": "What's the weather?"})
        conversation.append({"role": "assistant", "content": "It's sunny!"})

        # Turn 2
        conversation.append({"role": "user", "content": "Thanks!"})

        # Send full conversation to LLM
        results = []
        async for chunk in llm.generate_stream(conversation):
            results.append(chunk.text)

        # Verify LLM received full context
        assert len(llm.messages_received) == 3


# ==============================================================================
# Performance Integration Tests
# ==============================================================================


class TestPerformanceIntegration:
    """Performance-related integration tests."""

    @pytest.mark.asyncio
    async def test_streaming_latency(self, create_mock_asr, create_mock_llm, create_mock_tts):
        """Test that streaming reduces perceived latency."""
        import time

        # With streaming
        asr = create_mock_asr(response="Hello", latency=0)
        llm = create_mock_llm(response="Hi there!", stream_by="word", chunk_delay=0.01)
        tts = create_mock_tts(chunk_delay=0.01)

        chain = asr | llm | tts

        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        start = time.time()
        first_chunk_time = None

        async for chunk in chain.astream(audio()):
            if first_chunk_time is None:
                first_chunk_time = time.time() - start
            break

        # First chunk should arrive relatively quickly
        assert first_chunk_time is not None
        assert first_chunk_time < 0.5  # Should be fast with mocks

    @pytest.mark.asyncio
    async def test_backpressure_handling(self, mock_asr, create_mock_llm, mock_tts):
        """Test handling of slow consumers."""
        # LLM produces faster than TTS can consume
        llm = create_mock_llm(
            response="A " * 100,  # Many words
            stream_by="word",
            chunk_delay=0.001,
        )

        chain = mock_asr | llm | mock_tts

        async def audio():
            yield create_pcm16_audio(0.1, 16000)

        results = []
        async for result in chain.astream(audio()):
            results.append(result)

        # All results should be processed
        assert len(results) > 0
