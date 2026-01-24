"""Serialization utilities with msgpack support.

This module provides efficient serialization using msgpack as an alternative
to JSON. Based on the paper "Toward Low-Latency End-to-End Voice Agents"
which reports 0.8-1.0s savings using binary serialization.

Msgpack advantages:
- ~10x faster serialization/deserialization than JSON
- ~50% smaller message size
- Native binary support (important for audio data)
- Type preservation (int vs float)

Usage:
    >>> from voice_pipeline.utils.serialization import serialize, deserialize
    >>>
    >>> # Using msgpack (default, faster)
    >>> data = {"text": "hello", "score": 0.95}
    >>> encoded = serialize(data)
    >>> decoded = deserialize(encoded)
    >>>
    >>> # Using JSON (for compatibility)
    >>> encoded = serialize(data, format="json")
    >>> decoded = deserialize(encoded, format="json")
"""

import json
import logging
from dataclasses import dataclass, asdict, is_dataclass
from enum import Enum
from typing import Any, Optional, TypeVar, Union

logger = logging.getLogger(__name__)


class SerializationFormat(str, Enum):
    """Serialization format."""

    MSGPACK = "msgpack"
    """Binary msgpack format (faster, smaller)."""

    JSON = "json"
    """JSON text format (compatible, human-readable)."""


# Global default format
_default_format: SerializationFormat = SerializationFormat.MSGPACK


def set_default_format(format: Union[str, SerializationFormat]) -> None:
    """Set the default serialization format globally.

    Args:
        format: "msgpack" or "json"

    Example:
        >>> set_default_format("json")  # Use JSON by default
        >>> set_default_format("msgpack")  # Use msgpack by default
    """
    global _default_format
    if isinstance(format, str):
        format = SerializationFormat(format)
    _default_format = format


def get_default_format() -> SerializationFormat:
    """Get the current default serialization format.

    Returns:
        Current default format (msgpack or json).
    """
    return _default_format


def _has_msgpack() -> bool:
    """Check if msgpack is available."""
    try:
        import msgpack
        return True
    except ImportError:
        return False


def _prepare_for_serialization(obj: Any) -> Any:
    """Prepare object for serialization.

    Handles special types like dataclasses, enums, bytes, etc.

    Args:
        obj: Object to prepare.

    Returns:
        JSON/msgpack serializable object.
    """
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, bytes):
        # For msgpack, bytes are native
        # For JSON, we need to encode
        return obj

    if isinstance(obj, Enum):
        return obj.value

    if is_dataclass(obj) and not isinstance(obj, type):
        return _prepare_for_serialization(asdict(obj))

    if isinstance(obj, dict):
        return {
            _prepare_for_serialization(k): _prepare_for_serialization(v)
            for k, v in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [_prepare_for_serialization(item) for item in obj]

    if hasattr(obj, "to_dict"):
        return _prepare_for_serialization(obj.to_dict())

    if hasattr(obj, "__dict__"):
        return _prepare_for_serialization(obj.__dict__)

    # Fallback: convert to string
    return str(obj)


def serialize(
    data: Any,
    format: Optional[Union[str, SerializationFormat]] = None,
) -> bytes:
    """Serialize data to bytes.

    Args:
        data: Data to serialize (dict, list, dataclass, etc.).
        format: Serialization format ("msgpack" or "json").
                Defaults to global default (msgpack).

    Returns:
        Serialized bytes.

    Raises:
        ValueError: If format is invalid.
        ImportError: If msgpack is requested but not installed.

    Example:
        >>> data = {"message": "hello", "timestamp": 1234567890}
        >>> serialized = serialize(data)  # Uses msgpack
        >>> serialized = serialize(data, format="json")  # Uses JSON
    """
    if format is None:
        format = _default_format
    elif isinstance(format, str):
        format = SerializationFormat(format)

    # Prepare data for serialization
    prepared = _prepare_for_serialization(data)

    if format == SerializationFormat.MSGPACK:
        if not _has_msgpack():
            raise ImportError(
                "msgpack is required for msgpack serialization. "
                "Install with: pip install msgpack"
            )

        import msgpack
        return msgpack.packb(prepared, use_bin_type=True)

    elif format == SerializationFormat.JSON:
        return json.dumps(prepared, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    else:
        raise ValueError(f"Unknown format: {format}")


def deserialize(
    data: bytes,
    format: Optional[Union[str, SerializationFormat]] = None,
) -> Any:
    """Deserialize bytes to data.

    Args:
        data: Bytes to deserialize.
        format: Serialization format ("msgpack" or "json").
                Defaults to global default (msgpack).

    Returns:
        Deserialized data.

    Raises:
        ValueError: If format is invalid or data is corrupted.
        ImportError: If msgpack is requested but not installed.

    Example:
        >>> serialized = serialize({"key": "value"})
        >>> data = deserialize(serialized)
        >>> print(data)  # {"key": "value"}
    """
    if format is None:
        format = _default_format
    elif isinstance(format, str):
        format = SerializationFormat(format)

    if format == SerializationFormat.MSGPACK:
        if not _has_msgpack():
            raise ImportError(
                "msgpack is required for msgpack deserialization. "
                "Install with: pip install msgpack"
            )

        import msgpack
        return msgpack.unpackb(data, raw=False)

    elif format == SerializationFormat.JSON:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data)

    else:
        raise ValueError(f"Unknown format: {format}")


def serialize_to_string(
    data: Any,
    format: Optional[Union[str, SerializationFormat]] = None,
) -> str:
    """Serialize data to string (for text protocols).

    For msgpack, returns base64-encoded string.
    For JSON, returns JSON string.

    Args:
        data: Data to serialize.
        format: Serialization format.

    Returns:
        Serialized string.

    Example:
        >>> data = {"key": "value"}
        >>> s = serialize_to_string(data, format="json")
        >>> print(s)  # '{"key":"value"}'
    """
    if format is None:
        format = _default_format
    elif isinstance(format, str):
        format = SerializationFormat(format)

    serialized = serialize(data, format=format)

    if format == SerializationFormat.MSGPACK:
        import base64
        return base64.b64encode(serialized).decode("ascii")
    else:
        return serialized.decode("utf-8")


def deserialize_from_string(
    data: str,
    format: Optional[Union[str, SerializationFormat]] = None,
) -> Any:
    """Deserialize from string.

    Args:
        data: String to deserialize.
        format: Serialization format.

    Returns:
        Deserialized data.

    Example:
        >>> s = '{"key":"value"}'
        >>> data = deserialize_from_string(s, format="json")
    """
    if format is None:
        format = _default_format
    elif isinstance(format, str):
        format = SerializationFormat(format)

    if format == SerializationFormat.MSGPACK:
        import base64
        return deserialize(base64.b64decode(data), format=format)
    else:
        return deserialize(data.encode("utf-8"), format=format)


@dataclass
class SerializedMessage:
    """A message with metadata for serialization.

    Useful for WebSocket and queue communication where
    you need to include metadata like message type, timestamp, etc.

    Attributes:
        type: Message type identifier.
        payload: Message payload (any serializable data).
        timestamp: Unix timestamp (auto-generated if not provided).
        metadata: Additional metadata.

    Example:
        >>> msg = SerializedMessage(
        ...     type="transcript",
        ...     payload={"text": "Hello", "is_final": True},
        ... )
        >>> encoded = msg.to_bytes()
        >>> decoded = SerializedMessage.from_bytes(encoded)
    """

    type: str
    """Message type identifier."""

    payload: Any
    """Message payload."""

    timestamp: Optional[float] = None
    """Unix timestamp."""

    metadata: Optional[dict[str, Any]] = None
    """Additional metadata."""

    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            import time
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def to_bytes(
        self,
        format: Optional[Union[str, SerializationFormat]] = None,
    ) -> bytes:
        """Serialize to bytes.

        Args:
            format: Serialization format.

        Returns:
            Serialized bytes.
        """
        return serialize(self.to_dict(), format=format)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        format: Optional[Union[str, SerializationFormat]] = None,
    ) -> "SerializedMessage":
        """Deserialize from bytes.

        Args:
            data: Bytes to deserialize.
            format: Serialization format.

        Returns:
            SerializedMessage instance.
        """
        d = deserialize(data, format=format)
        return cls(
            type=d["type"],
            payload=d["payload"],
            timestamp=d.get("timestamp"),
            metadata=d.get("metadata"),
        )

    def to_string(
        self,
        format: Optional[Union[str, SerializationFormat]] = None,
    ) -> str:
        """Serialize to string."""
        return serialize_to_string(self.to_dict(), format=format)

    @classmethod
    def from_string(
        cls,
        data: str,
        format: Optional[Union[str, SerializationFormat]] = None,
    ) -> "SerializedMessage":
        """Deserialize from string."""
        d = deserialize_from_string(data, format=format)
        return cls(
            type=d["type"],
            payload=d["payload"],
            timestamp=d.get("timestamp"),
            metadata=d.get("metadata"),
        )


class MessageSerializer:
    """Serializer for queue/websocket messages with configurable format.

    Provides a convenient interface for serializing messages in
    async queues and WebSocket communication.

    Example:
        >>> serializer = MessageSerializer(format="msgpack")
        >>>
        >>> # Serialize
        >>> encoded = serializer.pack({"text": "hello"})
        >>>
        >>> # Deserialize
        >>> data = serializer.unpack(encoded)
        >>>
        >>> # Create typed messages
        >>> msg = serializer.create_message("transcript", {"text": "hello"})
        >>> encoded = serializer.pack_message(msg)
    """

    def __init__(
        self,
        format: Union[str, SerializationFormat] = SerializationFormat.MSGPACK,
    ):
        """Initialize serializer.

        Args:
            format: Serialization format ("msgpack" or "json").
        """
        if isinstance(format, str):
            format = SerializationFormat(format)
        self.format = format

    def pack(self, data: Any) -> bytes:
        """Serialize data to bytes.

        Args:
            data: Data to serialize.

        Returns:
            Serialized bytes.
        """
        return serialize(data, format=self.format)

    def unpack(self, data: bytes) -> Any:
        """Deserialize bytes to data.

        Args:
            data: Bytes to deserialize.

        Returns:
            Deserialized data.
        """
        return deserialize(data, format=self.format)

    def pack_string(self, data: Any) -> str:
        """Serialize data to string."""
        return serialize_to_string(data, format=self.format)

    def unpack_string(self, data: str) -> Any:
        """Deserialize string to data."""
        return deserialize_from_string(data, format=self.format)

    def create_message(
        self,
        type: str,
        payload: Any,
        **metadata,
    ) -> SerializedMessage:
        """Create a typed message.

        Args:
            type: Message type.
            payload: Message payload.
            **metadata: Additional metadata.

        Returns:
            SerializedMessage instance.
        """
        return SerializedMessage(
            type=type,
            payload=payload,
            metadata=metadata if metadata else None,
        )

    def pack_message(self, message: SerializedMessage) -> bytes:
        """Serialize a message to bytes.

        Args:
            message: Message to serialize.

        Returns:
            Serialized bytes.
        """
        return message.to_bytes(format=self.format)

    def unpack_message(self, data: bytes) -> SerializedMessage:
        """Deserialize bytes to message.

        Args:
            data: Bytes to deserialize.

        Returns:
            SerializedMessage instance.
        """
        return SerializedMessage.from_bytes(data, format=self.format)


# Convenience instances
msgpack_serializer = MessageSerializer(SerializationFormat.MSGPACK)
json_serializer = MessageSerializer(SerializationFormat.JSON)
