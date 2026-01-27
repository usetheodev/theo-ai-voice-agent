"""GPU monitoring utilities.

Provides GPU metrics collection for providers that use GPU acceleration.
Works with PyTorch CUDA when available, gracefully degrades without it.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class GPUMetrics:
    """GPU resource usage metrics.

    Attributes:
        gpu_memory_used_mb: GPU memory currently used in MB.
        gpu_memory_total_mb: Total GPU memory available in MB.
        gpu_utilization_pct: GPU utilization percentage (0-100).
        gpu_temperature_c: GPU temperature in Celsius.
        device_name: Name of the GPU device.
    """

    gpu_memory_used_mb: Optional[float] = None
    """GPU memory currently used in MB."""

    gpu_memory_total_mb: Optional[float] = None
    """Total GPU memory available in MB."""

    gpu_utilization_pct: Optional[float] = None
    """GPU utilization percentage (0-100)."""

    gpu_temperature_c: Optional[float] = None
    """GPU temperature in Celsius."""

    device_name: Optional[str] = None
    """Name of the GPU device."""

    @property
    def gpu_memory_pct(self) -> Optional[float]:
        """GPU memory usage percentage."""
        if self.gpu_memory_used_mb is not None and self.gpu_memory_total_mb:
            return (self.gpu_memory_used_mb / self.gpu_memory_total_mb) * 100.0
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {}
        if self.gpu_memory_used_mb is not None:
            result["gpu_memory_used_mb"] = self.gpu_memory_used_mb
        if self.gpu_memory_total_mb is not None:
            result["gpu_memory_total_mb"] = self.gpu_memory_total_mb
        if self.gpu_memory_pct is not None:
            result["gpu_memory_pct"] = round(self.gpu_memory_pct, 1)
        if self.gpu_utilization_pct is not None:
            result["gpu_utilization_pct"] = self.gpu_utilization_pct
        if self.gpu_temperature_c is not None:
            result["gpu_temperature_c"] = self.gpu_temperature_c
        if self.device_name is not None:
            result["device_name"] = self.device_name
        return result


def collect_gpu_metrics(device: Optional[str] = None) -> Optional[GPUMetrics]:
    """Collect current GPU metrics using PyTorch CUDA.

    Args:
        device: CUDA device string (e.g., "cuda:0"). If None, uses default.

    Returns:
        GPUMetrics if CUDA is available, None otherwise.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return None

        # Parse device index
        device_idx = 0
        if device and ":" in device:
            try:
                device_idx = int(device.split(":")[1])
            except (ValueError, IndexError):
                device_idx = 0

        # Collect memory metrics
        mem_allocated = torch.cuda.memory_allocated(device_idx) / (1024 * 1024)
        mem_total = torch.cuda.get_device_properties(device_idx).total_mem / (1024 * 1024)

        # Device name
        device_name = torch.cuda.get_device_name(device_idx)

        return GPUMetrics(
            gpu_memory_used_mb=round(mem_allocated, 1),
            gpu_memory_total_mb=round(mem_total, 1),
            device_name=device_name,
        )

    except (ImportError, RuntimeError, Exception):
        return None
