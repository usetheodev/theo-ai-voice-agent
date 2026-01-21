"""
Rate Limiter for SIP Server

Implements Token Bucket algorithm for rate limiting SIP requests per IP address.
Provides protection against:
- SIP INVITE floods
- Brute force authentication attacks
- Resource exhaustion attacks

Author: AI Voice Agent Team
Date: 2026-01-21
"""

import time
from typing import Dict, Optional, Tuple
from collections import deque
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limiter configuration"""
    requests_per_minute: int = 60  # Max requests per minute per IP
    burst_size: int = 10  # Allow burst of N requests
    ban_threshold: int = 5  # Ban after N violations in window
    ban_duration_seconds: int = 300  # Ban for 5 minutes
    violation_window_seconds: int = 60  # Track violations in 60s window
    cleanup_interval_seconds: int = 300  # Cleanup old entries every 5min


class TokenBucket:
    """
    Token Bucket implementation for rate limiting

    Algorithm:
    - Bucket starts with 'capacity' tokens
    - Tokens are consumed on each request
    - Tokens regenerate at 'refill_rate' per second
    - If no tokens available, request is rejected
    """

    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket

        Args:
            capacity: Maximum tokens (burst size)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        self._refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True

        return False

    def _refill(self):
        """Refill tokens based on time elapsed"""
        now = time.time()
        elapsed = now - self.last_refill

        # Add tokens based on elapsed time
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now

    def get_tokens(self) -> float:
        """Get current number of tokens"""
        self._refill()
        return self.tokens


class RateLimiter:
    """
    SIP Rate Limiter with Token Bucket algorithm

    Features:
    - Per-IP rate limiting
    - Automatic IP banning for repeated violations
    - Whitelist/blacklist support
    - Automatic cleanup of old entries
    """

    def __init__(self, config: RateLimitConfig):
        """
        Initialize rate limiter

        Args:
            config: Rate limit configuration
        """
        self.config = config

        # Token buckets per IP
        self.buckets: Dict[str, TokenBucket] = {}

        # Violation tracking: {ip: deque([timestamps])}
        self.violations: Dict[str, deque] = {}

        # Banned IPs: {ip: unban_timestamp}
        self.banned_ips: Dict[str, float] = {}

        # Whitelisted IPs (never rate limited)
        self.whitelist: set = set()

        # Permanently blacklisted IPs
        self.blacklist: set = set()

        # Calculate refill rate (tokens per second)
        self.refill_rate = self.config.requests_per_minute / 60.0

        logger.info("🛡️ Rate Limiter initialized",
                   requests_per_minute=config.requests_per_minute,
                   burst_size=config.burst_size,
                   ban_threshold=config.ban_threshold,
                   ban_duration=f"{config.ban_duration_seconds}s")

    def is_allowed(self, ip: str, method: str = "INVITE") -> Tuple[bool, Optional[str]]:
        """
        Check if request from IP is allowed

        Args:
            ip: Client IP address
            method: SIP method (for logging)

        Returns:
            (allowed: bool, reason: Optional[str])
        """
        # Check blacklist first
        if ip in self.blacklist:
            logger.warn("🚫 Blacklisted IP blocked",
                       ip=ip,
                       method=method)
            return False, "IP permanently blacklisted"

        # Check whitelist (always allowed)
        if ip in self.whitelist:
            return True, None

        # Check if IP is banned
        if ip in self.banned_ips:
            unban_time = self.banned_ips[ip]
            now = time.time()

            if now < unban_time:
                remaining = int(unban_time - now)
                logger.warn("🚫 Banned IP blocked",
                           ip=ip,
                           method=method,
                           remaining_seconds=remaining)
                return False, f"IP banned for {remaining}s"
            else:
                # Ban expired, remove from banned list
                del self.banned_ips[ip]
                logger.info("✅ IP unbanned",
                           ip=ip,
                           reason="ban_expired")

        # Get or create token bucket for this IP
        if ip not in self.buckets:
            self.buckets[ip] = TokenBucket(
                capacity=self.config.burst_size,
                refill_rate=self.refill_rate
            )

        bucket = self.buckets[ip]

        # Try to consume token
        if bucket.consume():
            # Request allowed
            return True, None
        else:
            # Rate limit exceeded - record violation
            self._record_violation(ip, method)

            tokens = bucket.get_tokens()
            logger.warn("⚠️ Rate limit exceeded",
                       ip=ip,
                       method=method,
                       tokens_available=f"{tokens:.2f}",
                       refill_rate=self.refill_rate)

            return False, "Rate limit exceeded"

    def _record_violation(self, ip: str, method: str):
        """
        Record rate limit violation and ban if threshold exceeded

        Args:
            ip: Client IP address
            method: SIP method
        """
        now = time.time()

        # Initialize violations deque for this IP
        if ip not in self.violations:
            self.violations[ip] = deque()

        violations = self.violations[ip]

        # Add current violation
        violations.append(now)

        # Remove old violations outside window
        window_start = now - self.config.violation_window_seconds
        while violations and violations[0] < window_start:
            violations.popleft()

        # Check if ban threshold exceeded
        violation_count = len(violations)
        if violation_count >= self.config.ban_threshold:
            self._ban_ip(ip, method, violation_count)

    def _ban_ip(self, ip: str, method: str, violation_count: int):
        """
        Ban IP for repeated violations

        Args:
            ip: IP to ban
            method: SIP method that triggered ban
            violation_count: Number of violations
        """
        unban_time = time.time() + self.config.ban_duration_seconds
        self.banned_ips[ip] = unban_time

        # Clear violations for this IP
        if ip in self.violations:
            del self.violations[ip]

        logger.error("🔒 IP BANNED",
                    ip=ip,
                    method=method,
                    violations=violation_count,
                    ban_duration=f"{self.config.ban_duration_seconds}s",
                    unban_at=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(unban_time)))

    def add_to_whitelist(self, ip: str):
        """Add IP to whitelist (never rate limited)"""
        self.whitelist.add(ip)
        logger.info("✅ IP added to whitelist", ip=ip)

    def remove_from_whitelist(self, ip: str):
        """Remove IP from whitelist"""
        self.whitelist.discard(ip)
        logger.info("➖ IP removed from whitelist", ip=ip)

    def add_to_blacklist(self, ip: str):
        """Add IP to permanent blacklist"""
        self.blacklist.add(ip)
        logger.info("🚫 IP added to blacklist", ip=ip)

    def remove_from_blacklist(self, ip: str):
        """Remove IP from blacklist"""
        self.blacklist.discard(ip)
        logger.info("➖ IP removed from blacklist", ip=ip)

    def unban_ip(self, ip: str):
        """Manually unban an IP"""
        if ip in self.banned_ips:
            del self.banned_ips[ip]
            logger.info("✅ IP manually unbanned", ip=ip)

    def cleanup(self):
        """
        Clean up old entries to prevent memory leaks

        Removes:
        - Token buckets for IPs not seen recently
        - Expired bans
        - Old violations
        """
        now = time.time()
        cleaned_buckets = 0
        cleaned_violations = 0
        cleaned_bans = 0

        # Clean up old token buckets (not used in 10 minutes)
        buckets_to_remove = []
        for ip, bucket in self.buckets.items():
            if (now - bucket.last_refill) > 600:  # 10 minutes
                buckets_to_remove.append(ip)

        for ip in buckets_to_remove:
            del self.buckets[ip]
            cleaned_buckets += 1

        # Clean up expired bans
        bans_to_remove = []
        for ip, unban_time in self.banned_ips.items():
            if now >= unban_time:
                bans_to_remove.append(ip)

        for ip in bans_to_remove:
            del self.banned_ips[ip]
            cleaned_bans += 1

        # Clean up old violations
        violations_to_remove = []
        for ip, violations in self.violations.items():
            window_start = now - self.config.violation_window_seconds
            while violations and violations[0] < window_start:
                violations.popleft()

            if not violations:
                violations_to_remove.append(ip)

        for ip in violations_to_remove:
            del self.violations[ip]
            cleaned_violations += 1

        if cleaned_buckets or cleaned_violations or cleaned_bans:
            logger.info("🧹 Rate limiter cleanup completed",
                       cleaned_buckets=cleaned_buckets,
                       cleaned_violations=cleaned_violations,
                       cleaned_bans=cleaned_bans,
                       active_buckets=len(self.buckets),
                       active_bans=len(self.banned_ips))

    def get_stats(self) -> dict:
        """Get current rate limiter statistics"""
        return {
            "active_buckets": len(self.buckets),
            "banned_ips": len(self.banned_ips),
            "whitelisted_ips": len(self.whitelist),
            "blacklisted_ips": len(self.blacklist),
            "active_violations": len(self.violations)
        }
