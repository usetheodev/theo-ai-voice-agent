"""
Testes unitarios para CallActionMessage (ASP Protocol)

Cobertura:
- Serializacao/deserializacao (roundtrip)
- Campos opcionais (target, reason)
- parse_message com call.action
- Validacao de message_type
- Integracao com fluxo ASP existente
"""

import json
import pytest
import sys
from pathlib import Path

# Add shared to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from asp_protocol import (
    CallActionMessage,
    MessageType,
    parse_message,
    is_valid_message,
)
from asp_protocol.enums import CallActionType


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_session_id():
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def transfer_message(sample_session_id):
    return CallActionMessage(
        session_id=sample_session_id,
        action=CallActionType.TRANSFER,
        target="1001",
        reason="Cliente solicitou suporte tecnico",
    )


@pytest.fixture
def hangup_message(sample_session_id):
    return CallActionMessage(
        session_id=sample_session_id,
        action=CallActionType.HANGUP,
        reason="Conversa encerrada naturalmente",
    )


# =============================================================================
# TESTES DE CallActionMessage
# =============================================================================

class TestCallActionMessage:
    """Testes para CallActionMessage."""

    def test_message_type(self, transfer_message):
        """Verifica tipo da mensagem."""
        assert transfer_message.message_type == MessageType.CALL_ACTION

    def test_message_type_value(self, transfer_message):
        """Verifica valor string do tipo."""
        assert transfer_message.message_type.value == "call.action"

    def test_transfer_to_dict(self, transfer_message, sample_session_id):
        """Conversao para dict com todos os campos."""
        d = transfer_message.to_dict()
        assert d["type"] == "call.action"
        assert d["session_id"] == sample_session_id
        assert d["action"] == "transfer"
        assert d["target"] == "1001"
        assert d["reason"] == "Cliente solicitou suporte tecnico"
        assert "timestamp" in d

    def test_hangup_to_dict(self, hangup_message, sample_session_id):
        """Conversao para dict sem target."""
        d = hangup_message.to_dict()
        assert d["type"] == "call.action"
        assert d["session_id"] == sample_session_id
        assert d["action"] == "hangup"
        assert "target" not in d
        assert d["reason"] == "Conversa encerrada naturalmente"

    def test_minimal_to_dict(self, sample_session_id):
        """Conversao para dict sem campos opcionais."""
        msg = CallActionMessage(
            session_id=sample_session_id,
            action=CallActionType.TRANSFER,
        )
        d = msg.to_dict()
        assert d["type"] == "call.action"
        assert d["session_id"] == sample_session_id
        assert d["action"] == "transfer"
        assert "target" not in d
        assert "reason" not in d

    def test_timestamp_auto_generated(self, sample_session_id):
        """Timestamp deve ser gerado automaticamente."""
        msg = CallActionMessage(
            session_id=sample_session_id,
            action=CallActionType.HANGUP,
        )
        assert msg.timestamp is not None
        assert "T" in msg.timestamp  # ISO format

    def test_json_roundtrip_transfer(self, transfer_message):
        """Serializacao/deserializacao JSON de transfer."""
        json_str = transfer_message.to_json()
        data = json.loads(json_str)
        restored = CallActionMessage.from_dict(data)

        assert restored.session_id == transfer_message.session_id
        assert restored.action == transfer_message.action
        assert restored.target == transfer_message.target
        assert restored.reason == transfer_message.reason

    def test_json_roundtrip_hangup(self, hangup_message):
        """Serializacao/deserializacao JSON de hangup."""
        json_str = hangup_message.to_json()
        data = json.loads(json_str)
        restored = CallActionMessage.from_dict(data)

        assert restored.session_id == hangup_message.session_id
        assert restored.action == hangup_message.action
        assert restored.target is None
        assert restored.reason == hangup_message.reason

    def test_from_dict_minimal(self, sample_session_id):
        """Criacao de CallActionMessage a partir de dict minimo."""
        data = {
            "type": "call.action",
            "session_id": sample_session_id,
            "action": "transfer",
        }
        msg = CallActionMessage.from_dict(data)
        assert msg.session_id == sample_session_id
        assert msg.action == "transfer"
        assert msg.target is None
        assert msg.reason is None


# =============================================================================
# TESTES DE parse_message COM call.action
# =============================================================================

class TestParseCallAction:
    """Testes para parse_message com CallActionMessage."""

    def test_parse_transfer_from_json(self, sample_session_id):
        """Parse de call.action transfer a partir de JSON string."""
        data = {
            "type": "call.action",
            "session_id": sample_session_id,
            "action": "transfer",
            "target": "1001",
        }
        json_str = json.dumps(data)
        parsed = parse_message(json_str)

        assert isinstance(parsed, CallActionMessage)
        assert parsed.session_id == sample_session_id
        assert parsed.action == "transfer"
        assert parsed.target == "1001"

    def test_parse_hangup_from_dict(self, sample_session_id):
        """Parse de call.action hangup a partir de dict."""
        data = {
            "type": "call.action",
            "session_id": sample_session_id,
            "action": "hangup",
            "reason": "fim da conversa",
        }
        parsed = parse_message(data)

        assert isinstance(parsed, CallActionMessage)
        assert parsed.action == "hangup"
        assert parsed.target is None
        assert parsed.reason == "fim da conversa"

    def test_parse_roundtrip_via_parse_message(self, transfer_message):
        """Roundtrip completo: create -> to_json -> parse_message."""
        json_str = transfer_message.to_json()
        parsed = parse_message(json_str)

        assert isinstance(parsed, CallActionMessage)
        assert parsed.session_id == transfer_message.session_id
        assert parsed.action == transfer_message.action
        assert parsed.target == transfer_message.target

    def test_is_valid_message_transfer(self, sample_session_id):
        """Verifica que call.action e reconhecido como mensagem valida."""
        data = {
            "type": "call.action",
            "session_id": sample_session_id,
            "action": "transfer",
            "target": "1001",
        }
        assert is_valid_message(data)


# =============================================================================
# TESTES DE CallActionType ENUM
# =============================================================================

class TestCallActionType:
    """Testes para CallActionType enum."""

    def test_transfer_value(self):
        assert CallActionType.TRANSFER == "transfer"
        assert CallActionType.TRANSFER.value == "transfer"

    def test_hangup_value(self):
        assert CallActionType.HANGUP == "hangup"
        assert CallActionType.HANGUP.value == "hangup"

    def test_enum_in_message(self, sample_session_id):
        """Enum funciona corretamente em CallActionMessage."""
        msg = CallActionMessage(
            session_id=sample_session_id,
            action=CallActionType.TRANSFER,
            target="1001",
        )
        d = msg.to_dict()
        assert d["action"] == "transfer"


# =============================================================================
# TESTES DE INTEGRACAO
# =============================================================================

class TestCallActionIntegration:
    """Testes de integracao do fluxo call.action."""

    def test_ai_agent_sends_call_action(self, sample_session_id):
        """Simula AI Agent enviando call.action e Media Server recebendo."""
        # 1. AI Agent cria mensagem
        msg = CallActionMessage(
            session_id=sample_session_id,
            action=CallActionType.TRANSFER,
            target="1001",
            reason="Cliente quer falar com suporte",
        )

        # 2. Serializa para enviar via WebSocket
        json_str = msg.to_json()

        # 3. Media Server recebe e faz parse
        parsed = parse_message(json_str)

        # 4. Verifica integridade
        assert isinstance(parsed, CallActionMessage)
        assert parsed.session_id == sample_session_id
        assert parsed.action == "transfer"
        assert parsed.target == "1001"
        assert parsed.reason == "Cliente quer falar com suporte"

    def test_hangup_flow(self, sample_session_id):
        """Simula fluxo de hangup sem target."""
        msg = CallActionMessage(
            session_id=sample_session_id,
            action=CallActionType.HANGUP,
        )
        json_str = msg.to_json()
        parsed = parse_message(json_str)

        assert isinstance(parsed, CallActionMessage)
        assert parsed.action == "hangup"
        assert parsed.target is None

    def test_action_with_string_values(self, sample_session_id):
        """Strings literais funcionam como action (nao apenas enums)."""
        msg = CallActionMessage(
            session_id=sample_session_id,
            action="transfer",
            target="vendas",
        )
        d = msg.to_dict()
        assert d["action"] == "transfer"

        restored = CallActionMessage.from_dict(d)
        assert restored.action == "transfer"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
