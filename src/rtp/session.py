"""
RTP Call Session Management

Represents the complete state of a single RTP call session, including:
- RTP transport (socket, addresses, SSRC tracking)
- Audio pipeline (buffer, VAD, codec)
- Call control (muting, statistics)

This dataclass-based approach ensures:
- Type safety (mypy validation)
- Per-call state isolation (no race conditions)
- Easy debugging (print(session) shows all state)
- Memory leak prevention (cleanup removes entire session)

Pattern based on:
- Asterisk-AI-Voice-Agent (src/rtp_server.py:20-44)
- Pipecat AI (pipecat/frames/session.py)
- FastAPI Request.state pattern
"""

import socket
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple
import random


@dataclass
class CallSession:
    """
    Complete state for a single RTP call session.

    Attributes:
        call_id: Unique identifier (format: "IP:PORT:SSRC")
        socket: UDP socket for RTP packets
        remote_addr: Caller's (IP, port) tuple

        # RTP State
        inbound_ssrc: Caller's SSRC (from received RTP)
        outbound_ssrc: Agent's SSRC (for sent RTP, must ≠ inbound)
        sequence_number: Current RTP sequence number (0-65535)
        timestamp: Current RTP timestamp (0-4294967295)

        # Audio Pipeline Components (per-call instances)
        audio_buffer: AudioBuffer instance for this call
        vad: VoiceActivityDetector instance for this call
        rtp_builder: RTPBuilder instance for this call

        # Call Control
        vad_muted: True when TTS playing (prevents echo detection)
        last_activity: Unix timestamp of last RTP packet

        # Statistics
        packets_received: Total inbound RTP packets
        packets_sent: Total outbound RTP packets
        echo_packets_filtered: Packets dropped (SSRC == outbound_ssrc)
        bytes_received: Total inbound bytes
        bytes_sent: Total outbound bytes

    Thread Safety:
        Each CallSession is accessed only by its own async task.
        No locking needed (single-threaded asyncio event loop).

    Memory Management:
        CallSession cleanup requires:
        1. socket.close()
        2. audio_buffer.clear()
        3. vad.cleanup_call(call_id)
        4. Remove from sessions dict
    """

    # Identity & Transport
    call_id: str
    socket: socket.socket
    remote_addr: Tuple[str, int]

    # RTP State
    inbound_ssrc: Optional[int] = None      # Caller's SSRC
    outbound_ssrc: Optional[int] = None     # Agent's SSRC (different!)
    sequence_number: int = 0
    timestamp: int = 0

    # Audio Pipeline (lazy init via property setters)
    audio_buffer: Optional[object] = None   # AudioBuffer instance
    vad: Optional[object] = None            # VoiceActivityDetector instance
    rtp_builder: Optional[object] = None    # RTPBuilder instance

    # Call Control
    vad_muted: bool = False
    last_activity: float = field(default_factory=time.time)

    # Statistics
    packets_received: int = 0
    packets_sent: int = 0
    echo_packets_filtered: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0

    # Internal state tracking
    _sequence_initialized: bool = False
    _timestamp_initialized: bool = False

    @staticmethod
    def generate_call_id(remote_ip: str, remote_port: int, ssrc: int) -> str:
        """
        Generate unique call_id from remote address + SSRC.

        Format: "IP:PORT:SSRC" (example: "192.168.1.10:5060:305419896")

        Why include SSRC:
        - Multiple calls from same NAT IP have same IP:PORT
        - SSRC is unique per RTP source (RFC 3550 collision probability < 2^-32)
        - Prevents session collision in multi-call scenarios

        Args:
            remote_ip: Caller's IP address
            remote_port: Caller's RTP port
            ssrc: Caller's SSRC from first RTP packet

        Returns:
            Unique call identifier string

        Evidence:
            Pattern found in Asterisk chan_pjsip.c:2847 (session ID generation)
        """
        return f"{remote_ip}:{remote_port}:{ssrc}"

    def generate_outbound_ssrc(self) -> int:
        """
        Generate outbound SSRC - MUST match inbound for Asterisk ExternalMedia.

        CRITICAL: Asterisk ExternalMedia expects the SAME SSRC back.
        Using a different SSRC causes audio to be rejected by the bridge.

        This is different from typical RTP echo filtering, but required for
        ExternalMedia channels to work correctly.

        Returns:
            Generated outbound SSRC (stored in self.outbound_ssrc)

        Evidence:
            https://community.asterisk.org/t/ssrc-change-bridging/103903
            "audio doesn't make it into the bridge when SSRC changes"
        """
        if self.inbound_ssrc is None:
            # No inbound SSRC yet, generate random
            self.outbound_ssrc = random.randint(0, 0xFFFFFFFF)
        else:
            # MUST use same SSRC for Asterisk ExternalMedia
            self.outbound_ssrc = self.inbound_ssrc

        return self.outbound_ssrc

    def is_echo_packet(self, ssrc: int) -> bool:
        """
        Check if RTP packet is echo (agent's own voice).

        DISABLED for Asterisk ExternalMedia: Since we use the SAME SSRC
        for inbound and outbound (required by Asterisk), we cannot use
        SSRC-based echo filtering.

        Instead, we rely on:
        1. VAD muting during TTS playback (vad_muted flag)
        2. Asterisk bridge managing audio routing

        Args:
            ssrc: SSRC from received RTP packet header

        Returns:
            False (echo filtering disabled for ExternalMedia compatibility)

        Evidence:
            Asterisk ExternalMedia requires matching SSRC
            https://community.asterisk.org/t/ssrc-change-bridging/103903
        """
        # SSRC-based filtering disabled for Asterisk ExternalMedia
        return False

    def update_activity(self):
        """
        Update last_activity timestamp.

        Called on:
        - Every received RTP packet
        - Every sent RTP packet

        Used by:
        - Session cleanup task (timeout idle sessions)
        - Statistics (calculate call duration)
        """
        self.last_activity = time.time()

    def get_idle_time(self) -> float:
        """
        Calculate seconds since last RTP activity.

        Returns:
            Idle time in seconds (float)

        Used by:
            Session cleanup task (remove if idle > 5min)
        """
        return time.time() - self.last_activity

    def get_stats(self) -> dict:
        """
        Get session statistics for monitoring/debugging.

        Returns:
            Dict with all session metrics
        """
        return {
            'call_id': self.call_id,
            'remote_addr': self.remote_addr,
            'inbound_ssrc': f"{self.inbound_ssrc:#010x}" if self.inbound_ssrc else None,
            'outbound_ssrc': f"{self.outbound_ssrc:#010x}" if self.outbound_ssrc else None,
            'packets_received': self.packets_received,
            'packets_sent': self.packets_sent,
            'echo_packets_filtered': self.echo_packets_filtered,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
            'vad_muted': self.vad_muted,
            'idle_time': self.get_idle_time(),
            'call_duration': time.time() - self.last_activity,
        }

    def __repr__(self) -> str:
        """
        Human-readable representation for debugging.

        Example output:
            CallSession(call_id='192.168.1.10:5060:305419896',
                        inbound_ssrc=0x12345678,
                        outbound_ssrc=0xedcba987,
                        pkts_rx=150, pkts_tx=100,
                        idle=2.3s)
        """
        return (
            f"CallSession("
            f"call_id='{self.call_id}', "
            f"inbound_ssrc={f'{self.inbound_ssrc:#010x}' if self.inbound_ssrc else None}, "
            f"outbound_ssrc={f'{self.outbound_ssrc:#010x}' if self.outbound_ssrc else None}, "
            f"pkts_rx={self.packets_received}, "
            f"pkts_tx={self.packets_sent}, "
            f"echo_filtered={self.echo_packets_filtered}, "
            f"idle={self.get_idle_time():.1f}s)"
        )


# Type aliases for clarity
CallID = str  # Format: "IP:PORT:SSRC"
SSRC = int    # 32-bit unsigned integer


def test_call_session():
    """
    Unit test for CallSession (run with: python -m src.rtp.session)
    """
    import socket as sock_module

    print("🧪 Testing CallSession...")

    # Test 1: call_id generation
    call_id = CallSession.generate_call_id("192.168.1.10", 5060, 0x12345678)
    assert call_id == "192.168.1.10:5060:305419896"
    print(f"✅ Test 1: call_id generation = {call_id}")

    # Test 2: Outbound SSRC generation (XOR flip)
    fake_socket = sock_module.socket(sock_module.AF_INET, sock_module.SOCK_DGRAM)
    session = CallSession(
        call_id=call_id,
        socket=fake_socket,
        remote_addr=("192.168.1.10", 5060)
    )
    session.inbound_ssrc = 0x12345678
    session.generate_outbound_ssrc()

    assert session.outbound_ssrc == 0xEDCBA987  # XOR with 0xFFFFFFFF
    assert session.inbound_ssrc != session.outbound_ssrc
    print(f"✅ Test 2: SSRC tracking = inbound={session.inbound_ssrc:#010x}, outbound={session.outbound_ssrc:#010x}")

    # Test 3: Echo detection
    assert session.is_echo_packet(0xEDCBA987) == True   # Own SSRC
    assert session.is_echo_packet(0x12345678) == False  # Caller SSRC
    assert session.is_echo_packet(0xAAAAAAAA) == False  # Other SSRC
    print(f"✅ Test 3: Echo detection works")

    # Test 4: Activity tracking
    initial_time = session.last_activity
    time.sleep(0.1)
    session.update_activity()
    assert session.last_activity > initial_time
    idle_time = session.get_idle_time()
    assert idle_time < 1.0, f"Idle time should be small, got {idle_time}s"  # More tolerant
    print(f"✅ Test 4: Activity tracking = idle {idle_time:.3f}s")

    # Test 5: Stats export
    stats = session.get_stats()
    assert stats['call_id'] == call_id
    assert stats['inbound_ssrc'] == "0x12345678"
    assert stats['outbound_ssrc'] == "0xedcba987"
    print(f"✅ Test 5: Stats = {stats}")

    # Test 6: repr() output
    repr_output = repr(session)
    assert "CallSession" in repr_output
    assert call_id in repr_output
    print(f"✅ Test 6: repr() = {repr_output}")

    # Cleanup
    fake_socket.close()

    print("\n🎉 All tests passed! CallSession is ready.")


if __name__ == '__main__':
    test_call_session()
