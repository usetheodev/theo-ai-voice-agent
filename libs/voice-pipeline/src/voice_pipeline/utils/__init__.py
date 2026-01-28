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
from .retry import (
    RetryConfig,
    with_retry,
    retry_async,
    RateLimitError,
    ServiceUnavailableError,
    LLM_RETRY_CONFIG,
    LLM_EXTENDED_RETRY_CONFIG,
    RETRYABLE_EXCEPTIONS,
    EXTENDED_RETRYABLE_EXCEPTIONS,
)
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
    with_circuit_breaker,
    LLM_CIRCUIT_BREAKER,
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
    # Retry
    "RetryConfig",
    "with_retry",
    "retry_async",
    "RateLimitError",
    "ServiceUnavailableError",
    "LLM_RETRY_CONFIG",
    "LLM_EXTENDED_RETRY_CONFIG",
    "RETRYABLE_EXCEPTIONS",
    "EXTENDED_RETRYABLE_EXCEPTIONS",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitState",
    "with_circuit_breaker",
    "LLM_CIRCUIT_BREAKER",
]
