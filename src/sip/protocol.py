"""
SIP Protocol Utilities

Migrated from LiveKit SIP (Go) - pkg/sip/protocol.go
"""

import re
import hashlib
from typing import Dict, Optional, Tuple
from enum import IntEnum

from .session import URI, Transport


class SIPStatus(IntEnum):
    """SIP Status Codes"""
    # 1xx - Provisional
    TRYING = 100
    RINGING = 180
    CALL_IS_FORWARDED = 181
    QUEUED = 182
    SESSION_PROGRESS = 183

    # 2xx - Success
    OK = 200
    ACCEPTED = 202

    # 3xx - Redirection
    MOVED_PERMANENTLY = 301
    MOVED_TEMPORARILY = 302
    USE_PROXY = 305

    # 4xx - Client Error
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    PAYMENT_REQUIRED = 402
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    NOT_ACCEPTABLE = 406
    PROXY_AUTH_REQUIRED = 407
    REQUEST_TIMEOUT = 408
    CONFLICT = 409
    GONE = 410
    REQUEST_ENTITY_TOO_LARGE = 413
    REQUEST_URI_TOO_LONG = 414
    UNSUPPORTED_MEDIA_TYPE = 415
    BAD_EXTENSION = 420
    EXTENSION_REQUIRED = 421
    INTERVAL_TOO_BRIEF = 423
    TEMPORARILY_UNAVAILABLE = 480
    CALL_TRANSACTION_DOES_NOT_EXIST = 481
    LOOP_DETECTED = 482
    TOO_MANY_HOPS = 483
    ADDRESS_INCOMPLETE = 484
    AMBIGUOUS = 485
    BUSY_HERE = 486
    REQUEST_TERMINATED = 487
    NOT_ACCEPTABLE_HERE = 488

    # 5xx - Server Error
    INTERNAL_SERVER_ERROR = 500
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504
    VERSION_NOT_SUPPORTED = 505
    MESSAGE_TOO_LARGE = 513

    # 6xx - Global Failure
    GLOBAL_BUSY_EVERYWHERE = 600
    GLOBAL_DECLINE = 603
    GLOBAL_DOES_NOT_EXIST_ANYWHERE = 604
    GLOBAL_NOT_ACCEPTABLE = 606


# Status code to name mapping
STATUS_NAMES = {
    100: "Trying",
    180: "Ringing",
    181: "Call Is Forwarded",
    182: "Queued",
    183: "Session In Progress",
    200: "OK",
    202: "Accepted",
    301: "Moved Permanently",
    302: "Moved Temporarily",
    305: "Use Proxy",
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Auth Required",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    413: "Request Entity Too Large",
    414: "Request URI Too Long",
    415: "Unsupported Media Type",
    416: "Requested Range Not Satisfiable",
    420: "Bad Extension",
    421: "Extension Required",
    423: "Interval Too Brief",
    480: "Temporarily Unavailable",
    481: "Call/Transaction Does Not Exist",
    482: "Loop Detected",
    483: "Too Many Hops",
    484: "Address Incomplete",
    485: "Ambiguous",
    486: "Busy Here",
    487: "Request Terminated",
    488: "Not Acceptable Here",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "Version Not Supported",
    513: "Message Too Large",
    600: "Busy Everywhere",
    603: "Decline",
    604: "Does Not Exist Anywhere",
    606: "Not Acceptable",
}


def status_name(status_code: int) -> str:
    """Get human-readable status name"""
    name = STATUS_NAMES.get(status_code, "Unknown")
    return f"{status_code}-{name}"


def generate_tag() -> str:
    """Generate a random SIP tag"""
    import uuid
    return str(uuid.uuid4())[:8]


def generate_call_id() -> str:
    """Generate a unique Call-ID"""
    import uuid
    return str(uuid.uuid4())


def generate_branch() -> str:
    """Generate a unique branch ID for Via header"""
    import uuid
    return f"z9hG4bK{str(uuid.uuid4())[:16]}"


def parse_via_header(via: str) -> Tuple[str, str, int, Dict[str, str]]:
    """
    Parse Via header

    Returns: (protocol, host, port, params)
    Example: "SIP/2.0/UDP 192.168.1.1:5060;branch=z9hG4bK..."
    """
    params = {}

    # Split by semicolon for parameters
    parts = via.split(';')
    via_main = parts[0].strip()

    # Parse parameters
    for param in parts[1:]:
        if '=' in param:
            key, value = param.split('=', 1)
            params[key.strip()] = value.strip()
        else:
            params[param.strip()] = ''

    # Parse protocol/version/transport host:port
    protocol_parts = via_main.split()
    if len(protocol_parts) < 2:
        raise ValueError(f"Invalid Via header: {via}")

    protocol = protocol_parts[0]  # "SIP/2.0/UDP"
    host_port = protocol_parts[1]

    # Parse host:port
    if ':' in host_port:
        host, port_str = host_port.rsplit(':', 1)
        port = int(port_str)
    else:
        host = host_port
        port = 5060

    return protocol, host, port, params


def build_via_header(protocol: str, host: str, port: int, params: Dict[str, str]) -> str:
    """Build Via header string"""
    via = f"{protocol} {host}:{port}"

    for key, value in params.items():
        if value:
            via += f";{key}={value}"
        else:
            via += f";{key}"

    return via


def parse_contact_header(contact: str) -> Tuple[Optional[str], URI]:
    """
    Parse Contact header

    Returns: (display_name, URI)
    Example: "Alice <sip:alice@example.com:5060>;expires=3600"
    """
    # Remove parameters
    if ';' in contact:
        contact_main, _ = contact.split(';', 1)
    else:
        contact_main = contact

    contact_main = contact_main.strip()

    # Check for display name
    if '<' in contact_main and '>' in contact_main:
        display_name = contact_main[:contact_main.index('<')].strip(' "')
        uri_str = contact_main[contact_main.index('<')+1:contact_main.index('>')].strip()
    else:
        display_name = None
        uri_str = contact_main

    uri = URI.from_string(uri_str)

    return display_name, uri


def build_contact_header(display_name: Optional[str], uri: URI, params: Optional[Dict[str, str]] = None) -> str:
    """Build Contact header string"""
    uri_str = uri.to_sip_uri()

    if display_name:
        contact = f'"{display_name}" <{uri_str}>'
    else:
        contact = f"<{uri_str}>"

    if params:
        for key, value in params.items():
            if value:
                contact += f";{key}={value}"
            else:
                contact += f";{key}"

    return contact


def compute_digest_response(
    username: str,
    realm: str,
    password: str,
    method: str,
    uri: str,
    nonce: str,
    qop: Optional[str] = None,
    cnonce: Optional[str] = None,
    nc: Optional[str] = None
) -> str:
    """
    Compute Digest Authentication response (RFC 2617)

    Migrated from LiveKit client.go digest auth logic
    """
    # HA1 = MD5(username:realm:password)
    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()

    # HA2 = MD5(method:uri)
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()

    # Compute response
    if qop and qop in ('auth', 'auth-int'):
        # response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
        if not cnonce or not nc:
            raise ValueError("cnonce and nc required for qop=auth")
        response_str = f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}"
    else:
        # response = MD5(HA1:nonce:HA2)
        response_str = f"{ha1}:{nonce}:{ha2}"

    response = hashlib.md5(response_str.encode()).hexdigest()

    return response


def parse_www_authenticate(www_auth: str) -> Dict[str, str]:
    """
    Parse WWW-Authenticate header

    Example: 'Digest realm="asterisk", nonce="...", algorithm=MD5, qop="auth"'
    """
    params = {}

    # Remove "Digest " prefix
    if www_auth.lower().startswith('digest '):
        www_auth = www_auth[7:]

    # Parse key=value pairs
    for part in www_auth.split(','):
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            key = key.strip()
            value = value.strip(' "')
            params[key] = value

    return params


def build_authorization_header(
    username: str,
    realm: str,
    nonce: str,
    uri: str,
    response: str,
    algorithm: str = "MD5",
    qop: Optional[str] = None,
    cnonce: Optional[str] = None,
    nc: Optional[str] = None,
    opaque: Optional[str] = None
) -> str:
    """Build Authorization header"""
    auth = f'Digest username="{username}", '
    auth += f'realm="{realm}", '
    auth += f'nonce="{nonce}", '
    auth += f'uri="{uri}", '
    auth += f'response="{response}", '
    auth += f'algorithm={algorithm}'

    if qop:
        auth += f', qop={qop}'
    if cnonce:
        auth += f', cnonce="{cnonce}"'
    if nc:
        auth += f', nc={nc}'
    if opaque:
        auth += f', opaque="{opaque}"'

    return auth


def extract_transport_from_via(via: str) -> Transport:
    """Extract transport protocol from Via header"""
    protocol_part = via.split()[0] if via.split() else ""

    if '/UDP' in protocol_part.upper():
        return Transport.UDP
    elif '/TCP' in protocol_part.upper():
        return Transport.TCP
    elif '/TLS' in protocol_part.upper():
        return Transport.TLS

    return Transport.UDP  # Default


# SIP Methods
class SIPMethod:
    INVITE = "INVITE"
    ACK = "ACK"
    BYE = "BYE"
    CANCEL = "CANCEL"
    REGISTER = "REGISTER"
    OPTIONS = "OPTIONS"
    INFO = "INFO"
    REFER = "REFER"
    NOTIFY = "NOTIFY"
    MESSAGE = "MESSAGE"
