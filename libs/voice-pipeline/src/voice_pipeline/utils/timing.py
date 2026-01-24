"""Timing utilities for measuring latency."""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Timer:
    """Simple timer for measuring durations."""

    _start_time: Optional[float] = None
    _end_time: Optional[float] = None
    _checkpoints: dict[str, float] = field(default_factory=dict)

    def start(self) -> "Timer":
        """Start the timer.

        Returns:
            Self for chaining.
        """
        self._start_time = time.time()
        self._end_time = None
        self._checkpoints.clear()
        return self

    def stop(self) -> float:
        """Stop the timer.

        Returns:
            Elapsed time in seconds.
        """
        self._end_time = time.time()
        return self.elapsed

    def checkpoint(self, name: str) -> float:
        """Record a checkpoint.

        Args:
            name: Checkpoint name.

        Returns:
            Time since start in seconds.
        """
        if self._start_time is None:
            raise RuntimeError("Timer not started")
        elapsed = time.time() - self._start_time
        self._checkpoints[name] = elapsed
        return elapsed

    @property
    def elapsed(self) -> float:
        """Elapsed time in seconds."""
        if self._start_time is None:
            return 0.0
        end = self._end_time or time.time()
        return end - self._start_time

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        return self.elapsed * 1000

    def get_checkpoint(self, name: str) -> Optional[float]:
        """Get checkpoint time.

        Args:
            name: Checkpoint name.

        Returns:
            Time since start in seconds, or None if not found.
        """
        return self._checkpoints.get(name)

    def get_checkpoint_ms(self, name: str) -> Optional[float]:
        """Get checkpoint time in milliseconds.

        Args:
            name: Checkpoint name.

        Returns:
            Time since start in milliseconds, or None if not found.
        """
        value = self._checkpoints.get(name)
        return value * 1000 if value is not None else None


@contextmanager
def measure_latency(callback: Optional[Callable[[float], None]] = None):
    """Context manager for measuring latency.

    Args:
        callback: Optional callback with elapsed time in milliseconds.

    Yields:
        Timer instance.

    Example:
        with measure_latency(lambda ms: print(f"Took {ms}ms")):
            do_something()
    """
    timer = Timer().start()
    try:
        yield timer
    finally:
        timer.stop()
        if callback:
            callback(timer.elapsed_ms)
