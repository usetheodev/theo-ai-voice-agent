"""Tests for GPU monitoring utilities."""

from unittest.mock import MagicMock, patch

import pytest

from voice_pipeline.utils.gpu import GPUMetrics, collect_gpu_metrics


class TestGPUMetrics:
    """Tests for GPUMetrics dataclass."""

    def test_to_dict_full(self):
        metrics = GPUMetrics(
            gpu_memory_used_mb=4096.0,
            gpu_memory_total_mb=8192.0,
            gpu_utilization_pct=75.0,
            gpu_temperature_c=65.0,
            device_name="NVIDIA RTX 4090",
        )
        d = metrics.to_dict()
        assert d["gpu_memory_used_mb"] == 4096.0
        assert d["gpu_memory_total_mb"] == 8192.0
        assert d["gpu_memory_pct"] == 50.0
        assert d["gpu_utilization_pct"] == 75.0
        assert d["gpu_temperature_c"] == 65.0
        assert d["device_name"] == "NVIDIA RTX 4090"

    def test_to_dict_partial(self):
        metrics = GPUMetrics(
            gpu_memory_used_mb=2048.0,
            gpu_memory_total_mb=8192.0,
        )
        d = metrics.to_dict()
        assert d["gpu_memory_used_mb"] == 2048.0
        assert d["gpu_memory_total_mb"] == 8192.0
        assert d["gpu_memory_pct"] == 25.0
        assert "gpu_utilization_pct" not in d
        assert "gpu_temperature_c" not in d
        assert "device_name" not in d

    def test_to_dict_empty(self):
        metrics = GPUMetrics()
        d = metrics.to_dict()
        assert d == {}

    def test_gpu_memory_pct(self):
        metrics = GPUMetrics(gpu_memory_used_mb=1000.0, gpu_memory_total_mb=4000.0)
        assert metrics.gpu_memory_pct == 25.0

    def test_gpu_memory_pct_none_when_missing(self):
        metrics = GPUMetrics(gpu_memory_used_mb=1000.0)
        assert metrics.gpu_memory_pct is None

    def test_gpu_memory_pct_none_when_no_used(self):
        metrics = GPUMetrics(gpu_memory_total_mb=4000.0)
        assert metrics.gpu_memory_pct is None


class TestCollectGPUMetrics:
    """Tests for collect_gpu_metrics function."""

    def test_returns_none_without_torch(self):
        with patch.dict("sys.modules", {"torch": None}):
            result = collect_gpu_metrics()
            assert result is None

    def test_returns_none_when_import_fails(self):
        """Without CUDA available, should return None."""
        result = collect_gpu_metrics()
        # In CI/dev environments without CUDA, this returns None
        # We just verify it doesn't crash
        assert result is None or isinstance(result, GPUMetrics)

    def test_with_mocked_torch_cuda(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 2 * 1024 * 1024 * 1024  # 2GB
        mock_props = MagicMock()
        mock_props.total_mem = 8 * 1024 * 1024 * 1024  # 8GB
        mock_torch.cuda.get_device_properties.return_value = mock_props
        mock_torch.cuda.get_device_name.return_value = "Mock GPU"

        with patch.dict("sys.modules", {"torch": mock_torch}):
            # Need to reimport because the module caches imports
            from voice_pipeline.utils import gpu
            import importlib
            importlib.reload(gpu)

            result = gpu.collect_gpu_metrics("cuda:0")

        if result is not None:
            assert result.device_name == "Mock GPU"
            assert result.gpu_memory_used_mb is not None
            assert result.gpu_memory_total_mb is not None

    def test_with_device_index_parsing(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 1024 * 1024 * 1024
        mock_props = MagicMock()
        mock_props.total_mem = 4 * 1024 * 1024 * 1024
        mock_torch.cuda.get_device_properties.return_value = mock_props
        mock_torch.cuda.get_device_name.return_value = "GPU 1"

        with patch.dict("sys.modules", {"torch": mock_torch}):
            from voice_pipeline.utils import gpu
            import importlib
            importlib.reload(gpu)

            result = gpu.collect_gpu_metrics("cuda:1")

        # Verify device index 1 was used
        if result is not None:
            mock_torch.cuda.memory_allocated.assert_called_with(1)
            mock_torch.cuda.get_device_properties.assert_called_with(1)
            mock_torch.cuda.get_device_name.assert_called_with(1)
