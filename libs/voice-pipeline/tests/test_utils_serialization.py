"""Tests for serialization utilities with msgpack support."""

import pytest
from dataclasses import dataclass
from enum import Enum
import time


from voice_pipeline.utils.serialization import (
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
    _prepare_for_serialization,
    _has_msgpack,
)


# =============================================================================
# Test Data Fixtures
# =============================================================================


@dataclass
class SampleDataclass:
    """Sample dataclass for testing."""
    name: str
    value: int
    score: float


class SampleEnum(Enum):
    """Sample enum for testing."""
    OPTION_A = "a"
    OPTION_B = "b"


# =============================================================================
# Format Tests
# =============================================================================


class TestSerializationFormat:
    """Tests for SerializationFormat enum."""

    def test_format_values(self):
        """Test format enum values."""
        assert SerializationFormat.MSGPACK.value == "msgpack"
        assert SerializationFormat.JSON.value == "json"

    def test_format_from_string(self):
        """Test creating format from string."""
        assert SerializationFormat("msgpack") == SerializationFormat.MSGPACK
        assert SerializationFormat("json") == SerializationFormat.JSON


class TestDefaultFormat:
    """Tests for default format management."""

    def test_get_default_format(self):
        """Test getting default format."""
        original = get_default_format()

        # Default should be msgpack
        assert original in (SerializationFormat.MSGPACK, SerializationFormat.JSON)

    def test_set_default_format(self):
        """Test setting default format."""
        original = get_default_format()

        try:
            set_default_format("json")
            assert get_default_format() == SerializationFormat.JSON

            set_default_format(SerializationFormat.MSGPACK)
            assert get_default_format() == SerializationFormat.MSGPACK
        finally:
            # Restore original
            set_default_format(original)


# =============================================================================
# JSON Serialization Tests
# =============================================================================


class TestJSONSerialization:
    """Tests for JSON serialization."""

    def test_serialize_dict(self):
        """Test serializing a dictionary."""
        data = {"key": "value", "number": 42}
        serialized = serialize(data, format="json")

        assert isinstance(serialized, bytes)
        assert b"key" in serialized
        assert b"value" in serialized

    def test_deserialize_dict(self):
        """Test deserializing a dictionary."""
        data = {"key": "value", "number": 42}
        serialized = serialize(data, format="json")
        deserialized = deserialize(serialized, format="json")

        assert deserialized == data

    def test_serialize_list(self):
        """Test serializing a list."""
        data = [1, 2, 3, "four", 5.0]
        serialized = serialize(data, format="json")
        deserialized = deserialize(serialized, format="json")

        assert deserialized == data

    def test_serialize_nested(self):
        """Test serializing nested structures."""
        data = {
            "outer": {
                "inner": [1, 2, {"deep": "value"}]
            },
            "list": [{"a": 1}, {"b": 2}]
        }
        serialized = serialize(data, format="json")
        deserialized = deserialize(serialized, format="json")

        assert deserialized == data

    def test_serialize_unicode(self):
        """Test serializing unicode strings."""
        data = {"message": "Olá, 世界! 🌍"}
        serialized = serialize(data, format="json")
        deserialized = deserialize(serialized, format="json")

        assert deserialized == data

    def test_serialize_to_string(self):
        """Test serializing to string."""
        data = {"key": "value"}
        s = serialize_to_string(data, format="json")

        assert isinstance(s, str)
        assert "key" in s
        assert "value" in s

    def test_deserialize_from_string(self):
        """Test deserializing from string."""
        s = '{"key":"value"}'
        data = deserialize_from_string(s, format="json")

        assert data == {"key": "value"}


# =============================================================================
# Msgpack Serialization Tests
# =============================================================================


@pytest.mark.skipif(not _has_msgpack(), reason="msgpack not installed")
class TestMsgpackSerialization:
    """Tests for msgpack serialization."""

    def test_serialize_dict(self):
        """Test serializing a dictionary."""
        data = {"key": "value", "number": 42}
        serialized = serialize(data, format="msgpack")

        assert isinstance(serialized, bytes)
        # Msgpack is binary, not readable

    def test_deserialize_dict(self):
        """Test deserializing a dictionary."""
        data = {"key": "value", "number": 42}
        serialized = serialize(data, format="msgpack")
        deserialized = deserialize(serialized, format="msgpack")

        assert deserialized == data

    def test_serialize_list(self):
        """Test serializing a list."""
        data = [1, 2, 3, "four", 5.0]
        serialized = serialize(data, format="msgpack")
        deserialized = deserialize(serialized, format="msgpack")

        assert deserialized == data

    def test_serialize_nested(self):
        """Test serializing nested structures."""
        data = {
            "outer": {
                "inner": [1, 2, {"deep": "value"}]
            }
        }
        serialized = serialize(data, format="msgpack")
        deserialized = deserialize(serialized, format="msgpack")

        assert deserialized == data

    def test_serialize_bytes(self):
        """Test serializing bytes (important for audio)."""
        data = {"audio": b"\x00\x01\x02\x03\xff"}
        serialized = serialize(data, format="msgpack")
        deserialized = deserialize(serialized, format="msgpack")

        assert deserialized["audio"] == b"\x00\x01\x02\x03\xff"

    def test_serialize_to_string_base64(self):
        """Test serializing to base64 string."""
        data = {"key": "value"}
        s = serialize_to_string(data, format="msgpack")

        assert isinstance(s, str)
        # Should be base64 encoded

    def test_deserialize_from_string_base64(self):
        """Test deserializing from base64 string."""
        data = {"key": "value"}
        s = serialize_to_string(data, format="msgpack")
        deserialized = deserialize_from_string(s, format="msgpack")

        assert deserialized == data

    def test_msgpack_smaller_than_json(self):
        """Test that msgpack produces smaller output than JSON."""
        data = {
            "messages": [
                {"role": "user", "content": "Hello, how are you?"},
                {"role": "assistant", "content": "I'm doing great, thanks!"},
            ],
            "timestamp": 1234567890,
            "metadata": {"source": "test", "version": 1}
        }

        json_size = len(serialize(data, format="json"))
        msgpack_size = len(serialize(data, format="msgpack"))

        # Msgpack should be smaller
        assert msgpack_size < json_size


# =============================================================================
# Preparation Tests
# =============================================================================


class TestPrepareForSerialization:
    """Tests for _prepare_for_serialization helper."""

    def test_prepare_primitives(self):
        """Test preparing primitive types."""
        assert _prepare_for_serialization(None) is None
        assert _prepare_for_serialization("hello") == "hello"
        assert _prepare_for_serialization(42) == 42
        assert _prepare_for_serialization(3.14) == 3.14
        assert _prepare_for_serialization(True) is True

    def test_prepare_enum(self):
        """Test preparing enum values."""
        result = _prepare_for_serialization(SampleEnum.OPTION_A)
        assert result == "a"

    def test_prepare_dataclass(self):
        """Test preparing dataclass."""
        dc = SampleDataclass(name="test", value=42, score=0.95)
        result = _prepare_for_serialization(dc)

        assert result == {"name": "test", "value": 42, "score": 0.95}

    def test_prepare_dict_with_enum_keys(self):
        """Test preparing dict with enum values."""
        data = {"status": SampleEnum.OPTION_B}
        result = _prepare_for_serialization(data)

        assert result == {"status": "b"}

    def test_prepare_list_of_dataclasses(self):
        """Test preparing list of dataclasses."""
        data = [
            SampleDataclass("a", 1, 0.1),
            SampleDataclass("b", 2, 0.2),
        ]
        result = _prepare_for_serialization(data)

        assert result == [
            {"name": "a", "value": 1, "score": 0.1},
            {"name": "b", "value": 2, "score": 0.2},
        ]

    def test_prepare_object_with_to_dict(self):
        """Test preparing object with to_dict method."""
        class CustomObject:
            def to_dict(self):
                return {"custom": "data"}

        obj = CustomObject()
        result = _prepare_for_serialization(obj)

        assert result == {"custom": "data"}


# =============================================================================
# SerializedMessage Tests
# =============================================================================


class TestSerializedMessage:
    """Tests for SerializedMessage class."""

    def test_create_message(self):
        """Test creating a message."""
        msg = SerializedMessage(
            type="test",
            payload={"data": "value"},
        )

        assert msg.type == "test"
        assert msg.payload == {"data": "value"}
        assert msg.timestamp is not None

    def test_message_to_dict(self):
        """Test converting message to dict."""
        msg = SerializedMessage(
            type="test",
            payload={"data": "value"},
            timestamp=1234567890.0,
        )

        d = msg.to_dict()

        assert d["type"] == "test"
        assert d["payload"] == {"data": "value"}
        assert d["timestamp"] == 1234567890.0

    def test_message_with_metadata(self):
        """Test message with metadata."""
        msg = SerializedMessage(
            type="test",
            payload="data",
            metadata={"source": "unit_test"},
        )

        d = msg.to_dict()
        assert d["metadata"] == {"source": "unit_test"}

    def test_message_to_bytes_json(self):
        """Test serializing message to bytes (JSON)."""
        msg = SerializedMessage(
            type="test",
            payload={"key": "value"},
            timestamp=1234567890.0,
        )

        data = msg.to_bytes(format="json")
        assert isinstance(data, bytes)

        decoded = SerializedMessage.from_bytes(data, format="json")
        assert decoded.type == "test"
        assert decoded.payload == {"key": "value"}

    @pytest.mark.skipif(not _has_msgpack(), reason="msgpack not installed")
    def test_message_to_bytes_msgpack(self):
        """Test serializing message to bytes (msgpack)."""
        msg = SerializedMessage(
            type="test",
            payload={"key": "value"},
            timestamp=1234567890.0,
        )

        data = msg.to_bytes(format="msgpack")
        assert isinstance(data, bytes)

        decoded = SerializedMessage.from_bytes(data, format="msgpack")
        assert decoded.type == "test"
        assert decoded.payload == {"key": "value"}

    def test_message_to_string(self):
        """Test serializing message to string."""
        msg = SerializedMessage(
            type="test",
            payload="data",
            timestamp=1234567890.0,
        )

        s = msg.to_string(format="json")
        assert isinstance(s, str)
        assert "test" in s

        decoded = SerializedMessage.from_string(s, format="json")
        assert decoded.type == "test"


# =============================================================================
# MessageSerializer Tests
# =============================================================================


class TestMessageSerializer:
    """Tests for MessageSerializer class."""

    def test_json_serializer(self):
        """Test JSON serializer."""
        serializer = MessageSerializer(format="json")

        data = {"key": "value"}
        packed = serializer.pack(data)
        unpacked = serializer.unpack(packed)

        assert unpacked == data

    @pytest.mark.skipif(not _has_msgpack(), reason="msgpack not installed")
    def test_msgpack_serializer(self):
        """Test msgpack serializer."""
        serializer = MessageSerializer(format="msgpack")

        data = {"key": "value"}
        packed = serializer.pack(data)
        unpacked = serializer.unpack(packed)

        assert unpacked == data

    def test_pack_string(self):
        """Test packing to string."""
        serializer = MessageSerializer(format="json")

        data = {"key": "value"}
        packed = serializer.pack_string(data)

        assert isinstance(packed, str)

    def test_unpack_string(self):
        """Test unpacking from string."""
        serializer = MessageSerializer(format="json")

        s = '{"key":"value"}'
        unpacked = serializer.unpack_string(s)

        assert unpacked == {"key": "value"}

    def test_create_message(self):
        """Test creating typed message."""
        serializer = MessageSerializer(format="json")

        msg = serializer.create_message(
            type="transcript",
            payload={"text": "hello"},
            source="test",
        )

        assert msg.type == "transcript"
        assert msg.payload == {"text": "hello"}
        assert msg.metadata == {"source": "test"}

    def test_pack_unpack_message(self):
        """Test packing and unpacking message."""
        serializer = MessageSerializer(format="json")

        msg = serializer.create_message(
            type="response",
            payload={"text": "world"},
        )

        packed = serializer.pack_message(msg)
        unpacked = serializer.unpack_message(packed)

        assert unpacked.type == "response"
        assert unpacked.payload == {"text": "world"}


# =============================================================================
# Convenience Instances Tests
# =============================================================================


class TestConvenienceInstances:
    """Tests for convenience serializer instances."""

    def test_json_serializer_instance(self):
        """Test json_serializer convenience instance."""
        assert json_serializer.format == SerializationFormat.JSON

        data = {"test": 123}
        packed = json_serializer.pack(data)
        unpacked = json_serializer.unpack(packed)

        assert unpacked == data

    @pytest.mark.skipif(not _has_msgpack(), reason="msgpack not installed")
    def test_msgpack_serializer_instance(self):
        """Test msgpack_serializer convenience instance."""
        assert msgpack_serializer.format == SerializationFormat.MSGPACK

        data = {"test": 123}
        packed = msgpack_serializer.pack(data)
        unpacked = msgpack_serializer.unpack(packed)

        assert unpacked == data


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_format(self):
        """Test invalid format raises error."""
        with pytest.raises(ValueError):
            serialize({"data": 1}, format="invalid")

    def test_invalid_json_deserialize(self):
        """Test invalid JSON raises error."""
        with pytest.raises((ValueError, Exception)):
            deserialize(b"not valid json", format="json")


# =============================================================================
# Performance Comparison Tests
# =============================================================================


@pytest.mark.skipif(not _has_msgpack(), reason="msgpack not installed")
class TestPerformanceComparison:
    """Tests comparing JSON vs msgpack performance."""

    def test_serialization_speed(self):
        """Test that msgpack is faster for serialization."""
        data = {
            "messages": [{"role": "user", "content": f"Message {i}"} for i in range(100)],
            "metadata": {"key": "value" * 100},
        }

        # Warmup
        for _ in range(10):
            serialize(data, format="json")
            serialize(data, format="msgpack")

        # Time JSON
        iterations = 100
        json_start = time.perf_counter()
        for _ in range(iterations):
            serialize(data, format="json")
        json_time = time.perf_counter() - json_start

        # Time msgpack
        msgpack_start = time.perf_counter()
        for _ in range(iterations):
            serialize(data, format="msgpack")
        msgpack_time = time.perf_counter() - msgpack_start

        # Log times (msgpack should generally be faster)
        print(f"\nJSON: {json_time*1000:.2f}ms, msgpack: {msgpack_time*1000:.2f}ms")

        # We expect msgpack to be at least comparable (sometimes faster)
        # Not asserting strict inequality due to variability
        assert msgpack_time < json_time * 2  # Msgpack should not be 2x slower
