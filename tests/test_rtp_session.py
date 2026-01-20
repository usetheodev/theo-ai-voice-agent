"""
Unit Tests - CallSession Dataclass

Tests per-call session management, SSRC tracking, and echo detection.

Coverage Target: 100% (CallSession is critical infrastructure)
"""

import pytest
import socket
import time
from src.rtp.session import CallSession


class TestCallSessionCreation:
    """Test CallSession initialization and factory methods."""

    def test_call_id_generation_basic(self):
        """Call ID should include IP, port, and SSRC."""
        call_id = CallSession.generate_call_id("192.168.1.10", 5060, 0x12345678)
        assert call_id == "192.168.1.10:5060:305419896"

    def test_call_id_uniqueness_same_ip_different_ssrc(self):
        """Different SSRCs from same IP should generate different call_ids."""
        call_id1 = CallSession.generate_call_id("192.168.1.10", 5060, 0x11111111)
        call_id2 = CallSession.generate_call_id("192.168.1.10", 5060, 0x22222222)
        assert call_id1 != call_id2
        assert "192.168.1.10:5060" in call_id1
        assert "192.168.1.10:5060" in call_id2

    def test_call_id_uniqueness_different_ports(self):
        """Different ports should generate different call_ids."""
        call_id1 = CallSession.generate_call_id("192.168.1.10", 5060, 0x12345678)
        call_id2 = CallSession.generate_call_id("192.168.1.10", 5070, 0x12345678)
        assert call_id1 != call_id2

    def test_session_creation(self):
        """CallSession should initialize with correct defaults."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test-call",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )

            assert session.call_id == "test-call"
            assert session.remote_addr == ("192.168.1.10", 5060)
            assert session.inbound_ssrc is None
            assert session.outbound_ssrc is None
            assert session.packets_received == 0
            assert session.packets_sent == 0
            assert session.echo_packets_filtered == 0
            assert session.vad_muted is False
        finally:
            sock.close()


class TestSSRCTracking:
    """Test SSRC generation and tracking."""

    def test_outbound_ssrc_different_from_inbound(self):
        """Outbound SSRC must differ from inbound (echo filtering requirement)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x12345678
            session.generate_outbound_ssrc()

            assert session.outbound_ssrc is not None
            assert session.outbound_ssrc != session.inbound_ssrc
        finally:
            sock.close()

    def test_outbound_ssrc_xor_flip(self):
        """Outbound SSRC should be XOR flip of inbound."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x12345678
            session.generate_outbound_ssrc()

            # XOR flip: inbound XOR 0xFFFFFFFF
            expected = (0x12345678 ^ 0xFFFFFFFF) & 0xFFFFFFFF
            assert session.outbound_ssrc == expected
            assert session.outbound_ssrc == 0xEDCBA987
        finally:
            sock.close()

    def test_outbound_ssrc_random_when_no_inbound(self):
        """Outbound SSRC should be random if inbound not set."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            # No inbound_ssrc set
            session.generate_outbound_ssrc()

            assert session.outbound_ssrc is not None
            assert 0 <= session.outbound_ssrc <= 0xFFFFFFFF
        finally:
            sock.close()


class TestEchoDetection:
    """Test echo packet detection (critical for full-duplex)."""

    def test_is_echo_packet_true(self):
        """Packet with SSRC == outbound_ssrc should be detected as echo."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x11111111
            session.outbound_ssrc = 0xEEEEEEEE

            # Packet with agent's SSRC
            assert session.is_echo_packet(0xEEEEEEEE) is True
        finally:
            sock.close()

    def test_is_echo_packet_false_caller_ssrc(self):
        """Packet with caller's SSRC should NOT be echo."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x11111111
            session.outbound_ssrc = 0xEEEEEEEE

            # Packet with caller's SSRC
            assert session.is_echo_packet(0x11111111) is False
        finally:
            sock.close()

    def test_is_echo_packet_false_other_ssrc(self):
        """Packet with unknown SSRC should NOT be echo."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x11111111
            session.outbound_ssrc = 0xEEEEEEEE

            # Packet with different SSRC
            assert session.is_echo_packet(0xAAAAAAAA) is False
        finally:
            sock.close()

    def test_is_echo_packet_false_when_outbound_not_set(self):
        """Should not detect echo if outbound_ssrc not initialized."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            # outbound_ssrc = None

            assert session.is_echo_packet(0x12345678) is False
        finally:
            sock.close()


class TestActivityTracking:
    """Test activity timestamp tracking."""

    def test_update_activity(self):
        """update_activity() should update last_activity timestamp."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            initial_time = session.last_activity
            time.sleep(0.01)
            session.update_activity()

            assert session.last_activity > initial_time
        finally:
            sock.close()

    def test_get_idle_time(self):
        """get_idle_time() should return seconds since last activity."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            time.sleep(0.1)
            idle = session.get_idle_time()

            assert idle >= 0.1
            assert idle < 0.5  # Should be recent
        finally:
            sock.close()


class TestStatistics:
    """Test session statistics tracking."""

    def test_get_stats_format(self):
        """get_stats() should return dict with all metrics."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test-call-id",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x12345678
            session.outbound_ssrc = 0xEDCBA987
            session.packets_received = 100
            session.packets_sent = 50
            session.echo_packets_filtered = 5

            stats = session.get_stats()

            assert stats['call_id'] == "test-call-id"
            assert stats['remote_addr'] == ("192.168.1.10", 5060)
            assert stats['inbound_ssrc'] == "0x12345678"
            assert stats['outbound_ssrc'] == "0xedcba987"
            assert stats['packets_received'] == 100
            assert stats['packets_sent'] == 50
            assert stats['echo_packets_filtered'] == 5
            assert 'idle_time' in stats
            assert 'call_duration' in stats
        finally:
            sock.close()

    def test_repr_output(self):
        """__repr__() should include key session info."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="192.168.1.10:5060:305419896",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x12345678
            session.outbound_ssrc = 0xEDCBA987
            session.packets_received = 150
            session.packets_sent = 100

            repr_str = repr(session)

            assert "CallSession" in repr_str
            assert "192.168.1.10:5060:305419896" in repr_str
            assert "0x12345678" in repr_str
            assert "0xedcba987" in repr_str
            assert "pkts_rx=150" in repr_str
            assert "pkts_tx=100" in repr_str
        finally:
            sock.close()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_ssrc_collision_scenario(self):
        """Test behavior when SSRCs collide (extremely rare)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            # Simulate collision: inbound == outbound (shouldn't happen with XOR)
            session.inbound_ssrc = 0x12345678
            session.outbound_ssrc = 0x12345678  # Manually set same

            # Echo detection should still work
            assert session.is_echo_packet(0x12345678) is True
        finally:
            sock.close()

    def test_multiple_ssrc_generation_idempotent(self):
        """Calling generate_outbound_ssrc() multiple times should be safe."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x12345678

            ssrc1 = session.generate_outbound_ssrc()
            ssrc2 = session.generate_outbound_ssrc()

            # Should generate same result (deterministic XOR)
            assert ssrc1 == ssrc2
            assert ssrc1 == 0xEDCBA987
        finally:
            sock.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
