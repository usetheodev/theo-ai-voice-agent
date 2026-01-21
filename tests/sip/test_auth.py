"""
Unit Tests for SIP Digest Authentication

Tests RFC 7616 (SHA-256) and RFC 2617 (MD5) implementation
"""

import pytest
import time
from src.sip.auth import (
    DigestAuthenticator,
    DigestAlgorithm,
    DigestChallenge,
    DigestCredentials
)


class TestDigestAuthenticator:
    """Test DigestAuthenticator class"""

    @pytest.fixture
    def authenticator(self):
        """Create authenticator instance for testing"""
        users = {
            "alice": "secret123",
            "bob": "password456"
        }
        return DigestAuthenticator(
            realm="test.local",
            users=users,
            nonce_timeout=300,
            preferred_algorithm=DigestAlgorithm.SHA256
        )

    def test_initialization(self, authenticator):
        """Test authenticator initialization"""
        assert authenticator.realm == "test.local"
        assert len(authenticator.users) == 2
        assert "alice" in authenticator.users
        assert "bob" in authenticator.users
        assert authenticator.nonce_timeout == 300
        assert authenticator.preferred_algorithm == DigestAlgorithm.SHA256

    def test_generate_challenge_sha256(self, authenticator):
        """Test generating SHA-256 challenge"""
        challenge = authenticator.generate_challenge()

        assert isinstance(challenge, DigestChallenge)
        assert challenge.realm == "test.local"
        assert challenge.algorithm == DigestAlgorithm.SHA256
        assert challenge.qop == "auth"
        assert challenge.nonce is not None
        assert challenge.opaque is not None

        # Verify nonce format (hex:timestamp)
        parts = challenge.nonce.split(':')
        assert len(parts) == 2
        assert len(parts[0]) == 64  # 32 bytes hex = 64 chars
        assert int(parts[1]) > 0  # Valid timestamp

    def test_generate_challenge_md5(self, authenticator):
        """Test generating MD5 challenge (fallback)"""
        challenge = authenticator.generate_challenge(algorithm=DigestAlgorithm.MD5)

        assert challenge.algorithm == DigestAlgorithm.MD5
        assert challenge.realm == "test.local"

    def test_build_www_authenticate_header(self, authenticator):
        """Test building WWW-Authenticate header"""
        challenge = DigestChallenge(
            realm="test.local",
            nonce="abc123:1234567890",
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            opaque="xyz789"
        )

        header = authenticator.build_www_authenticate_header(challenge)

        assert header.startswith("Digest ")
        assert 'realm="test.local"' in header
        assert 'nonce="abc123:1234567890"' in header
        assert 'algorithm=SHA-256' in header
        assert 'qop="auth"' in header
        assert 'opaque="xyz789"' in header

    def test_parse_authorization_header(self):
        """Test parsing Authorization header"""
        auth_header = (
            'Digest username="alice", '
            'realm="test.local", '
            'nonce="abc123:1234567890", '
            'uri="sip:agent@test.local", '
            'response="6629fae49393a05397450978507c4ef1", '
            'algorithm=SHA-256, '
            'qop=auth, '
            'nc=00000001, '
            'cnonce="0a4f113b"'
        )

        credentials = DigestAuthenticator.parse_authorization_header(auth_header)

        assert credentials is not None
        assert credentials.username == "alice"
        assert credentials.realm == "test.local"
        assert credentials.nonce == "abc123:1234567890"
        assert credentials.uri == "sip:agent@test.local"
        assert credentials.response == "6629fae49393a05397450978507c4ef1"
        assert credentials.algorithm == DigestAlgorithm.SHA256
        assert credentials.qop == "auth"
        assert credentials.nc == "00000001"
        assert credentials.cnonce == "0a4f113b"

    def test_parse_authorization_header_invalid(self):
        """Test parsing invalid Authorization header"""
        # Missing Digest prefix
        assert DigestAuthenticator.parse_authorization_header("Bearer token123") is None

        # Missing required fields
        assert DigestAuthenticator.parse_authorization_header('Digest username="alice"') is None

    def test_calculate_response_md5(self, authenticator):
        """Test MD5 digest calculation"""
        response = authenticator._calculate_response(
            username="alice",
            password="secret123",
            realm="test.local",
            method="INVITE",
            uri="sip:agent@test.local",
            nonce="abc123",
            algorithm=DigestAlgorithm.MD5,
            qop="auth",
            nc="00000001",
            cnonce="xyz789"
        )

        # MD5 hash is 32 hex chars
        assert len(response) == 32
        assert all(c in '0123456789abcdef' for c in response)

    def test_calculate_response_sha256(self, authenticator):
        """Test SHA-256 digest calculation"""
        response = authenticator._calculate_response(
            username="alice",
            password="secret123",
            realm="test.local",
            method="INVITE",
            uri="sip:agent@test.local",
            nonce="abc123",
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="xyz789"
        )

        # SHA-256 hash is 64 hex chars
        assert len(response) == 64
        assert all(c in '0123456789abcdef' for c in response)

    def test_validate_response_success(self, authenticator):
        """Test successful authentication"""
        # Generate a real challenge
        challenge = authenticator.generate_challenge()

        # Calculate correct response
        expected_response = authenticator._calculate_response(
            username="alice",
            password="secret123",
            realm="test.local",
            method="INVITE",
            uri="sip:agent@test.local",
            nonce=challenge.nonce,
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        # Create credentials with correct response
        credentials = DigestCredentials(
            username="alice",
            realm="test.local",
            nonce=challenge.nonce,
            uri="sip:agent@test.local",
            response=expected_response,
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is True
        assert error is None

    def test_validate_response_wrong_password(self, authenticator):
        """Test authentication with wrong password"""
        challenge = authenticator.generate_challenge()

        # Calculate response with WRONG password
        wrong_response = authenticator._calculate_response(
            username="alice",
            password="WRONG_PASSWORD",
            realm="test.local",
            method="INVITE",
            uri="sip:agent@test.local",
            nonce=challenge.nonce,
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        credentials = DigestCredentials(
            username="alice",
            realm="test.local",
            nonce=challenge.nonce,
            uri="sip:agent@test.local",
            response=wrong_response,
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is False
        assert error == "Invalid credentials"

    def test_validate_response_unknown_user(self, authenticator):
        """Test authentication with unknown user"""
        challenge = authenticator.generate_challenge()

        credentials = DigestCredentials(
            username="unknown_user",
            realm="test.local",
            nonce=challenge.nonce,
            uri="sip:agent@test.local",
            response="fakehash",
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is False
        assert error == "Unknown user"

    def test_validate_response_expired_nonce(self, authenticator):
        """Test authentication with expired nonce"""
        # Create expired nonce (5 minutes ago)
        old_timestamp = int(time.time()) - 301  # 301 seconds = expired
        expired_nonce = f"abc123:{old_timestamp}"

        credentials = DigestCredentials(
            username="alice",
            realm="test.local",
            nonce=expired_nonce,
            uri="sip:agent@test.local",
            response="somehash",
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is False
        assert error == "Nonce expired"

    def test_validate_response_future_nonce(self, authenticator):
        """Test authentication with future nonce (clock skew attack)"""
        # Create future nonce
        future_timestamp = int(time.time()) + 60  # 1 minute in future
        future_nonce = f"abc123:{future_timestamp}"

        credentials = DigestCredentials(
            username="alice",
            realm="test.local",
            nonce=future_nonce,
            uri="sip:agent@test.local",
            response="somehash",
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is False
        assert error == "Invalid nonce timestamp"

    def test_validate_response_wrong_realm(self, authenticator):
        """Test authentication with wrong realm"""
        challenge = authenticator.generate_challenge()

        expected_response = authenticator._calculate_response(
            username="alice",
            password="secret123",
            realm="WRONG.REALM",
            method="INVITE",
            uri="sip:agent@test.local",
            nonce=challenge.nonce,
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        credentials = DigestCredentials(
            username="alice",
            realm="WRONG.REALM",
            nonce=challenge.nonce,
            uri="sip:agent@test.local",
            response=expected_response,
            algorithm=DigestAlgorithm.SHA256,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is False
        assert error == "Realm mismatch"

    def test_cleanup_expired_nonces(self, authenticator):
        """Test nonce cleanup"""
        # Add some nonces
        current_time = time.time()
        authenticator.nonces = {
            "fresh1": current_time,
            "fresh2": current_time - 100,
            "expired1": current_time - 400,  # Expired
            "expired2": current_time - 500,  # Expired
        }

        authenticator.cleanup_expired_nonces()

        # Only fresh nonces should remain
        assert "fresh1" in authenticator.nonces
        assert "fresh2" in authenticator.nonces
        assert "expired1" not in authenticator.nonces
        assert "expired2" not in authenticator.nonces

    def test_md5_fallback_scenario(self, authenticator):
        """Test MD5 fallback after SHA-256 failure"""
        # Simulate real-world scenario:
        # 1. Client gets SHA-256 challenge
        # 2. Client doesn't support SHA-256
        # 3. Server sends MD5 challenge
        # 4. Client authenticates with MD5

        # Generate MD5 challenge (fallback)
        md5_challenge = authenticator.generate_challenge(algorithm=DigestAlgorithm.MD5)

        # Calculate MD5 response
        md5_response = authenticator._calculate_response(
            username="bob",
            password="password456",
            realm="test.local",
            method="INVITE",
            uri="sip:agent@test.local",
            nonce=md5_challenge.nonce,
            algorithm=DigestAlgorithm.MD5,
            qop="auth",
            nc="00000001",
            cnonce="legacy_client"
        )

        credentials = DigestCredentials(
            username="bob",
            realm="test.local",
            nonce=md5_challenge.nonce,
            uri="sip:agent@test.local",
            response=md5_response,
            algorithm=DigestAlgorithm.MD5,
            qop="auth",
            nc="00000001",
            cnonce="legacy_client"
        )

        is_valid, error = authenticator.validate_response(credentials, "INVITE")

        assert is_valid is True
        assert error is None


class TestDigestCalculations:
    """Test digest calculation edge cases"""

    def test_calculate_response_without_qop(self):
        """Test digest calculation without qop parameter (legacy)"""
        auth = DigestAuthenticator(
            realm="test.local",
            users={"user": "pass"}
        )

        response = auth._calculate_response(
            username="user",
            password="pass",
            realm="test.local",
            method="INVITE",
            uri="sip:test@test.local",
            nonce="nonce123",
            algorithm=DigestAlgorithm.MD5,
            qop=None,  # No qop
            nc=None,
            cnonce=None
        )

        # Should still produce valid hash
        assert len(response) == 32

    def test_calculate_response_sess_variant(self):
        """Test MD5-sess and SHA-256-sess variants"""
        auth = DigestAuthenticator(
            realm="test.local",
            users={"user": "pass"}
        )

        # MD5-sess
        md5_sess = auth._calculate_response(
            username="user",
            password="pass",
            realm="test.local",
            method="INVITE",
            uri="sip:test@test.local",
            nonce="nonce123",
            algorithm=DigestAlgorithm.MD5_SESS,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        # SHA-256-sess
        sha256_sess = auth._calculate_response(
            username="user",
            password="pass",
            realm="test.local",
            method="INVITE",
            uri="sip:test@test.local",
            nonce="nonce123",
            algorithm=DigestAlgorithm.SHA256_SESS,
            qop="auth",
            nc="00000001",
            cnonce="client123"
        )

        assert len(md5_sess) == 32
        assert len(sha256_sess) == 64
        assert md5_sess != sha256_sess


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
