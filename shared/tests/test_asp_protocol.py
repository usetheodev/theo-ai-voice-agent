"""
Testes unitários para o módulo asp_protocol

Cobertura:
- Serialização/deserialização de mensagens
- Validação de configurações
- Negociação de configuração
- Casos de borda
"""

import json
import pytest
import sys
from pathlib import Path

# Add shared to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from asp_protocol import (
    # Enums
    AudioEncoding,
    SessionStatus,
    ErrorCategory,
    MessageType,
    # Config
    AudioConfig,
    VADConfig,
    ProtocolCapabilities,
    NegotiatedConfig,
    Adjustment,
    ProtocolError,
    SessionStatistics,
    # Messages
    ProtocolCapabilitiesMessage,
    SessionStartMessage,
    SessionStartedMessage,
    SessionUpdateMessage,
    SessionUpdatedMessage,
    SessionEndMessage,
    SessionEndedMessage,
    ProtocolErrorMessage,
    parse_message,
    is_valid_message,
    # Negotiation
    ConfigNegotiator,
    negotiate_config,
    # Constants
    VALID_SAMPLE_RATES,
    VAD_SILENCE_THRESHOLD_MIN,
    VAD_SILENCE_THRESHOLD_MAX,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def default_audio_config():
    """AudioConfig com valores default."""
    return AudioConfig()


@pytest.fixture
def default_vad_config():
    """VADConfig com valores default."""
    return VADConfig()


@pytest.fixture
def default_capabilities():
    """ProtocolCapabilities com valores default."""
    return ProtocolCapabilities()


@pytest.fixture
def sample_session_id():
    """UUID de exemplo para testes."""
    return "550e8400-e29b-41d4-a716-446655440000"


# =============================================================================
# TESTES DE AudioConfig
# =============================================================================

class TestAudioConfig:
    """Testes para AudioConfig."""

    def test_default_values(self, default_audio_config):
        """Verifica valores default."""
        assert default_audio_config.sample_rate == 8000
        assert default_audio_config.encoding == AudioEncoding.PCM_S16LE
        assert default_audio_config.channels == 1
        assert default_audio_config.frame_duration_ms == 20

    def test_validation_valid_config(self, default_audio_config):
        """Config default deve ser válida."""
        errors = default_audio_config.validate()
        assert len(errors) == 0
        assert default_audio_config.is_valid()

    def test_validation_invalid_sample_rate(self):
        """Sample rate inválido deve gerar erro."""
        config = AudioConfig(sample_rate=44100)
        errors = config.validate()
        assert len(errors) == 1
        assert "sample_rate" in errors[0]

    def test_validation_invalid_frame_duration(self):
        """Frame duration inválido deve gerar erro."""
        config = AudioConfig(frame_duration_ms=15)
        errors = config.validate()
        assert len(errors) == 1
        assert "frame_duration_ms" in errors[0]

    def test_to_dict(self, default_audio_config):
        """Conversão para dict."""
        d = default_audio_config.to_dict()
        assert d["sample_rate"] == 8000
        assert d["encoding"] == "pcm_s16le"
        assert d["channels"] == 1
        assert d["frame_duration_ms"] == 20

    def test_from_dict(self):
        """Criação a partir de dict."""
        data = {
            "sample_rate": 16000,
            "encoding": "mulaw",
            "channels": 1,
            "frame_duration_ms": 30
        }
        config = AudioConfig.from_dict(data)
        assert config.sample_rate == 16000
        assert config.encoding == AudioEncoding.MULAW
        assert config.frame_duration_ms == 30

    def test_json_roundtrip(self, default_audio_config):
        """Serialização/deserialização JSON."""
        json_str = default_audio_config.to_json()
        restored = AudioConfig.from_json(json_str)
        assert restored.sample_rate == default_audio_config.sample_rate
        assert restored.encoding == default_audio_config.encoding

    def test_bytes_per_frame(self):
        """Cálculo de bytes por frame."""
        config = AudioConfig(sample_rate=8000, frame_duration_ms=20)
        # 8000 * 0.020 * 2 (16-bit) * 1 (mono) = 320 bytes
        assert config.bytes_per_frame == 320


# =============================================================================
# TESTES DE VADConfig
# =============================================================================

class TestVADConfig:
    """Testes para VADConfig."""

    def test_default_values(self, default_vad_config):
        """Verifica valores default."""
        assert default_vad_config.enabled == True
        assert default_vad_config.silence_threshold_ms == 500
        assert default_vad_config.min_speech_ms == 250
        assert default_vad_config.threshold == 0.5
        assert default_vad_config.ring_buffer_frames == 5
        assert default_vad_config.speech_ratio == 0.4
        assert default_vad_config.prefix_padding_ms == 300

    def test_validation_valid_config(self, default_vad_config):
        """Config default deve ser válida."""
        errors = default_vad_config.validate()
        assert len(errors) == 0
        assert default_vad_config.is_valid()

    def test_validation_silence_threshold_too_low(self):
        """Silence threshold muito baixo."""
        config = VADConfig(silence_threshold_ms=50)
        errors = config.validate()
        assert len(errors) == 1
        assert "silence_threshold_ms" in errors[0]

    def test_validation_silence_threshold_too_high(self):
        """Silence threshold muito alto."""
        config = VADConfig(silence_threshold_ms=3000)
        errors = config.validate()
        assert len(errors) == 1
        assert "silence_threshold_ms" in errors[0]

    def test_validation_threshold_out_of_range(self):
        """Threshold fora do range 0-1."""
        config = VADConfig(threshold=1.5)
        errors = config.validate()
        assert len(errors) == 1
        assert "threshold" in errors[0]

    def test_validation_multiple_errors(self):
        """Múltiplos erros de validação."""
        config = VADConfig(
            silence_threshold_ms=50,
            threshold=1.5,
            ring_buffer_frames=20
        )
        errors = config.validate()
        assert len(errors) == 3

    def test_merge(self, default_vad_config):
        """Merge de configurações."""
        merged = default_vad_config.merge({"silence_threshold_ms": 700})
        assert merged.silence_threshold_ms == 700
        assert merged.threshold == default_vad_config.threshold

    def test_json_roundtrip(self, default_vad_config):
        """Serialização/deserialização JSON."""
        json_str = default_vad_config.to_json()
        restored = VADConfig.from_json(json_str)
        assert restored.silence_threshold_ms == default_vad_config.silence_threshold_ms
        assert restored.threshold == default_vad_config.threshold


# =============================================================================
# TESTES DE ProtocolCapabilities
# =============================================================================

class TestProtocolCapabilities:
    """Testes para ProtocolCapabilities."""

    def test_default_values(self, default_capabilities):
        """Verifica valores default."""
        assert default_capabilities.version == "1.0.0"
        assert 8000 in default_capabilities.supported_sample_rates
        assert "pcm_s16le" in default_capabilities.supported_encodings

    def test_supports_sample_rate(self, default_capabilities):
        """Verifica suporte a sample rate."""
        assert default_capabilities.supports_sample_rate(8000)
        assert default_capabilities.supports_sample_rate(16000)
        assert not default_capabilities.supports_sample_rate(44100)

    def test_supports_encoding(self, default_capabilities):
        """Verifica suporte a encoding."""
        assert default_capabilities.supports_encoding("pcm_s16le")
        assert not default_capabilities.supports_encoding("opus")

    def test_supports_feature(self, default_capabilities):
        """Verifica suporte a features."""
        assert default_capabilities.supports_feature("barge_in")
        assert not default_capabilities.supports_feature("video")


# =============================================================================
# TESTES DE MENSAGENS
# =============================================================================

class TestProtocolCapabilitiesMessage:
    """Testes para ProtocolCapabilitiesMessage."""

    def test_message_type(self, default_capabilities):
        """Verifica tipo da mensagem."""
        msg = ProtocolCapabilitiesMessage(capabilities=default_capabilities)
        assert msg.message_type == MessageType.PROTOCOL_CAPABILITIES

    def test_to_dict(self, default_capabilities):
        """Conversão para dict."""
        msg = ProtocolCapabilitiesMessage(
            capabilities=default_capabilities,
            server_id="test-server"
        )
        d = msg.to_dict()
        assert d["type"] == "protocol.capabilities"
        assert d["server_id"] == "test-server"
        assert "capabilities" in d

    def test_json_roundtrip(self, default_capabilities):
        """Serialização/deserialização JSON."""
        msg = ProtocolCapabilitiesMessage(capabilities=default_capabilities)
        json_str = msg.to_json()
        restored = ProtocolCapabilitiesMessage.from_json(json_str)
        assert restored.version == msg.version


class TestSessionStartMessage:
    """Testes para SessionStartMessage."""

    def test_message_type(self, sample_session_id):
        """Verifica tipo da mensagem."""
        msg = SessionStartMessage(session_id=sample_session_id)
        assert msg.message_type == MessageType.SESSION_START

    def test_default_audio_vad(self, sample_session_id):
        """Audio e VAD default são criados."""
        msg = SessionStartMessage(session_id=sample_session_id)
        assert msg.audio is not None
        assert msg.vad is not None

    def test_with_custom_config(self, sample_session_id):
        """Com configuração customizada."""
        audio = AudioConfig(sample_rate=16000)
        vad = VADConfig(silence_threshold_ms=700)
        msg = SessionStartMessage(
            session_id=sample_session_id,
            audio=audio,
            vad=vad,
            call_id="sip-123",
            metadata={"key": "value"}
        )
        d = msg.to_dict()
        assert d["audio"]["sample_rate"] == 16000
        assert d["vad"]["silence_threshold_ms"] == 700
        assert d["call_id"] == "sip-123"
        assert d["metadata"]["key"] == "value"

    def test_json_roundtrip(self, sample_session_id):
        """Serialização/deserialização JSON."""
        msg = SessionStartMessage(
            session_id=sample_session_id,
            call_id="sip-123"
        )
        json_str = msg.to_json()
        restored = SessionStartMessage.from_json(json_str)
        assert restored.session_id == sample_session_id
        assert restored.call_id == "sip-123"


class TestSessionStartedMessage:
    """Testes para SessionStartedMessage."""

    def test_accepted(self, sample_session_id, default_audio_config, default_vad_config):
        """Sessão aceita."""
        msg = SessionStartedMessage(
            session_id=sample_session_id,
            status=SessionStatus.ACCEPTED,
            negotiated=NegotiatedConfig(
                audio=default_audio_config,
                vad=default_vad_config
            )
        )
        assert msg.is_accepted
        assert not msg.is_rejected

    def test_rejected(self, sample_session_id):
        """Sessão rejeitada."""
        error = ProtocolError(
            code=2001,
            category="audio",
            message="Sample rate not supported"
        )
        msg = SessionStartedMessage(
            session_id=sample_session_id,
            status=SessionStatus.REJECTED,
            errors=[error]
        )
        assert not msg.is_accepted
        assert msg.is_rejected
        assert len(msg.errors) == 1

    def test_accepted_with_changes(self, sample_session_id, default_audio_config, default_vad_config):
        """Sessão aceita com ajustes."""
        msg = SessionStartedMessage(
            session_id=sample_session_id,
            status=SessionStatus.ACCEPTED_WITH_CHANGES,
            negotiated=NegotiatedConfig(
                audio=default_audio_config,
                vad=default_vad_config,
                adjustments=[
                    Adjustment(
                        field="vad.threshold",
                        requested=0.05,
                        applied=0.1,
                        reason="Below minimum"
                    )
                ]
            )
        )
        assert msg.is_accepted
        assert msg.negotiated.has_adjustments()


class TestParseMessage:
    """Testes para parse_message."""

    def test_parse_capabilities(self, default_capabilities):
        """Parse de capabilities."""
        msg = ProtocolCapabilitiesMessage(capabilities=default_capabilities)
        json_str = msg.to_json()
        parsed = parse_message(json_str)
        assert isinstance(parsed, ProtocolCapabilitiesMessage)

    def test_parse_session_start(self, sample_session_id):
        """Parse de session.start."""
        msg = SessionStartMessage(session_id=sample_session_id)
        json_str = msg.to_json()
        parsed = parse_message(json_str)
        assert isinstance(parsed, SessionStartMessage)
        assert parsed.session_id == sample_session_id

    def test_parse_dict(self, sample_session_id):
        """Parse de dict."""
        data = {
            "type": "session.start",
            "session_id": sample_session_id
        }
        parsed = parse_message(data)
        assert isinstance(parsed, SessionStartMessage)

    def test_parse_unknown_type(self):
        """Tipo desconhecido deve lançar exceção."""
        data = {"type": "unknown.type"}
        with pytest.raises(ValueError) as exc_info:
            parse_message(data)
        assert "Unknown message type" in str(exc_info.value)

    def test_is_valid_message(self, sample_session_id):
        """Verificação de mensagem válida."""
        valid = {"type": "session.start", "session_id": sample_session_id}
        invalid = {"type": "invalid"}
        assert is_valid_message(valid)
        assert not is_valid_message(invalid)


# =============================================================================
# TESTES DE NEGOCIAÇÃO
# =============================================================================

class TestConfigNegotiator:
    """Testes para ConfigNegotiator."""

    def test_negotiate_default_config(self, default_capabilities):
        """Negociação com config default."""
        negotiator = ConfigNegotiator(default_capabilities)
        result = negotiator.negotiate(None, None)
        assert result.success
        assert result.status == SessionStatus.ACCEPTED
        assert result.negotiated is not None

    def test_negotiate_compatible_config(self, default_capabilities):
        """Negociação com config compatível."""
        audio = AudioConfig(sample_rate=8000)
        vad = VADConfig(silence_threshold_ms=500)
        result = negotiate_config(default_capabilities, audio, vad)
        assert result.success
        assert result.status == SessionStatus.ACCEPTED

    def test_negotiate_with_adjustments(self, default_capabilities):
        """Negociação com ajustes necessários."""
        vad = VADConfig(threshold=1.5)  # Acima do máximo (1.0)
        result = negotiate_config(default_capabilities, None, vad)
        assert result.success
        assert result.status == SessionStatus.ACCEPTED_WITH_CHANGES
        assert len(result.negotiated.adjustments) > 0

    def test_negotiate_unsupported_sample_rate(self):
        """Negociação com sample rate não suportado."""
        caps = ProtocolCapabilities(supported_sample_rates=[8000])
        audio = AudioConfig(sample_rate=16000)
        result = negotiate_config(caps, audio, None)
        # Deve ajustar para o mais próximo
        assert result.success
        assert result.negotiated.audio.sample_rate == 8000

    def test_negotiate_vad_not_configurable(self):
        """Negociação quando VAD não é configurável."""
        caps = ProtocolCapabilities(vad_configurable=False)
        vad = VADConfig(silence_threshold_ms=1000)
        result = negotiate_config(caps, None, vad)
        assert result.success
        # Deve usar defaults
        assert result.negotiated.vad.silence_threshold_ms == 500

    def test_negotiate_multiple_adjustments(self, default_capabilities):
        """Negociação com múltiplos ajustes."""
        vad = VADConfig(
            silence_threshold_ms=50,   # Abaixo do mínimo
            threshold=1.5,              # Acima do máximo
            ring_buffer_frames=20       # Acima do máximo
        )
        result = negotiate_config(default_capabilities, None, vad)
        assert result.success
        assert result.status == SessionStatus.ACCEPTED_WITH_CHANGES
        assert len(result.negotiated.adjustments) == 3

    def test_negotiate_clamp_values(self, default_capabilities):
        """Valores são ajustados para dentro do range."""
        vad = VADConfig(
            silence_threshold_ms=50,    # Min é 100
            threshold=1.5                # Max é 1.0
        )
        result = negotiate_config(default_capabilities, None, vad)
        assert result.negotiated.vad.silence_threshold_ms == 100
        assert result.negotiated.vad.threshold == 1.0


# =============================================================================
# TESTES DE EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Testes de casos de borda."""

    def test_empty_audio_config_dict(self):
        """Dict vazio para AudioConfig."""
        config = AudioConfig.from_dict({})
        assert config.sample_rate == 8000  # Default

    def test_extra_fields_ignored(self):
        """Campos extras são ignorados."""
        data = {
            "sample_rate": 8000,
            "unknown_field": "value"
        }
        config = AudioConfig.from_dict(data)
        assert config.sample_rate == 8000

    def test_timestamp_auto_generated(self, sample_session_id):
        """Timestamp é gerado automaticamente."""
        msg = SessionStartMessage(session_id=sample_session_id)
        assert msg.timestamp is not None
        assert "T" in msg.timestamp  # ISO format

    def test_negotiated_config_adjustments(self):
        """NegotiatedConfig com adjustments."""
        config = NegotiatedConfig(
            audio=AudioConfig(),
            vad=VADConfig(),
            adjustments=[
                Adjustment("field1", 1, 2, "reason1"),
                Adjustment("field2", "a", "b", "reason2"),
            ]
        )
        assert config.has_adjustments()
        d = config.to_dict()
        assert len(d["adjustments"]) == 2

    def test_protocol_error_with_details(self):
        """ProtocolError com detalhes."""
        error = ProtocolError(
            code=2001,
            category="audio",
            message="Test error",
            details={"key": "value"},
            recoverable=False
        )
        d = error.to_dict()
        assert d["details"]["key"] == "value"
        assert d["recoverable"] == False

    def test_session_statistics(self):
        """SessionStatistics serialização."""
        stats = SessionStatistics(
            audio_frames_received=1000,
            vad_speech_events=10,
            barge_in_count=2
        )
        d = stats.to_dict()
        assert d["audio_frames_received"] == 1000
        assert d["barge_in_count"] == 2


# =============================================================================
# TESTES DE INTEGRAÇÃO
# =============================================================================

class TestIntegration:
    """Testes de integração do fluxo completo."""

    def test_full_handshake_flow(self, sample_session_id):
        """Fluxo completo de handshake."""
        # 1. Servidor cria e envia capabilities
        caps = ProtocolCapabilities()
        caps_msg = ProtocolCapabilitiesMessage(capabilities=caps)
        caps_json = caps_msg.to_json()

        # 2. Cliente recebe capabilities
        received_caps = parse_message(caps_json)
        assert isinstance(received_caps, ProtocolCapabilitiesMessage)

        # 3. Cliente envia session.start
        start_msg = SessionStartMessage(
            session_id=sample_session_id,
            audio=AudioConfig(sample_rate=8000),
            vad=VADConfig(silence_threshold_ms=500)
        )
        start_json = start_msg.to_json()

        # 4. Servidor recebe e negocia
        received_start = parse_message(start_json)
        assert isinstance(received_start, SessionStartMessage)

        result = negotiate_config(
            caps,
            received_start.audio,
            received_start.vad
        )
        assert result.success

        # 5. Servidor envia session.started
        started_msg = SessionStartedMessage(
            session_id=received_start.session_id,
            status=result.status,
            negotiated=result.negotiated
        )
        started_json = started_msg.to_json()

        # 6. Cliente recebe confirmação
        received_started = parse_message(started_json)
        assert isinstance(received_started, SessionStartedMessage)
        assert received_started.is_accepted
        assert received_started.negotiated is not None

    def test_session_update_flow(self, sample_session_id, default_capabilities):
        """Fluxo de atualização de sessão."""
        # 1. Cliente envia update
        update_msg = SessionUpdateMessage(
            session_id=sample_session_id,
            vad=VADConfig(silence_threshold_ms=700)
        )
        update_json = update_msg.to_json()

        # 2. Servidor recebe e negocia
        received_update = parse_message(update_json)
        assert isinstance(received_update, SessionUpdateMessage)

        result = negotiate_config(
            default_capabilities,
            None,
            received_update.vad
        )

        # 3. Servidor envia updated
        updated_msg = SessionUpdatedMessage(
            session_id=sample_session_id,
            status=result.status,
            negotiated=result.negotiated
        )
        updated_json = updated_msg.to_json()

        # 4. Cliente recebe confirmação
        received_updated = parse_message(updated_json)
        assert isinstance(received_updated, SessionUpdatedMessage)

    def test_session_end_flow(self, sample_session_id):
        """Fluxo de encerramento de sessão."""
        # 1. Cliente envia end
        end_msg = SessionEndMessage(
            session_id=sample_session_id,
            reason="call_hangup"
        )
        end_json = end_msg.to_json()

        # 2. Servidor recebe
        received_end = parse_message(end_json)
        assert isinstance(received_end, SessionEndMessage)
        assert received_end.reason == "call_hangup"

        # 3. Servidor envia ended
        ended_msg = SessionEndedMessage(
            session_id=sample_session_id,
            duration_seconds=120.5,
            statistics=SessionStatistics(
                audio_frames_received=6000,
                vad_speech_events=15
            )
        )
        ended_json = ended_msg.to_json()

        # 4. Cliente recebe confirmação
        received_ended = parse_message(ended_json)
        assert isinstance(received_ended, SessionEndedMessage)
        assert received_ended.duration_seconds == 120.5
        assert received_ended.statistics.vad_speech_events == 15


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
