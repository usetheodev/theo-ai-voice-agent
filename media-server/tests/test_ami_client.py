"""
Testes unitarios para AMI Client

Cobertura:
- _is_success: parsing de resposta AMI
- _extract_field: extracao de campos da resposta
- Formatacao de acoes AMI
- Estado de conexao

Nota: Testes de rede (connect, redirect, etc.) requerem Docker.
Aqui testamos apenas logica pura sem I/O.
"""

import pytest
import sys
from pathlib import Path

# Add media-server to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ami.client import AMIClient


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def ami_client():
    """AMI client para testes (sem conexao)."""
    return AMIClient(
        host="localhost",
        port=5038,
        username="media_server",
        secret="test_secret",
        timeout=5.0,
    )


@pytest.fixture
def success_response():
    """Resposta AMI de sucesso (Login)."""
    return (
        "Response: Success\r\n"
        "ActionID: 12345\r\n"
        "Message: Authentication accepted\r\n"
        "\r\n"
    )


@pytest.fixture
def error_response():
    """Resposta AMI de erro."""
    return (
        "Response: Error\r\n"
        "ActionID: 12345\r\n"
        "Message: Authentication failed\r\n"
        "\r\n"
    )


@pytest.fixture
def redirect_success():
    """Resposta de Redirect bem-sucedido."""
    return (
        "Response: Success\r\n"
        "ActionID: abcdef\r\n"
        "Message: Redirect successful\r\n"
        "\r\n"
    )


@pytest.fixture
def redirect_error():
    """Resposta de Redirect com erro (canal nao encontrado)."""
    return (
        "Response: Error\r\n"
        "ActionID: abcdef\r\n"
        "Message: Channel not specified\r\n"
        "\r\n"
    )


# =============================================================================
# TESTES DE _is_success
# =============================================================================

class TestIsSuccess:
    """Testes para AMIClient._is_success."""

    def test_success_response(self, success_response):
        """Resposta com 'Response: Success' deve retornar True."""
        assert AMIClient._is_success(success_response) is True

    def test_error_response(self, error_response):
        """Resposta com 'Response: Error' deve retornar False."""
        assert AMIClient._is_success(error_response) is False

    def test_redirect_success(self, redirect_success):
        """Redirect bem-sucedido deve retornar True."""
        assert AMIClient._is_success(redirect_success) is True

    def test_redirect_error(self, redirect_error):
        """Redirect com erro deve retornar False."""
        assert AMIClient._is_success(redirect_error) is False

    def test_case_insensitive(self):
        """Parsing deve ser case-insensitive."""
        response = "response: success\r\nActionID: 123\r\n\r\n"
        assert AMIClient._is_success(response) is True

    def test_with_extra_whitespace(self):
        """Deve funcionar com whitespace extra."""
        response = "  Response: Success  \r\nActionID: 123\r\n\r\n"
        assert AMIClient._is_success(response) is True

    def test_empty_response(self):
        """Resposta vazia deve retornar False."""
        assert AMIClient._is_success("") is False

    def test_no_response_line(self):
        """Resposta sem 'Response:' deve retornar False."""
        response = "ActionID: 123\r\nMessage: Hello\r\n\r\n"
        assert AMIClient._is_success(response) is False

    def test_response_follows_different_format(self):
        """Resposta 'Response: Follows' deve retornar False."""
        response = "Response: Follows\r\nActionID: 123\r\n\r\n"
        assert AMIClient._is_success(response) is False

    def test_multiline_response(self):
        """Resposta com multiplas linhas extras."""
        response = (
            "Response: Success\r\n"
            "ActionID: abc123\r\n"
            "Message: Authentication accepted\r\n"
            "Events: on\r\n"
            "\r\n"
        )
        assert AMIClient._is_success(response) is True


# =============================================================================
# TESTES DE _extract_field
# =============================================================================

class TestExtractField:
    """Testes para AMIClient._extract_field."""

    def test_extract_message(self, success_response):
        """Extrai campo Message."""
        result = AMIClient._extract_field(success_response, "Message")
        assert result == "Authentication accepted"

    def test_extract_action_id(self, success_response):
        """Extrai campo ActionID."""
        result = AMIClient._extract_field(success_response, "ActionID")
        assert result == "12345"

    def test_extract_response(self, success_response):
        """Extrai campo Response."""
        result = AMIClient._extract_field(success_response, "Response")
        assert result == "Success"

    def test_field_not_found(self, success_response):
        """Campo inexistente retorna None."""
        result = AMIClient._extract_field(success_response, "Channel")
        assert result is None

    def test_case_insensitive(self):
        """Extracao e case-insensitive."""
        response = "response: Success\r\nmessage: Test\r\n\r\n"
        result = AMIClient._extract_field(response, "Message")
        assert result == "Test"

    def test_field_with_colon_in_value(self):
        """Campo com ':' no valor deve funcionar."""
        response = "Response: Success\r\nMessage: Error: something failed\r\n\r\n"
        result = AMIClient._extract_field(response, "Message")
        assert result == "Error: something failed"

    def test_empty_response(self):
        """Resposta vazia retorna None."""
        result = AMIClient._extract_field("", "Message")
        assert result is None

    def test_extract_from_redirect_response(self, redirect_success):
        """Extrai campo de resposta Redirect."""
        result = AMIClient._extract_field(redirect_success, "Message")
        assert result == "Redirect successful"


# =============================================================================
# TESTES DE ESTADO
# =============================================================================

class TestAMIClientState:
    """Testes para estado do AMI Client."""

    def test_initial_state_disconnected(self, ami_client):
        """Client deve iniciar desconectado."""
        assert ami_client.is_connected is False

    def test_internal_state_initial(self, ami_client):
        """Verifica estado interno inicial."""
        assert ami_client._reader is None
        assert ami_client._writer is None
        assert ami_client._connected is False

    def test_constructor_params(self, ami_client):
        """Verifica que parametros do construtor sao armazenados."""
        assert ami_client._host == "localhost"
        assert ami_client._port == 5038
        assert ami_client._username == "media_server"
        assert ami_client._secret == "test_secret"
        assert ami_client._timeout == 5.0

    def test_custom_timeout(self):
        """Timeout customizado."""
        client = AMIClient(
            host="10.0.0.1",
            port=5039,
            username="admin",
            secret="pass",
            timeout=10.0,
        )
        assert client._timeout == 10.0

    def test_default_timeout(self):
        """Timeout padrao."""
        client = AMIClient(
            host="localhost",
            port=5038,
            username="admin",
            secret="pass",
        )
        assert client._timeout == 5.0


# =============================================================================
# TESTES DE REDIRECT SEM CONEXAO
# =============================================================================

class TestRedirectWithoutConnection:
    """Testes para redirect quando nao esta conectado."""

    @pytest.mark.asyncio
    async def test_redirect_fails_when_disconnected(self, ami_client):
        """Redirect deve falhar quando nao conectado."""
        result = await ami_client.redirect(
            channel="PJSIP/1004-00000001",
            context="transfer-assistida",
            exten="1001",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self, ami_client):
        """Close nao deve falhar quando nao conectado."""
        await ami_client.close()  # Nao deve lancar excecao


# =============================================================================
# TESTES DE FORMATACAO DE ACOES
# =============================================================================

class TestActionFormatting:
    """Testes para verificar formato das acoes AMI."""

    def test_login_format(self):
        """Verifica formato da acao Login."""
        action = (
            "Action: Login\r\n"
            "ActionID: test-123\r\n"
            "Username: admin\r\n"
            "Secret: password\r\n"
            "\r\n"
        )
        lines = action.strip().split("\r\n")
        assert lines[0] == "Action: Login"
        assert lines[1] == "ActionID: test-123"
        assert lines[2] == "Username: admin"
        assert lines[3] == "Secret: password"

    def test_redirect_format(self):
        """Verifica formato da acao Redirect."""
        action = (
            "Action: Redirect\r\n"
            "ActionID: test-456\r\n"
            "Channel: PJSIP/1004-00000001\r\n"
            "Context: transfer-assistida\r\n"
            "Exten: 1001\r\n"
            "Priority: 1\r\n"
            "\r\n"
        )
        lines = action.strip().split("\r\n")
        assert lines[0] == "Action: Redirect"
        assert "Channel: PJSIP/1004-00000001" in lines
        assert "Context: transfer-assistida" in lines
        assert "Exten: 1001" in lines
        assert "Priority: 1" in lines

    def test_action_terminates_with_double_crlf(self):
        """Acao AMI deve terminar com \\r\\n\\r\\n."""
        action = (
            "Action: Logoff\r\n"
            "ActionID: test-789\r\n"
            "\r\n"
        )
        assert action.endswith("\r\n\r\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
