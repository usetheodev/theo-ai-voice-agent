"""Utilities for the voice pipeline."""

from .audio import (
    pcm16_to_float,
    float_to_pcm16,
    calculate_rms,
    calculate_db,
    resample_audio,
)
from .timing import Timer, measure_latency
from .serialization import (
    serialize,
    deserialize,
    serialize_to_string,
    deserialize_from_string,
    set_default_format,
    get_default_format,
    SerializationFormat,
    SerializedMessage,
    MessageSerializer,
    msgpack_serializer,
    json_serializer,
)

__all__ = [
    # Audio
    "pcm16_to_float",
    "float_to_pcm16",
    "calculate_rms",
    "calculate_db",
    "resample_audio",
    # Timing
    "Timer",
    "measure_latency",
    # Serialization
    "serialize",
    "deserialize",
    "serialize_to_string",
    "deserialize_from_string",
    "set_default_format",
    "get_default_format",
    "SerializationFormat",
    "SerializedMessage",
    "MessageSerializer",
    "msgpack_serializer",
    "json_serializer",
]
