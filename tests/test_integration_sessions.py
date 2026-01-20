"""
Integration Tests - Session Management

Tests CallSession integration scenarios focusing on:
- Multi-session state isolation
- SSRC collision handling
- Cleanup workflows
- Statistics aggregation

These tests validate session management WITHOUT requiring full RTPServer
initialization (which pulls in ASR/LLM/TTS dependencies).

Coverage Target: 80%+ session management paths

Pattern: Unit → Integration → Smoke (progressive testing strategy)
"""

import pytest
import socket
import time
from src.rtp.session import CallSession


class TestMultiSessionIsolation:
    """Test that multiple CallSession instances maintain independent state."""

    def test_two_sessions_independent_ssrcs(self):
        """
        Two sessions should have independent SSRC values.

        Validates: XOR flip generates different outbound SSRCs.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Create two sessions with different inbound SSRCs
            session1 = CallSession(
                call_id="192.168.1.10:5060:1111",
                socket=sock1,
                remote_addr=("192.168.1.10", 5060)
            )
            session1.inbound_ssrc = 0x11111111
            session1.generate_outbound_ssrc()

            session2 = CallSession(
                call_id="192.168.1.20:5060:2222",
                socket=sock2,
                remote_addr=("192.168.1.20", 5060)
            )
            session2.inbound_ssrc = 0x22222222
            session2.generate_outbound_ssrc()

            # Validate independence
            assert session1.inbound_ssrc != session2.inbound_ssrc
            assert session1.outbound_ssrc != session2.outbound_ssrc

            # Validate XOR flip worked correctly for both
            expected_out1 = (0x11111111 ^ 0xFFFFFFFF) & 0xFFFFFFFF
            expected_out2 = (0x22222222 ^ 0xFFFFFFFF) & 0xFFFFFFFF

            assert session1.outbound_ssrc == expected_out1
            assert session2.outbound_ssrc == expected_out2

        finally:
            sock1.close()
            sock2.close()

    def test_three_sessions_unique_call_ids(self):
        """
        Three sessions from different clients should have unique call_ids.

        Scenario: Three users calling simultaneously.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock3 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Different IPs, different SSRCs
            call_id1 = CallSession.generate_call_id("192.168.1.10", 5060, 0xAAAAAAAA)
            call_id2 = CallSession.generate_call_id("192.168.1.20", 5060, 0xBBBBBBBB)
            call_id3 = CallSession.generate_call_id("192.168.1.30", 5060, 0xCCCCCCCC)

            # All must be unique
            call_ids = {call_id1, call_id2, call_id3}
            assert len(call_ids) == 3

            # Create actual sessions
            session1 = CallSession(call_id=call_id1, socket=sock1,
                                  remote_addr=("192.168.1.10", 5060))
            session2 = CallSession(call_id=call_id2, socket=sock2,
                                  remote_addr=("192.168.1.20", 5060))
            session3 = CallSession(call_id=call_id3, socket=sock3,
                                  remote_addr=("192.168.1.30", 5060))

            # Validate all have unique identities
            assert session1.call_id != session2.call_id
            assert session2.call_id != session3.call_id
            assert session1.call_id != session3.call_id

        finally:
            sock1.close()
            sock2.close()
            sock3.close()

    def test_packet_counters_independent(self):
        """
        Packet counters should be independent per session.

        Validates: No cross-talk between session statistics.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            session1 = CallSession(
                call_id="test1",
                socket=sock1,
                remote_addr=("192.168.1.10", 5060)
            )

            session2 = CallSession(
                call_id="test2",
                socket=sock2,
                remote_addr=("192.168.1.20", 5060)
            )

            # Simulate packet reception on session1
            session1.packets_received = 10
            session1.packets_sent = 5

            # Simulate different counts on session2
            session2.packets_received = 20
            session2.packets_sent = 15

            # Validate independence
            assert session1.packets_received == 10
            assert session1.packets_sent == 5
            assert session2.packets_received == 20
            assert session2.packets_sent == 15

            # Get stats from both
            stats1 = session1.get_stats()
            stats2 = session2.get_stats()

            assert stats1['packets_received'] == 10
            assert stats2['packets_received'] == 20
            assert stats1['packets_sent'] != stats2['packets_sent']

        finally:
            sock1.close()
            sock2.close()


class TestSSRCCollisionScenarios:
    """Test rare but critical SSRC collision scenarios."""

    def test_same_ip_different_ports_different_ssrc(self):
        """
        Same IP but different ports with different SSRCs: unique call_ids.

        Scenario: Two NAT clients from same public IP.
        """
        # Same IP, different ports, different SSRCs
        call_id1 = CallSession.generate_call_id("203.0.113.1", 5060, 0x11111111)
        call_id2 = CallSession.generate_call_id("203.0.113.1", 5070, 0x22222222)

        assert call_id1 != call_id2

    def test_same_ip_different_ports_same_ssrc(self):
        """
        Same IP, different ports, SAME SSRC: still unique call_ids.

        Critical: Prevents NAT collision when SSRCs collide.
        """
        # Same IP, different ports, SAME SSRC
        same_ssrc = 0x12345678
        call_id1 = CallSession.generate_call_id("203.0.113.1", 5060, same_ssrc)
        call_id2 = CallSession.generate_call_id("203.0.113.1", 5070, same_ssrc)

        # Must still be unique (port differentiates)
        assert call_id1 != call_id2
        assert "5060" in call_id1
        assert "5070" in call_id2

    def test_different_ips_same_ssrc(self):
        """
        Different IPs with same SSRC: unique call_ids.

        Scenario: Two clients accidentally using same random SSRC.
        """
        same_ssrc = 0xAAAAAAAA
        call_id1 = CallSession.generate_call_id("192.168.1.10", 5060, same_ssrc)
        call_id2 = CallSession.generate_call_id("192.168.1.20", 5060, same_ssrc)

        assert call_id1 != call_id2
        assert "192.168.1.10" in call_id1
        assert "192.168.1.20" in call_id2


class TestEchoDetectionIntegration:
    """Test echo detection with realistic multi-session scenarios."""

    def test_echo_detection_multi_session(self):
        """
        Echo detection should work correctly with multiple sessions.

        Validates: Session A's outbound != Session B's outbound.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Create two sessions
            session1 = CallSession(
                call_id="test1",
                socket=sock1,
                remote_addr=("192.168.1.10", 5060)
            )
            session1.inbound_ssrc = 0x11111111
            session1.generate_outbound_ssrc()

            session2 = CallSession(
                call_id="test2",
                socket=sock2,
                remote_addr=("192.168.1.20", 5060)
            )
            session2.inbound_ssrc = 0x22222222
            session2.generate_outbound_ssrc()

            # Session 1's echo detection
            assert session1.is_echo_packet(session1.outbound_ssrc) is True
            assert session1.is_echo_packet(session1.inbound_ssrc) is False

            # Session 2's echo detection
            assert session2.is_echo_packet(session2.outbound_ssrc) is True
            assert session2.is_echo_packet(session2.inbound_ssrc) is False

            # Cross-session: Session 1's outbound is NOT echo for Session 2
            assert session2.is_echo_packet(session1.outbound_ssrc) is False
            assert session1.is_echo_packet(session2.outbound_ssrc) is False

        finally:
            sock1.close()
            sock2.close()

    def test_echo_filtering_statistics(self):
        """
        Echo packet counter should track filtered packets correctly.

        Validates: echo_packets_filtered increments properly.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            session = CallSession(
                call_id="test",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x11111111
            session.generate_outbound_ssrc()

            # Simulate echo detection workflow
            for i in range(10):
                # Simulate receiving packet
                test_ssrc = session.outbound_ssrc if i % 3 == 0 else session.inbound_ssrc

                if session.is_echo_packet(test_ssrc):
                    session.echo_packets_filtered += 1
                else:
                    session.packets_received += 1

            # Validate counters
            assert session.echo_packets_filtered > 0  # Some were filtered
            assert session.packets_received > 0  # Some were processed

            # Get stats
            stats = session.get_stats()
            assert stats['echo_packets_filtered'] == session.echo_packets_filtered

        finally:
            sock.close()


class TestActivityTracking:
    """Test activity timestamp tracking across sessions."""

    def test_activity_updates_per_session(self):
        """
        Activity timestamps should update independently per session.

        Validates: No shared state for last_activity.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            session1 = CallSession(call_id="test1", socket=sock1,
                                  remote_addr=("192.168.1.10", 5060))
            session2 = CallSession(call_id="test2", socket=sock2,
                                  remote_addr=("192.168.1.20", 5060))

            # Initial timestamps should be different (created at different times)
            initial1 = session1.last_activity
            time.sleep(0.01)
            initial2 = session2.last_activity

            assert initial2 > initial1

            # Update session1 activity
            time.sleep(0.01)
            session1.update_activity()

            # Session2 should not be affected
            assert session1.last_activity > initial1
            assert session2.last_activity == initial2

        finally:
            sock1.close()
            sock2.close()

    def test_idle_time_calculation(self):
        """
        Idle time should be calculated correctly per session.

        Validates: get_idle_time() works independently.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            session1 = CallSession(call_id="test1", socket=sock1,
                                  remote_addr=("192.168.1.10", 5060))
            session2 = CallSession(call_id="test2", socket=sock2,
                                  remote_addr=("192.168.1.20", 5060))

            # Make session1 older
            session1.last_activity = time.time() - 100  # 100s ago

            # Session2 is recent
            session2.last_activity = time.time()

            # Get idle times
            idle1 = session1.get_idle_time()
            idle2 = session2.get_idle_time()

            # Session1 should be much more idle
            assert idle1 > 90  # Should be ~100s
            assert idle2 < 1   # Should be very recent

        finally:
            sock1.close()
            sock2.close()


class TestCleanupWorkflows:
    """Test session cleanup workflows."""

    def test_cleanup_candidate_identification(self):
        """
        Identify which sessions should be cleaned up based on idle time.

        Validates: Sessions >5min idle are cleanup candidates.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock3 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Create three sessions
            session1 = CallSession(call_id="active", socket=sock1,
                                  remote_addr=("192.168.1.10", 5060))
            session2 = CallSession(call_id="idle", socket=sock2,
                                  remote_addr=("192.168.1.20", 5060))
            session3 = CallSession(call_id="very_idle", socket=sock3,
                                  remote_addr=("192.168.1.30", 5060))

            # Set different activity times
            session1.last_activity = time.time()  # Active now
            session2.last_activity = time.time() - 200  # 3.3 min ago
            session3.last_activity = time.time() - 400  # 6.6 min ago

            # Simulate cleanup logic
            idle_timeout = 300  # 5 minutes
            sessions = [session1, session2, session3]
            cleanup_candidates = [s for s in sessions if s.get_idle_time() > idle_timeout]

            # Only session3 should be cleanup candidate
            assert len(cleanup_candidates) == 1
            assert cleanup_candidates[0].call_id == "very_idle"

        finally:
            sock1.close()
            sock2.close()
            sock3.close()

    def test_statistics_aggregation(self):
        """
        Aggregate statistics from multiple sessions.

        Validates: Stats can be collected across all sessions.
        """
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            session1 = CallSession(call_id="test1", socket=sock1,
                                  remote_addr=("192.168.1.10", 5060))
            session1.packets_received = 100
            session1.packets_sent = 80
            session1.echo_packets_filtered = 5

            session2 = CallSession(call_id="test2", socket=sock2,
                                  remote_addr=("192.168.1.20", 5060))
            session2.packets_received = 200
            session2.packets_sent = 150
            session2.echo_packets_filtered = 10

            # Aggregate stats
            sessions = [session1, session2]
            total_rx = sum(s.packets_received for s in sessions)
            total_tx = sum(s.packets_sent for s in sessions)
            total_echo = sum(s.echo_packets_filtered for s in sessions)

            assert total_rx == 300
            assert total_tx == 230
            assert total_echo == 15

        finally:
            sock1.close()
            sock2.close()


class TestCallSessionRepr:
    """Test CallSession string representation."""

    def test_repr_readability(self):
        """
        __repr__() should provide useful debugging information.

        Validates: Repr includes call_id, SSRCs, packet counts.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            session = CallSession(
                call_id="192.168.1.10:5060:305419896",
                socket=sock,
                remote_addr=("192.168.1.10", 5060)
            )
            session.inbound_ssrc = 0x12345678
            session.generate_outbound_ssrc()
            session.packets_received = 150
            session.packets_sent = 100

            repr_str = repr(session)

            # Should contain key identifiers
            assert "CallSession" in repr_str
            assert "192.168.1.10:5060:305419896" in repr_str
            assert "0x12345678" in repr_str
            assert "pkts_rx=150" in repr_str
            assert "pkts_tx=100" in repr_str

        finally:
            sock.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
