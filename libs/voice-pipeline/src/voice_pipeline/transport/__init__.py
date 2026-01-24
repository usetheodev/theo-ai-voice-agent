"""Audio transport implementations.

Available transports:
- LocalAudioTransport: Local microphone/speaker using sounddevice
- FileAudioTransport: File-based I/O for testing

Example:
    >>> from voice_pipeline.transport import LocalAudioTransport
    >>>
    >>> async with LocalAudioTransport() as transport:
    ...     async for frame in transport.read_frames():
    ...         # Process audio from microphone
    ...         processed = await process(frame)
    ...         # Play back to speaker
    ...         await transport.write_frame(processed)
"""

from voice_pipeline.transport.local import (
    LocalAudioTransport,
    LocalAudioConfig,
)
from voice_pipeline.transport.file import (
    FileAudioTransport,
    FileAudioConfig,
    create_test_audio,
    create_silence,
)

__all__ = [
    # Local transport
    "LocalAudioTransport",
    "LocalAudioConfig",
    # File transport
    "FileAudioTransport",
    "FileAudioConfig",
    # Utilities
    "create_test_audio",
    "create_silence",
]
