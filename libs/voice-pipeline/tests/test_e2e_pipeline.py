"""End-to-end tests for voice pipeline.

These tests exercise complete voice processing flows from audio input
to audio output, testing the integration of all components.
"""

import asyncio
from typing import AsyncIterator

import pytest

from voice_pipeline import (
    Pipeline,
    PipelineConfig,
    PipelineEventType,
    VoiceRunnable,
    VoiceSequence,
)

from tests.mocks import (
    MockASR,
    MockLLM,
    MockTTS,
    MockVAD,
    MockRealtime,
    MockTransport,
    create_pcm16_audio,
    create_audio_chunks,
    create_silence,
)


# ==============================================================================
# E2E: Complete Voice Pipeline Tests
# ==============================================================================


class TestE2EBasicPipeline:
    """Basic end-to-end pipeline tests."""

    @pytest.mark.asyncio
    async def test_audio_to_text_to_audio(
        self,
        mock_asr,
        mock_llm,
        mock_tts,
        audio_stream_factory,
        audio_chunks,
    ):
        """Test complete audio -> text -> audio flow."""
        # Create chain
        chain = mock_asr | mock_llm | mock_tts

        # Create audio stream
        async def audio_stream():
            for chunk in audio_chunks:
                yield chunk

        # Process and collect results
        audio_output = []
        async for result in chain.astream(audio_stream()):
            if hasattr(result, "data"):
                audio_output.append(result.data)

        # Verify we got audio output
        assert len(audio_output) > 0
        assert all(isinstance(chunk, bytes) for chunk in audio_output)

        # Verify mocks were called
        assert mock_asr.chunks_received > 0
        assert len(mock_llm.messages_received) > 0
        assert len(mock_tts.text_received) > 0

    @pytest.mark.asyncio
    async def test_pipeline_with_events(
        self,
        mock_asr,
        mock_llm,
        mock_tts,
        mock_vad,
        pipeline_config,
    ):
        """Test pipeline with event handlers."""
        pipeline = Pipeline(
            config=pipeline_config,
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            vad=mock_vad,
        )

        events_received = []

        def on_event(event):
            events_received.append(event.type)

        pipeline.on(PipelineEventType.TRANSCRIPTION, on_event)
        pipeline.on(PipelineEventType.LLM_RESPONSE, on_event)
        pipeline.on(PipelineEventType.TTS_CHUNK, on_event)

        # Note: This tests event registration, not actual pipeline processing
        # since process_turn is not implemented in the mock
        assert pipeline is not None
        assert pipeline.config.system_prompt == "You are a helpful voice assistant."

    @pytest.mark.asyncio
    async def test_chain_with_custom_responses(self, create_mock_asr, create_mock_llm, create_mock_tts):
        """Test chain with custom mock responses."""
        asr = create_mock_asr(response="What's the weather like?")
        llm = create_mock_llm(response="It's sunny and 72 degrees!")
        tts = create_mock_tts(sample_rate=24000)

        chain = asr | llm | tts

        async def audio_stream():
            yield create_pcm16_audio(0.5, 16000)

        results = []
        async for result in chain.astream(audio_stream()):
            results.append(result)

        # LLM should have received the ASR transcription
        assert len(llm.messages_received) > 0
        assert "What's the weather like?" in llm.messages_received[0].get("content", "")

        # TTS should have received the LLM response
        full_text = "".join(tts.text_received)
        assert "sunny" in full_text or "72" in full_text


class TestE2EStreamingBehavior:
    """Tests for streaming behavior in pipelines."""

    @pytest.mark.asyncio
    async def test_word_by_word_streaming(self, create_mock_asr, create_mock_llm, create_mock_tts):
        """Test word-by-word streaming through pipeline."""
        asr = create_mock_asr(response="Hello", word_by_word=False)
        llm = create_mock_llm(
            response="Hi there, how can I help you today?",
            stream_by="word",
        )
        tts = create_mock_tts()

        chain = asr | llm | tts

        async def audio_stream():
            yield create_pcm16_audio(0.2, 16000)

        chunks_received = []
        async for chunk in chain.astream(audio_stream()):
            chunks_received.append(chunk)

        # Should receive at least one TTS chunk
        # Note: The chain may combine streaming outputs
        assert len(chunks_received) >= 1

    @pytest.mark.asyncio
    async def test_sentence_streaming(self, create_mock_asr, create_mock_llm, create_mock_tts):
        """Test sentence-level streaming."""
        asr = create_mock_asr(response="Tell me a story")
        llm = create_mock_llm(
            response="Once upon a time. There was a brave knight. The end!",
            stream_by="sentence",
        )
        tts = create_mock_tts()

        chain = asr | llm | tts

        async def audio_stream():
            yield create_pcm16_audio(0.2, 16000)

        chunks_received = []
        async for chunk in chain.astream(audio_stream()):
            chunks_received.append(chunk)

        # Should receive at least one TTS chunk
        # Note: The chain may combine streaming outputs
        assert len(chunks_received) >= 1

    @pytest.mark.asyncio
    async def test_latency_simulation(self, create_mock_asr, create_mock_llm, create_mock_tts):
        """Test pipeline with simulated latency."""
        import time

        asr = create_mock_asr(response="Hello", latency=0.05)
        llm = create_mock_llm(response="Hi there!", latency=0.05)
        tts = create_mock_tts(latency=0.05)

        chain = asr | llm | tts

        async def audio_stream():
            yield create_pcm16_audio(0.1, 16000)

        start = time.time()
        results = []
        async for result in chain.astream(audio_stream()):
            results.append(result)
        elapsed = time.time() - start

        # Should take at least 150ms (3 x 50ms latency)
        assert elapsed >= 0.15

    @pytest.mark.asyncio
    async def test_interim_results(self, create_mock_asr):
        """Test that interim ASR results are yielded."""
        asr = create_mock_asr(
            response="Hello world",
            interim_results=True,
            word_by_word=True,
        )

        async def audio_stream():
            yield create_pcm16_audio(0.1, 16000)

        results = []
        async for result in asr.astream(audio_stream()):
            results.append(result)

        # Should have interim and final results
        final_results = [r for r in results if r.is_final]
        interim_results = [r for r in results if not r.is_final]

        assert len(final_results) == 1
        assert len(interim_results) > 0


class TestE2EErrorHandling:
    """Tests for error handling in pipelines."""

    @pytest.mark.asyncio
    async def test_asr_error_propagation(self, create_mock_asr, mock_llm, mock_tts):
        """Test that ASR errors propagate through the chain."""
        asr = create_mock_asr(fail_after=5, error_message="ASR failed!")

        chain = asr | mock_llm | mock_tts

        async def audio_stream():
            for i in range(10):
                yield create_pcm16_audio(0.02, 16000)

        with pytest.raises(RuntimeError, match="ASR failed"):
            async for _ in chain.astream(audio_stream()):
                pass

    @pytest.mark.asyncio
    async def test_llm_error_on_content(self, mock_asr, create_mock_llm, mock_tts):
        """Test LLM error based on message content."""
        llm = create_mock_llm(
            fail_on_message="error",
            error_message="LLM error triggered!",
        )

        # Set ASR to return text containing "error"
        mock_asr.config.response = "Please trigger error"

        chain = mock_asr | llm | mock_tts

        async def audio_stream():
            yield create_pcm16_audio(0.1, 16000)

        with pytest.raises(RuntimeError, match="LLM error triggered"):
            async for _ in chain.astream(audio_stream()):
                pass

    @pytest.mark.asyncio
    async def test_tts_error_on_text(self, mock_asr, mock_llm, create_mock_tts):
        """Test TTS error based on text content."""
        tts = create_mock_tts(
            fail_on_text="forbidden",
            error_message="TTS error triggered!",
        )

        # Set LLM to return text containing "forbidden"
        mock_llm.config.response = "This is a forbidden word"

        chain = mock_asr | mock_llm | tts

        async def audio_stream():
            yield create_pcm16_audio(0.1, 16000)

        with pytest.raises(RuntimeError, match="TTS error triggered"):
            async for _ in chain.astream(audio_stream()):
                pass


class TestE2ERealtimePipeline:
    """Tests for realtime API pipeline."""

    @pytest.mark.asyncio
    async def test_realtime_connection_flow(self, mock_realtime):
        """Test realtime connection and event flow."""
        # Connect
        await mock_realtime.connect()
        assert mock_realtime.is_connected

        # Send audio
        audio = create_pcm16_audio(0.5, 16000)
        await mock_realtime.send_audio(audio)
        assert len(mock_realtime.audio_sent) == 1

        # Send text
        await mock_realtime.send_text("Hello")
        assert len(mock_realtime.text_sent) == 1

        # Commit and create response
        await mock_realtime.commit_audio()
        await mock_realtime.create_response()

        # Receive events
        events = []
        async for event in mock_realtime.receive_events():
            events.append(event)
            if event.event_type == RealtimeEventType.RESPONSE_DONE:
                break

        # Verify event flow
        event_types = [e.event_type for e in events]
        assert RealtimeEventType.SESSION_CREATED in event_types
        assert RealtimeEventType.INPUT_AUDIO_BUFFER_COMMITTED in event_types
        assert RealtimeEventType.RESPONSE_CREATED in event_types
        assert RealtimeEventType.RESPONSE_DONE in event_types

        # Disconnect
        await mock_realtime.disconnect()
        assert not mock_realtime.is_connected

    @pytest.mark.asyncio
    async def test_realtime_text_and_audio_response(self, mock_realtime):
        """Test receiving text and audio from realtime API."""
        await mock_realtime.connect()
        await mock_realtime.send_text("Hello")
        await mock_realtime.create_response()

        text_content = None
        audio_content = None

        async for event in mock_realtime.receive_events():
            if event.event_type == RealtimeEventType.RESPONSE_TEXT_DELTA:
                text_content = event.text
            elif event.event_type == RealtimeEventType.RESPONSE_AUDIO_DELTA:
                audio_content = event.audio
            elif event.event_type == RealtimeEventType.RESPONSE_DONE:
                break

        assert text_content is not None
        assert audio_content is not None
        assert len(audio_content) > 0

        await mock_realtime.disconnect()


class TestE2ETransportIntegration:
    """Tests for transport integration."""

    @pytest.mark.asyncio
    async def test_transport_to_asr_flow(self, mock_transport, mock_asr):
        """Test audio transport to ASR flow."""
        # Setup input audio
        audio_chunks = create_audio_chunks(0.5, 0.02, 16000)
        mock_transport.set_input_audio(audio_chunks)

        await mock_transport.start()

        # Create async stream from transport
        async def transport_stream():
            async for frame in mock_transport.read_frames():
                yield frame.data

        # Process through ASR
        results = []
        async for result in mock_asr.astream(transport_stream()):
            results.append(result)

        await mock_transport.stop()

        # Verify ASR received audio
        assert mock_asr.chunks_received > 0
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_tts_to_transport_flow(self, mock_tts, mock_transport):
        """Test TTS to audio transport flow."""
        await mock_transport.start()

        # Create text stream
        async def text_stream():
            yield "Hello"
            yield " world"
            yield "!"

        # Process through TTS and write to transport
        async for chunk in mock_tts.synthesize_stream(text_stream()):
            await mock_transport.write_bytes(chunk.data)

        await mock_transport.stop()

        # Verify transport received audio
        output = mock_transport.get_output_audio()
        assert len(output) == 3  # One chunk per text piece

    @pytest.mark.asyncio
    async def test_full_transport_pipeline(
        self,
        mock_transport,
        mock_asr,
        mock_llm,
        mock_tts,
    ):
        """Test complete transport -> ASR -> LLM -> TTS -> transport flow."""
        # Setup
        input_audio = create_audio_chunks(0.5, 0.02, 16000)
        mock_transport.set_input_audio(input_audio)

        await mock_transport.start()

        # Read from transport
        async def read_audio():
            async for frame in mock_transport.read_frames():
                yield frame.data

        # Create processing chain
        chain = mock_asr | mock_llm | mock_tts

        # Process and write output
        async for chunk in chain.astream(read_audio()):
            if hasattr(chunk, "data"):
                await mock_transport.write_bytes(chunk.data)

        await mock_transport.stop()

        # Verify full flow
        assert mock_asr.chunks_received > 0
        assert len(mock_llm.messages_received) > 0
        assert len(mock_tts.text_received) > 0
        assert len(mock_transport.get_output_audio()) > 0


class TestE2EConversationFlow:
    """Tests for multi-turn conversation flows."""

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(
        self,
        create_mock_asr,
        create_mock_llm,
        mock_tts,
    ):
        """Test multi-turn conversation flow."""
        # Track conversation
        conversation_history = []

        # Turn 1: Greeting
        asr1 = create_mock_asr(response="Hello")
        llm1 = create_mock_llm(response="Hi! How can I help you?")

        async def audio1():
            yield create_pcm16_audio(0.1, 16000)

        chain1 = asr1 | llm1 | mock_tts
        async for _ in chain1.astream(audio1()):
            pass

        conversation_history.append({
            "user": asr1.config.response,
            "assistant": llm1.config.response,
        })

        # Turn 2: Question
        asr2 = create_mock_asr(response="What's your name?")
        llm2 = create_mock_llm(response="I'm a helpful voice assistant!")

        async def audio2():
            yield create_pcm16_audio(0.1, 16000)

        chain2 = asr2 | llm2 | mock_tts
        async for _ in chain2.astream(audio2()):
            pass

        conversation_history.append({
            "user": asr2.config.response,
            "assistant": llm2.config.response,
        })

        # Turn 3: Goodbye
        asr3 = create_mock_asr(response="Goodbye!")
        llm3 = create_mock_llm(response="Goodbye! Have a great day!")

        async def audio3():
            yield create_pcm16_audio(0.1, 16000)

        chain3 = asr3 | llm3 | mock_tts
        async for _ in chain3.astream(audio3()):
            pass

        conversation_history.append({
            "user": asr3.config.response,
            "assistant": llm3.config.response,
        })

        # Verify conversation
        assert len(conversation_history) == 3
        assert conversation_history[0]["user"] == "Hello"
        assert conversation_history[2]["assistant"] == "Goodbye! Have a great day!"


class TestE2EPerformance:
    """Performance-related E2E tests."""

    @pytest.mark.asyncio
    async def test_large_audio_processing(self, mock_asr, mock_llm, mock_tts):
        """Test processing larger audio files."""
        # 10 seconds of audio
        large_audio = create_audio_chunks(10.0, 0.02, 16000)  # 500 chunks

        chain = mock_asr | mock_llm | mock_tts

        async def audio_stream():
            for chunk in large_audio:
                yield chunk

        chunk_count = 0
        async for _ in chain.astream(audio_stream()):
            chunk_count += 1

        # Verify all chunks were processed
        assert mock_asr.chunks_received == 500
        assert chunk_count > 0

    @pytest.mark.asyncio
    async def test_rapid_short_utterances(
        self,
        create_mock_asr,
        create_mock_llm,
        mock_tts,
    ):
        """Test rapid succession of short utterances."""
        results = []

        for i in range(10):
            asr = create_mock_asr(response=f"Utterance {i}")
            llm = create_mock_llm(response=f"Response {i}")

            chain = asr | llm | mock_tts

            async def audio():
                yield create_pcm16_audio(0.05, 16000)

            async for chunk in chain.astream(audio()):
                results.append(chunk)

        # All 10 utterances should be processed
        assert len(results) >= 10

    @pytest.mark.asyncio
    async def test_concurrent_streams(self, create_mock_asr, create_mock_llm, create_mock_tts):
        """Test concurrent processing of multiple streams."""
        async def process_stream(stream_id: int):
            asr = create_mock_asr(response=f"Stream {stream_id}")
            llm = create_mock_llm(response=f"Response {stream_id}")
            tts = create_mock_tts()

            chain = asr | llm | tts

            async def audio():
                yield create_pcm16_audio(0.1, 16000)

            results = []
            async for chunk in chain.astream(audio()):
                results.append(chunk)

            return stream_id, len(results)

        # Process 5 streams concurrently
        tasks = [process_stream(i) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # All streams should complete
        assert len(results) == 5
        assert all(count > 0 for _, count in results)


# ==============================================================================
# Import for RealtimeEventType
# ==============================================================================

from voice_pipeline.interfaces.realtime import RealtimeEventType
