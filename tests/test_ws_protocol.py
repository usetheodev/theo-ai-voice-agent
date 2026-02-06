#!/usr/bin/env python3
"""
Teste do protocolo WebSocket entre Media Server e AI Agent
"""

import sys
import asyncio
import json

# Adiciona paths
sys.path.insert(0, '../ai-agent')
sys.path.insert(0, '../media-server')

from ai_agent.ws.protocol import (
    MessageType,
    AudioConfig,
    AudioDirection,
    SessionStartMessage,
    SessionStartedMessage,
    SessionEndMessage,
    AudioEndMessage,
    ResponseStartMessage,
    ResponseEndMessage,
    ErrorMessage,
    AudioFrame,
    parse_control_message,
    parse_audio_frame,
    create_audio_frame,
    is_audio_frame,
    session_id_to_hash,
)


def test_control_messages():
    """Testa serialização/deserialização de mensagens de controle"""
    print("Testing control messages...")

    # SessionStartMessage
    audio_config = AudioConfig(sample_rate=8000, channels=1, sample_width=2)
    msg = SessionStartMessage(
        session_id="test-session-123",
        call_id="sip-call-456",
        audio_config=audio_config
    )
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, SessionStartMessage)
    assert parsed.session_id == "test-session-123"
    assert parsed.audio_config.sample_rate == 8000
    print("   SessionStartMessage OK")

    # SessionStartedMessage
    msg = SessionStartedMessage(session_id="test-session-123")
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, SessionStartedMessage)
    assert parsed.session_id == "test-session-123"
    print("   SessionStartedMessage OK")

    # SessionEndMessage
    msg = SessionEndMessage(session_id="test-session-123", reason="user_hangup")
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, SessionEndMessage)
    assert parsed.reason == "user_hangup"
    print("   SessionEndMessage OK")

    # AudioEndMessage
    msg = AudioEndMessage(session_id="test-session-123")
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, AudioEndMessage)
    print("   AudioEndMessage OK")

    # ResponseStartMessage
    msg = ResponseStartMessage(session_id="test-session-123", text="Olá!")
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, ResponseStartMessage)
    assert parsed.text == "Olá!"
    print("   ResponseStartMessage OK")

    # ResponseEndMessage
    msg = ResponseEndMessage(session_id="test-session-123")
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, ResponseEndMessage)
    print("   ResponseEndMessage OK")

    # ErrorMessage
    msg = ErrorMessage(session_id="test-session-123", code="LLM_FAILED", message="Timeout")
    json_str = msg.to_json()
    parsed = parse_control_message(json_str)
    assert isinstance(parsed, ErrorMessage)
    assert parsed.code == "LLM_FAILED"
    print("   ErrorMessage OK")


def test_audio_frames():
    """Testa serialização/deserialização de frames de áudio"""
    print("\nTesting audio frames...")

    session_id = "test-session-789"
    audio_data = b'\x00\x10' * 160  # 320 bytes = 20ms a 8kHz

    # Cria frame inbound
    frame_bytes = create_audio_frame(
        session_id=session_id,
        audio_data=audio_data,
        direction=AudioDirection.INBOUND
    )
    assert is_audio_frame(frame_bytes)
    print("   Audio frame creation OK")

    # Parse com lookup
    session_hash = session_id_to_hash(session_id).hex()
    lookup = {session_hash: session_id}
    frame = parse_audio_frame(frame_bytes, lookup)
    assert frame.session_id == session_id
    assert frame.direction == AudioDirection.INBOUND
    assert frame.audio_data == audio_data
    print("   Audio frame parsing OK")

    # Cria frame outbound
    frame_bytes = create_audio_frame(
        session_id=session_id,
        audio_data=audio_data,
        direction=AudioDirection.OUTBOUND
    )
    frame = parse_audio_frame(frame_bytes, lookup)
    assert frame.direction == AudioDirection.OUTBOUND
    print("   Outbound audio frame OK")


def test_session_hash():
    """Testa geração de hash do session_id"""
    print("\nTesting session hash...")

    session_id = "test-session-abc123"
    hash_bytes = session_id_to_hash(session_id)
    assert len(hash_bytes) == 8
    print(f"  Session: {session_id}")
    print(f"  Hash: {hash_bytes.hex()}")
    print("   Session hash OK")


if __name__ == "__main__":
    print("=" * 50)
    print("WebSocket Protocol Tests")
    print("=" * 50)

    try:
        test_control_messages()
        test_audio_frames()
        test_session_hash()
        print("\n" + "=" * 50)
        print(" All tests passed!")
        print("=" * 50)
    except Exception as e:
        print(f"\n Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
