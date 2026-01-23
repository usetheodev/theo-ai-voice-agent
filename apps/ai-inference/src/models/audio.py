"""Audio format models for the AI Inference service."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AudioFormat(str, Enum):
    """Supported audio formats."""

    PCM16 = "pcm16"
    G711_ULAW = "g711_ulaw"
    G711_ALAW = "g711_alaw"


class AudioChunk(BaseModel):
    """Represents a chunk of audio data."""

    data: bytes = Field(..., description="Raw audio data")
    format: AudioFormat = Field(default=AudioFormat.PCM16, description="Audio format")
    timestamp_ms: Optional[int] = Field(default=None, description="Timestamp in milliseconds")
    sample_rate: int = Field(default=24000, description="Sample rate in Hz")
    channels: int = Field(default=1, description="Number of audio channels")

    class Config:
        arbitrary_types_allowed = True


class AudioBuffer(BaseModel):
    """Buffer for accumulating audio chunks."""

    data: bytes = Field(default=b"", description="Accumulated audio data")
    format: AudioFormat = Field(default=AudioFormat.PCM16, description="Audio format")
    total_duration_ms: int = Field(default=0, description="Total duration in milliseconds")
    sample_rate: int = Field(default=24000, description="Sample rate in Hz")

    class Config:
        arbitrary_types_allowed = True

    def append(self, chunk: bytes) -> None:
        """Append audio data to the buffer."""
        self.data += chunk
        # Calculate duration based on PCM16 format (2 bytes per sample)
        if self.format == AudioFormat.PCM16:
            samples = len(chunk) // 2
            self.total_duration_ms += int((samples / self.sample_rate) * 1000)

    def clear(self) -> None:
        """Clear the buffer."""
        self.data = b""
        self.total_duration_ms = 0

    def get_data(self) -> bytes:
        """Get the accumulated audio data."""
        return self.data

    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return len(self.data) == 0
