"""
Unit Tests for Phase 2.1: Conversational Intelligence Components

Tests cover:
1. SimpleTurnAnalyzer (end-of-turn detection)
2. MinDurationInterruptionStrategy (smart barge-in)
3. Integration scenarios

Run with: pytest tests/audio/test_phase2_1_components.py -v
"""

import pytest
import time
import asyncio
import numpy as np

# Import Phase 2.1 components
from audio.turn import (
    BaseTurnAnalyzer,
    BaseTurnParams,
    SimpleTurnAnalyzer,
    SimpleTurnParams,
    EndOfTurnState,
)

from audio.interruptions import (
    BaseInterruptionStrategy,
    MinDurationInterruptionStrategy,
)


# ============================================================
# Test Fixtures
# ============================================================

@pytest.fixture
def sample_rate():
    """Sample rate for telephony audio (G.711 ulaw)."""
    return 8000


@pytest.fixture
def frame_duration_ms():
    """Standard RTP frame duration."""
    return 20  # 20ms


@pytest.fixture
def pcm_frame(sample_rate, frame_duration_ms):
    """Generate 20ms PCM audio frame (160 samples @ 8kHz)."""
    num_samples = sample_rate * frame_duration_ms // 1000
    audio = np.zeros(num_samples, dtype=np.int16)
    return audio.tobytes()


@pytest.fixture
def speech_frame(sample_rate, frame_duration_ms):
    """Generate 20ms speech-like audio frame (sine wave)."""
    num_samples = sample_rate * frame_duration_ms // 1000
    t = np.linspace(0, frame_duration_ms / 1000, num_samples)
    audio = (np.sin(2 * np.pi * 440 * t) * 1000).astype(np.int16)  # 440Hz sine
    return audio.tobytes()


# ============================================================
# SimpleTurnAnalyzer Tests
# ============================================================

class TestSimpleTurnAnalyzer:
    """Tests for SimpleTurnAnalyzer."""

    def test_initialization(self, sample_rate):
        """Test SimpleTurnAnalyzer initialization."""
        analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,
            min_duration=0.3
        )

        assert analyzer.sample_rate == sample_rate
        assert analyzer.params.pause_duration == 1.0
        assert analyzer.params.min_duration == 0.3
        assert analyzer.speech_triggered == False

    def test_speech_detection(self, sample_rate, speech_frame):
        """Test that speech triggers the analyzer."""
        analyzer = SimpleTurnAnalyzer(sample_rate=sample_rate)

        # Process speech frame
        state = analyzer.append_audio(speech_frame, is_speech=True)

        assert analyzer.speech_triggered == True
        assert state == EndOfTurnState.INCOMPLETE  # Not enough pause yet

    def test_short_pause_incomplete(self, sample_rate, speech_frame, pcm_frame):
        """Test that short pauses don't trigger end-of-turn."""
        analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,  # Need 1s pause
        )

        # Speak for 0.5s (25 frames @ 20ms)
        for _ in range(25):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Short pause: 0.3s (15 frames)
        for _ in range(15):
            state = analyzer.append_audio(pcm_frame, is_speech=False)

        # Should still be incomplete (need 1.0s pause)
        assert state == EndOfTurnState.INCOMPLETE

    def test_long_pause_complete(self, sample_rate, speech_frame, pcm_frame):
        """Test that long pauses trigger end-of-turn."""
        analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,  # Need 1s pause
            min_duration=0.3,    # Need 0.3s speech
        )

        # Speak for 0.5s (25 frames @ 20ms)
        for _ in range(25):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Long pause: 1.0s (50 frames)
        state = EndOfTurnState.INCOMPLETE
        for _ in range(50):
            state = analyzer.append_audio(pcm_frame, is_speech=False)

        # Should be complete after 1.0s pause
        assert state == EndOfTurnState.COMPLETE

    def test_too_short_speech_ignored(self, sample_rate, speech_frame, pcm_frame):
        """Test that very short speech is ignored (noise/cough)."""
        analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,
            min_duration=0.3,  # Need at least 0.3s speech
        )

        # Very short speech: 0.1s (5 frames)
        for _ in range(5):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Wait 1.0s pause (50 frames)
        state = EndOfTurnState.INCOMPLETE
        for _ in range(50):
            state = analyzer.append_audio(pcm_frame, is_speech=False)

        # Should be incomplete (speech too short, < 0.3s)
        assert state == EndOfTurnState.INCOMPLETE
        # Analyzer should auto-reset
        assert analyzer.speech_triggered == False

    def test_buffer_accumulation(self, sample_rate, speech_frame):
        """Test that audio buffer accumulates correctly."""
        analyzer = SimpleTurnAnalyzer(sample_rate=sample_rate)

        # Add 10 frames
        for _ in range(10):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Check buffer
        buffer = analyzer.get_buffer()
        assert len(buffer) == len(speech_frame) * 10

        # Check duration calculation
        duration = analyzer.get_buffer_duration()
        expected_duration = (10 * 20) / 1000  # 10 frames * 20ms = 0.2s
        assert abs(duration - expected_duration) < 0.01

    def test_clear_resets_state(self, sample_rate, speech_frame):
        """Test that clear() resets all state."""
        analyzer = SimpleTurnAnalyzer(sample_rate=sample_rate)

        # Generate some state
        for _ in range(10):
            analyzer.append_audio(speech_frame, is_speech=True)

        assert analyzer.speech_triggered == True
        assert len(analyzer.get_buffer()) > 0

        # Clear
        analyzer.clear()

        # Check reset
        assert analyzer.speech_triggered == False
        assert len(analyzer.get_buffer()) == 0

    @pytest.mark.asyncio
    async def test_analyze_end_of_turn(self, sample_rate, speech_frame, pcm_frame):
        """Test async analyze_end_of_turn method."""
        analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,
            min_duration=0.3,
        )

        # Speak for 0.5s
        for _ in range(25):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Check before pause
        state, metrics = await analyzer.analyze_end_of_turn()
        assert state == EndOfTurnState.INCOMPLETE

        # Add 1.0s pause
        for _ in range(50):
            analyzer.append_audio(pcm_frame, is_speech=False)

        # Check after pause
        state, metrics = await analyzer.analyze_end_of_turn()
        assert state == EndOfTurnState.COMPLETE
        assert metrics is not None
        assert 'speech_duration' in metrics
        assert metrics['speech_duration'] >= 0.3


# ============================================================
# MinDurationInterruptionStrategy Tests
# ============================================================

class TestMinDurationInterruptionStrategy:
    """Tests for MinDurationInterruptionStrategy."""

    def test_initialization(self):
        """Test MinDurationInterruptionStrategy initialization."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)
        assert strategy._min_duration == 0.8
        assert strategy._total_samples == 0

    @pytest.mark.asyncio
    async def test_short_speech_no_interrupt(self, sample_rate, speech_frame):
        """Test that short speech doesn't trigger interruption."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # Add 0.3s of speech (15 frames @ 20ms)
        for _ in range(15):
            await strategy.append_audio(speech_frame, sample_rate)

        # Check - should not interrupt (0.3s < 0.8s)
        should_interrupt = await strategy.should_interrupt()
        assert should_interrupt == False

    @pytest.mark.asyncio
    async def test_long_speech_interrupts(self, sample_rate, speech_frame):
        """Test that long speech triggers interruption."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # Add 1.0s of speech (50 frames @ 20ms)
        for _ in range(50):
            await strategy.append_audio(speech_frame, sample_rate)

        # Check - should interrupt (1.0s >= 0.8s)
        should_interrupt = await strategy.should_interrupt()
        assert should_interrupt == True

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, sample_rate, speech_frame):
        """Test that reset() clears accumulated state."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # Add speech
        for _ in range(50):
            await strategy.append_audio(speech_frame, sample_rate)

        assert strategy.get_current_duration() > 0

        # Reset
        await strategy.reset()

        # Check cleared
        assert strategy._total_samples == 0
        assert strategy.get_current_duration() == 0.0

    @pytest.mark.asyncio
    async def test_get_current_duration(self, sample_rate, speech_frame):
        """Test duration calculation."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # Add 0.5s of speech (25 frames @ 20ms)
        for _ in range(25):
            await strategy.append_audio(speech_frame, sample_rate)

        duration = strategy.get_current_duration()
        expected = 0.5
        assert abs(duration - expected) < 0.01  # Allow 10ms tolerance

    @pytest.mark.asyncio
    async def test_no_audio_no_interrupt(self, sample_rate):
        """Test that no audio means no interruption."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # Check without adding any audio
        should_interrupt = await strategy.should_interrupt()
        assert should_interrupt == False


# ============================================================
# Integration Tests
# ============================================================

class TestPhase21Integration:
    """Integration tests combining Turn Detection + Smart Barge-in."""

    @pytest.mark.asyncio
    async def test_full_conversation_flow(self, sample_rate, speech_frame, pcm_frame):
        """Test complete conversation flow with turn detection."""
        turn_analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,
            min_duration=0.3
        )

        # User speaks: "Hello, how are you?" (1.0s speech)
        for _ in range(50):
            state = turn_analyzer.append_audio(speech_frame, is_speech=True)
            assert state == EndOfTurnState.INCOMPLETE

        # User pauses (1.0s silence)
        for i in range(50):
            state = turn_analyzer.append_audio(pcm_frame, is_speech=False)
            if i < 49:
                assert state == EndOfTurnState.INCOMPLETE
            else:
                # Last frame should trigger completion
                assert state == EndOfTurnState.COMPLETE

        # Verify turn complete
        state, metrics = await turn_analyzer.analyze_end_of_turn()
        assert state == EndOfTurnState.COMPLETE
        assert metrics['speech_duration'] >= 0.3

        # Clear for next turn
        turn_analyzer.clear()
        assert turn_analyzer.speech_triggered == False

    @pytest.mark.asyncio
    async def test_barge_in_false_positive_prevention(self, sample_rate, speech_frame):
        """Test that smart barge-in prevents false positives."""
        strategy = MinDurationInterruptionStrategy(min_duration=0.8)

        # Scenario: Agent speaking, user coughs (0.2s)
        for _ in range(10):  # 10 frames * 20ms = 0.2s
            await strategy.append_audio(speech_frame, sample_rate)

        # Should NOT interrupt (0.2s < 0.8s)
        should_interrupt = await strategy.should_interrupt()
        assert should_interrupt == False

        await strategy.reset()

        # Scenario: Agent speaking, user interrupts: "Actually, no" (1.2s)
        for _ in range(60):  # 60 frames * 20ms = 1.2s
            await strategy.append_audio(speech_frame, sample_rate)

        # SHOULD interrupt (1.2s >= 0.8s)
        should_interrupt = await strategy.should_interrupt()
        assert should_interrupt == True

    @pytest.mark.asyncio
    async def test_turn_detection_with_multiple_pauses(self, sample_rate, speech_frame, pcm_frame):
        """Test turn detection handles mid-sentence pauses correctly."""
        analyzer = SimpleTurnAnalyzer(
            sample_rate=sample_rate,
            pause_duration=1.0,
            min_duration=0.3
        )

        # User speaks: "Hello" (0.3s)
        for _ in range(15):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Short pause (0.3s) - mid-sentence
        for _ in range(15):
            state = analyzer.append_audio(pcm_frame, is_speech=False)
            assert state == EndOfTurnState.INCOMPLETE  # Not long enough

        # Continue: "how are you?" (0.5s)
        for _ in range(25):
            analyzer.append_audio(speech_frame, is_speech=True)

        # Long pause (1.0s) - end of turn
        for i in range(50):
            state = analyzer.append_audio(pcm_frame, is_speech=False)
            if i < 49:
                assert state == EndOfTurnState.INCOMPLETE
            else:
                assert state == EndOfTurnState.COMPLETE


# ============================================================
# Run Tests
# ============================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
