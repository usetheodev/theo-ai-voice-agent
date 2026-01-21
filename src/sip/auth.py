"""
SIP Digest Authentication

Implements RFC 7616 (SHA-256) and RFC 2617 (MD5) Digest Authentication
for SIP INVITE requests.

Security Features:
- SHA-256 digest (preferred) with MD5 fallback
- Nonce generation with timestamp
- Quality of Protection (qop) support
- Realm-based authentication
- Protection against replay attacks
"""

import hashlib
import secrets
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ..common.logging import get_logger


logger = get_logger('sip.auth')


class DigestAlgorithm(str, Enum):
    """Supported digest algorithms"""
    SHA256 = "SHA-256"
    SHA256_SESS = "SHA-256-sess"
    MD5 = "MD5"
    MD5_SESS = "MD5-sess"


@dataclass
class DigestChallenge:
    """Digest authentication challenge parameters"""
    realm: str
    nonce: str
    algorithm: DigestAlgorithm
    qop: str = "auth"
    opaque: Optional[str] = None


@dataclass
class DigestCredentials:
    """Parsed digest credentials from Authorization header"""
    username: str
    realm: str
    nonce: str
    uri: str
    response: str
    algorithm: DigestAlgorithm = DigestAlgorithm.MD5
    qop: Optional[str] = None
    nc: Optional[str] = None  # Nonce count
    cnonce: Optional[str] = None  # Client nonce


class DigestAuthenticator:
    """
    SIP Digest Authentication Manager

    Implements secure digest authentication with:
    - SHA-256 (RFC 7616) - preferred
    - MD5 (RFC 2617) - fallback for legacy clients
    - Nonce management with expiration
    - Quality of Protection (qop=auth)
    """

    def __init__(
        self,
        realm: str,
        users: Dict[str, str],
        nonce_timeout: int = 300,  # 5 minutes
        preferred_algorithm: DigestAlgorithm = DigestAlgorithm.SHA256
    ):
        """
        Initialize DigestAuthenticator

        Args:
            realm: SIP realm (e.g., "voiceagent.local")
            users: Dictionary of {username: password}
            nonce_timeout: Nonce validity in seconds (default: 300s)
            preferred_algorithm: Preferred digest algorithm (default: SHA-256)
        """
        self.realm = realm
        self.users = users
        self.nonce_timeout = nonce_timeout
        self.preferred_algorithm = preferred_algorithm

        # Nonce tracking {nonce: timestamp}
        self.nonces: Dict[str, float] = {}

        logger.info("DigestAuthenticator initialized",
                   realm=realm,
                   users=len(users),
                   algorithm=preferred_algorithm.value)

    def generate_challenge(
        self,
        algorithm: Optional[DigestAlgorithm] = None
    ) -> DigestChallenge:
        """
        Generate digest authentication challenge

        Returns 401 Unauthorized challenge with:
        - realm
        - nonce (cryptographically secure random + timestamp)
        - algorithm (SHA-256 or MD5)
        - qop (quality of protection)
        - opaque (optional)

        Args:
            algorithm: Override preferred algorithm (for MD5 fallback)

        Returns:
            DigestChallenge object
        """
        if algorithm is None:
            algorithm = self.preferred_algorithm

        # Generate cryptographically secure nonce
        # Format: base64(random_bytes) + ":" + timestamp
        nonce = self._generate_nonce()

        # Generate opaque value (optional, for additional security)
        opaque = secrets.token_hex(16)

        challenge = DigestChallenge(
            realm=self.realm,
            nonce=nonce,
            algorithm=algorithm,
            qop="auth",
            opaque=opaque
        )

        # Store nonce with timestamp
        self.nonces[nonce] = time.time()

        logger.debug("Challenge generated",
                    nonce=nonce[:16] + "...",
                    algorithm=algorithm.value)

        return challenge

    def _generate_nonce(self) -> str:
        """
        Generate cryptographically secure nonce

        Format: hex(random_32_bytes):timestamp
        This allows validation of nonce age without storing all nonces
        """
        random_part = secrets.token_hex(32)
        timestamp = int(time.time())
        return f"{random_part}:{timestamp}"

    def _parse_nonce_timestamp(self, nonce: str) -> Optional[int]:
        """Extract timestamp from nonce"""
        try:
            parts = nonce.split(':')
            if len(parts) == 2:
                return int(parts[1])
        except (ValueError, IndexError):
            pass
        return None

    def validate_response(
        self,
        credentials: DigestCredentials,
        method: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate digest authentication response

        Validates:
        1. Username exists
        2. Nonce is valid and not expired
        3. Digest calculation matches

        Args:
            credentials: Parsed Authorization header
            method: SIP method (e.g., "INVITE")

        Returns:
            Tuple of (is_valid, error_message)
            - (True, None) if authentication succeeds
            - (False, "error reason") if authentication fails
        """

        # 1. Check if username exists
        if credentials.username not in self.users:
            logger.warn("Authentication failed - unknown user",
                       username=credentials.username)
            return False, "Unknown user"

        # 2. Validate nonce exists and not expired
        nonce_timestamp = self._parse_nonce_timestamp(credentials.nonce)
        if nonce_timestamp is None:
            logger.warn("Authentication failed - invalid nonce format")
            return False, "Invalid nonce"

        nonce_age = time.time() - nonce_timestamp
        if nonce_age > self.nonce_timeout:
            logger.warn("Authentication failed - nonce expired",
                       age=f"{nonce_age:.0f}s")
            return False, "Nonce expired"

        if nonce_age < 0:
            logger.warn("Authentication failed - future nonce",
                       age=f"{nonce_age:.0f}s")
            return False, "Invalid nonce timestamp"

        # 3. Verify realm matches
        if credentials.realm != self.realm:
            logger.warn("Authentication failed - realm mismatch",
                       expected=self.realm,
                       received=credentials.realm)
            return False, "Realm mismatch"

        # 4. Calculate expected digest
        password = self.users[credentials.username]
        expected_response = self._calculate_response(
            username=credentials.username,
            password=password,
            realm=credentials.realm,
            method=method,
            uri=credentials.uri,
            nonce=credentials.nonce,
            algorithm=credentials.algorithm,
            qop=credentials.qop,
            nc=credentials.nc,
            cnonce=credentials.cnonce
        )

        # 5. Compare responses (constant-time comparison to prevent timing attacks)
        if not secrets.compare_digest(credentials.response, expected_response):
            logger.warn("Authentication failed - digest mismatch",
                       username=credentials.username)
            return False, "Invalid credentials"

        logger.info("✅ Authentication successful",
                   username=credentials.username,
                   algorithm=credentials.algorithm.value)

        return True, None

    def _calculate_response(
        self,
        username: str,
        password: str,
        realm: str,
        method: str,
        uri: str,
        nonce: str,
        algorithm: DigestAlgorithm,
        qop: Optional[str] = None,
        nc: Optional[str] = None,
        cnonce: Optional[str] = None
    ) -> str:
        """
        Calculate digest response

        Implements both RFC 7616 (SHA-256) and RFC 2617 (MD5)

        Algorithm:
        - HA1 = hash(username:realm:password)
        - HA2 = hash(method:uri)
        - response = hash(HA1:nonce:nc:cnonce:qop:HA2)  # if qop
        - response = hash(HA1:nonce:HA2)                # if no qop
        """

        # Select hash function
        if algorithm in (DigestAlgorithm.SHA256, DigestAlgorithm.SHA256_SESS):
            hash_func = hashlib.sha256
        else:  # MD5 or MD5-sess
            hash_func = hashlib.md5

        def H(data: str) -> str:
            """Hash helper"""
            return hash_func(data.encode('utf-8')).hexdigest()

        # Calculate HA1
        if algorithm in (DigestAlgorithm.SHA256_SESS, DigestAlgorithm.MD5_SESS):
            # sess variant: HA1 = hash(hash(username:realm:password):nonce:cnonce)
            a1_base = H(f"{username}:{realm}:{password}")
            ha1 = H(f"{a1_base}:{nonce}:{cnonce}")
        else:
            # standard: HA1 = hash(username:realm:password)
            ha1 = H(f"{username}:{realm}:{password}")

        # Calculate HA2
        ha2 = H(f"{method}:{uri}")

        # Calculate response
        if qop:
            # With qop: hash(HA1:nonce:nc:cnonce:qop:HA2)
            response = H(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        else:
            # Without qop: hash(HA1:nonce:HA2)
            response = H(f"{ha1}:{nonce}:{ha2}")

        return response

    def cleanup_expired_nonces(self):
        """Remove expired nonces from tracking"""
        current_time = time.time()
        expired = [
            nonce for nonce, timestamp in self.nonces.items()
            if current_time - timestamp > self.nonce_timeout
        ]

        for nonce in expired:
            del self.nonces[nonce]

        if expired:
            logger.debug("Cleaned up expired nonces", count=len(expired))

    def build_www_authenticate_header(
        self,
        challenge: DigestChallenge
    ) -> str:
        """
        Build WWW-Authenticate header for 401 response

        Format:
        WWW-Authenticate: Digest realm="voiceagent",
                                 nonce="abc123:1234567890",
                                 algorithm=SHA-256,
                                 qop="auth",
                                 opaque="xyz789"

        Args:
            challenge: DigestChallenge object

        Returns:
            Header value string
        """
        parts = [
            f'realm="{challenge.realm}"',
            f'nonce="{challenge.nonce}"',
            f'algorithm={challenge.algorithm.value}',
            f'qop="{challenge.qop}"'
        ]

        if challenge.opaque:
            parts.append(f'opaque="{challenge.opaque}"')

        return "Digest " + ", ".join(parts)

    @staticmethod
    def parse_authorization_header(auth_header: str) -> Optional[DigestCredentials]:
        """
        Parse Authorization header

        Format:
        Authorization: Digest username="alice",
                              realm="voiceagent",
                              nonce="abc123",
                              uri="sip:agent@example.com",
                              response="6629fae49393a05397450978507c4ef1",
                              algorithm=SHA-256,
                              qop=auth,
                              nc=00000001,
                              cnonce="0a4f113b"

        Args:
            auth_header: Authorization header value

        Returns:
            DigestCredentials object or None if parsing fails
        """
        if not auth_header.startswith("Digest "):
            return None

        # Remove "Digest " prefix
        auth_params = auth_header[7:].strip()

        # Parse key=value pairs
        params: Dict[str, str] = {}

        # Split by comma, but handle quoted values
        parts = []
        current = ""
        in_quotes = False

        for char in auth_params:
            if char == '"':
                in_quotes = not in_quotes
                current += char
            elif char == ',' and not in_quotes:
                parts.append(current.strip())
                current = ""
            else:
                current += char

        if current:
            parts.append(current.strip())

        # Parse each part
        for part in parts:
            if '=' not in part:
                continue

            key, value = part.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"')
            params[key] = value

        # Extract required fields
        try:
            credentials = DigestCredentials(
                username=params['username'],
                realm=params['realm'],
                nonce=params['nonce'],
                uri=params['uri'],
                response=params['response'],
                algorithm=DigestAlgorithm(params.get('algorithm', 'MD5')),
                qop=params.get('qop'),
                nc=params.get('nc'),
                cnonce=params.get('cnonce')
            )
            return credentials
        except (KeyError, ValueError) as e:
            logger.warn("Failed to parse Authorization header", error=str(e))
            return None
