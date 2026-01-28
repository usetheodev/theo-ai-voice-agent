"""Tests for WebRTC Transport."""

import asyncio
import sys
import os

import pytest
import numpy as np

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.webrtc.events import DataChannelEventEmitter, Event, EventType
from backend.webrtc.tracks import AudioOutputTrack, SAMPLE_RATE, FRAME_DURATION_MS


class TestDataChannelEventEmitter:
    """Tests for DataChannelEventEmitter."""

    def test_event_creation(self):
        """Test creating an event."""
        event = Event(type=EventType.CONNECTED, data={"message": "test"})
        assert event.type == EventType.CONNECTED
        assert event.data == {"message": "test"}
        assert event.timestamp > 0

    def test_event_msgpack_roundtrip(self):
        """Test event serialization/deserialization."""
        original = Event(
            type=EventType.LLM_TOKEN,
            data={"token": "hello"},
            sequence=42,
        )
        packed = original.to_msgpack()
        unpacked = Event.from_msgpack(packed)

        assert unpacked.type == original.type
        assert unpacked.data == original.data
        assert unpacked.sequence == original.sequence

    @pytest.mark.asyncio
    async def test_emitter_handler_registration(self):
        """Test registering event handlers."""
        emitter = DataChannelEventEmitter()
        received_events = []

        async def handler(event: Event):
            received_events.append(event)

        emitter.on(EventType.CONNECTED, handler)

        # Dispatch event manually
        await emitter._dispatch(Event(type=EventType.CONNECTED, data={}))

        assert len(received_events) == 1
        assert received_events[0].type == EventType.CONNECTED

    @pytest.mark.asyncio
    async def test_emitter_handler_unregistration(self):
        """Test unregistering event handlers."""
        emitter = DataChannelEventEmitter()
        received_events = []

        async def handler(event: Event):
            received_events.append(event)

        emitter.on(EventType.CONNECTED, handler)
        emitter.off(EventType.CONNECTED, handler)

        await emitter._dispatch(Event(type=EventType.CONNECTED, data={}))

        assert len(received_events) == 0


class TestAudioOutputTrack:
    """Tests for AudioOutputTrack."""

    def test_track_initialization(self):
        """Test track initialization."""
        track = AudioOutputTrack(sample_rate=24000)
        assert track.sample_rate == 24000
        assert track.channels == 1
        assert track.kind == "audio"

    @pytest.mark.asyncio
    async def test_write_frame(self):
        """Test writing audio frame."""
        track = AudioOutputTrack(sample_rate=16000)

        # Create test audio
        samples = int(16000 * FRAME_DURATION_MS / 1000)
        audio = np.zeros(samples, dtype=np.int16)
        audio_bytes = audio.tobytes()

        # Write frame
        await track.write_frame(audio_bytes)

        # Queue should have one item
        assert not track._queue.empty()

    def test_clear_queue(self):
        """Test clearing audio queue."""
        track = AudioOutputTrack()
        track._queue.put_nowait(b"test1")
        track._queue.put_nowait(b"test2")

        assert not track._queue.empty()

        track.clear_queue()

        assert track._queue.empty()

    @pytest.mark.asyncio
    async def test_recv_returns_frame(self):
        """Test that recv returns proper audio frame."""
        track = AudioOutputTrack(sample_rate=16000)

        # Write some audio
        samples = int(16000 * FRAME_DURATION_MS / 1000)
        audio = (np.random.randn(samples) * 1000).astype(np.int16)
        await track.write_frame(audio.tobytes())

        # Receive frame
        frame = await track.recv()

        assert frame is not None
        assert frame.sample_rate == 16000
        assert len(frame.planes) > 0


class TestEventTypes:
    """Tests for event type enumeration."""

    def test_all_event_types_have_values(self):
        """Test that all event types have string values."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)
            assert len(event_type.value) > 0

    def test_event_types_are_unique(self):
        """Test that all event type values are unique."""
        values = [e.value for e in EventType]
        assert len(values) == len(set(values))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
