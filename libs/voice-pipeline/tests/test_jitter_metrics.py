"""Tests for jitter measurement in StreamingMetrics.

Validates that inter-chunk jitter is correctly computed for both ASR and TTS
chunk streams, including edge cases (empty data, single timestamp) and
integration with to_dict() / __str__() output.
"""

import time

import pytest

from voice_pipeline.streaming.metrics import StreamingMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inject_timestamps(metrics: StreamingMetrics, field: str, timestamps: list[float]) -> None:
    """Directly inject timestamps into the private list to avoid real sleeps."""
    getattr(metrics, field).extend(timestamps)


# ---------------------------------------------------------------------------
# 1. Uniform intervals -> jitter stddev ~0
# ---------------------------------------------------------------------------

class TestUniformIntervals:
    """When chunks arrive at perfectly uniform intervals the jitter stddev
    must be (approximately) zero."""

    def test_uniform_asr_jitter_stddev_is_zero(self):
        metrics = StreamingMetrics()
        # 10 chunks exactly 0.020s apart
        base = 1000.0
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [base + i * 0.020 for i in range(10)],
        )

        stats = metrics.jitter()
        assert "asr_chunks" in stats
        asr = stats["asr_chunks"]
        assert asr["count"] == 9  # 10 timestamps -> 9 intervals
        assert asr["jitter_stddev"] == pytest.approx(0.0, abs=1e-12)
        assert asr["mean_interval"] == pytest.approx(0.020, abs=1e-12)

    def test_uniform_tts_jitter_stddev_is_zero(self):
        metrics = StreamingMetrics()
        base = 5000.0
        _inject_timestamps(
            metrics, "_tts_chunk_timestamps",
            [base + i * 0.050 for i in range(6)],
        )

        stats = metrics.jitter()
        assert "tts_chunks" in stats
        tts = stats["tts_chunks"]
        assert tts["count"] == 5
        assert tts["jitter_stddev"] == pytest.approx(0.0, abs=1e-12)
        assert tts["mean_interval"] == pytest.approx(0.050, abs=1e-12)

    def test_percentiles_equal_interval_when_uniform(self):
        metrics = StreamingMetrics()
        base = 0.0
        interval = 0.030
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [base + i * interval for i in range(20)],
        )

        asr = metrics.jitter()["asr_chunks"]
        # All intervals identical -> every percentile equals the interval
        assert asr["p50"] == pytest.approx(interval, abs=1e-12)
        assert asr["p95"] == pytest.approx(interval, abs=1e-12)
        assert asr["p99"] == pytest.approx(interval, abs=1e-12)


# ---------------------------------------------------------------------------
# 2. Variable intervals -> jitter stddev > 0
# ---------------------------------------------------------------------------

class TestVariableIntervals:
    """When chunks arrive at non-uniform intervals the jitter stddev must be
    positive."""

    def test_variable_asr_jitter_stddev_positive(self):
        metrics = StreamingMetrics()
        # Deliberately irregular timestamps
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [0.0, 0.010, 0.035, 0.040, 0.100, 0.105],
        )

        asr = metrics.jitter()["asr_chunks"]
        assert asr["count"] == 5
        assert asr["jitter_stddev"] > 0.0

    def test_variable_tts_jitter_stddev_positive(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_tts_chunk_timestamps",
            [0.0, 0.001, 0.050, 0.051, 0.200],
        )

        tts = metrics.jitter()["tts_chunks"]
        assert tts["count"] == 4
        assert tts["jitter_stddev"] > 0.0

    def test_mean_interval_is_correct(self):
        metrics = StreamingMetrics()
        timestamps = [0.0, 0.010, 0.030, 0.060]
        _inject_timestamps(metrics, "_asr_chunk_timestamps", timestamps)

        intervals = [0.010, 0.020, 0.030]
        expected_mean = sum(intervals) / len(intervals)

        asr = metrics.jitter()["asr_chunks"]
        assert asr["mean_interval"] == pytest.approx(expected_mean, abs=1e-12)

    def test_stddev_is_correct(self):
        metrics = StreamingMetrics()
        timestamps = [0.0, 0.010, 0.030, 0.060]
        _inject_timestamps(metrics, "_asr_chunk_timestamps", timestamps)

        intervals = [0.010, 0.020, 0.030]
        mean = sum(intervals) / len(intervals)
        variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
        expected_stddev = variance ** 0.5

        asr = metrics.jitter()["asr_chunks"]
        assert asr["jitter_stddev"] == pytest.approx(expected_stddev, abs=1e-12)

    def test_p95_greater_than_p50_with_variable_data(self):
        metrics = StreamingMetrics()
        # Many small intervals followed by a few large ones
        ts = [0.0]
        t = 0.0
        for i in range(50):
            t += 0.010  # 10ms intervals
            ts.append(t)
        for i in range(5):
            t += 0.200  # 200ms intervals (outliers)
            ts.append(t)

        _inject_timestamps(metrics, "_tts_chunk_timestamps", ts)

        tts = metrics.jitter()["tts_chunks"]
        assert tts["p95"] > tts["p50"]
        assert tts["p99"] >= tts["p95"]


# ---------------------------------------------------------------------------
# 3. ASR and TTS jitter tracked separately
# ---------------------------------------------------------------------------

class TestSeparateTracking:
    """ASR and TTS jitter stats must be independent."""

    def test_asr_only_no_tts(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [0.0, 0.010, 0.020],
        )

        stats = metrics.jitter()
        assert "asr_chunks" in stats
        assert "tts_chunks" not in stats

    def test_tts_only_no_asr(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_tts_chunk_timestamps",
            [0.0, 0.050, 0.100],
        )

        stats = metrics.jitter()
        assert "tts_chunks" in stats
        assert "asr_chunks" not in stats

    def test_both_present_independently(self):
        metrics = StreamingMetrics()
        # ASR: uniform 10ms
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [0.0, 0.010, 0.020, 0.030],
        )
        # TTS: variable
        _inject_timestamps(
            metrics, "_tts_chunk_timestamps",
            [0.0, 0.005, 0.050, 0.055],
        )

        stats = metrics.jitter()
        assert "asr_chunks" in stats
        assert "tts_chunks" in stats

        # ASR should have ~0 jitter (uniform)
        assert stats["asr_chunks"]["jitter_stddev"] == pytest.approx(0.0, abs=1e-12)
        # TTS should have >0 jitter (variable)
        assert stats["tts_chunks"]["jitter_stddev"] > 0.0

    def test_record_methods_append_to_correct_lists(self):
        """Verify record_asr_chunk / record_tts_chunk actually append
        timestamps to the correct internal lists."""
        metrics = StreamingMetrics()

        metrics.record_asr_chunk()
        assert len(metrics._asr_chunk_timestamps) == 1
        assert len(metrics._tts_chunk_timestamps) == 0

        metrics.record_tts_chunk()
        assert len(metrics._asr_chunk_timestamps) == 1
        assert len(metrics._tts_chunk_timestamps) == 1

        metrics.record_asr_chunk()
        metrics.record_asr_chunk()
        assert len(metrics._asr_chunk_timestamps) == 3
        assert len(metrics._tts_chunk_timestamps) == 1


# ---------------------------------------------------------------------------
# 4. Jitter included in to_dict() output
# ---------------------------------------------------------------------------

class TestToDictIntegration:
    """Jitter stats must appear under the 'jitter' key in to_dict()."""

    def test_jitter_in_to_dict_when_data_present(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [0.0, 0.010, 0.020, 0.030],
        )
        _inject_timestamps(
            metrics, "_tts_chunk_timestamps",
            [0.0, 0.020, 0.040],
        )

        d = metrics.to_dict()
        assert "jitter" in d
        assert "asr_chunks" in d["jitter"]
        assert "tts_chunks" in d["jitter"]

        # Validate sub-dict keys
        expected_keys = {"count", "mean_interval", "jitter_stddev", "p50", "p95", "p99"}
        assert set(d["jitter"]["asr_chunks"].keys()) == expected_keys
        assert set(d["jitter"]["tts_chunks"].keys()) == expected_keys

    def test_no_jitter_key_when_no_data(self):
        metrics = StreamingMetrics()
        d = metrics.to_dict()
        assert "jitter" not in d

    def test_jitter_values_match_direct_call(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [0.0, 0.015, 0.025, 0.060],
        )

        direct = metrics.jitter()
        from_dict = metrics.to_dict()["jitter"]

        assert direct["asr_chunks"]["mean_interval"] == from_dict["asr_chunks"]["mean_interval"]
        assert direct["asr_chunks"]["jitter_stddev"] == from_dict["asr_chunks"]["jitter_stddev"]
        assert direct["asr_chunks"]["p50"] == from_dict["asr_chunks"]["p50"]
        assert direct["asr_chunks"]["p95"] == from_dict["asr_chunks"]["p95"]
        assert direct["asr_chunks"]["p99"] == from_dict["asr_chunks"]["p99"]


# ---------------------------------------------------------------------------
# 5. Jitter included in __str__() output
# ---------------------------------------------------------------------------

class TestStrIntegration:
    """The __str__ representation must include jitter information."""

    def test_jitter_in_str_when_data_present(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_asr_chunk_timestamps",
            [0.0, 0.020, 0.040],
        )

        s = str(metrics)
        assert "jitter_asr_chunks" in s
        assert "mean=" in s
        assert "stddev=" in s

    def test_tts_jitter_in_str(self):
        metrics = StreamingMetrics()
        _inject_timestamps(
            metrics, "_tts_chunk_timestamps",
            [0.0, 0.010, 0.030],
        )

        s = str(metrics)
        assert "jitter_tts_chunks" in s

    def test_no_jitter_in_str_when_no_data(self):
        metrics = StreamingMetrics()
        s = str(metrics)
        assert "jitter" not in s

    def test_both_jitter_sources_in_str(self):
        metrics = StreamingMetrics()
        _inject_timestamps(metrics, "_asr_chunk_timestamps", [0.0, 0.010, 0.020])
        _inject_timestamps(metrics, "_tts_chunk_timestamps", [0.0, 0.050, 0.100])

        s = str(metrics)
        assert "jitter_asr_chunks" in s
        assert "jitter_tts_chunks" in s


# ---------------------------------------------------------------------------
# 6. Empty timestamps -> empty jitter dict
# ---------------------------------------------------------------------------

class TestEmptyTimestamps:
    """With no recorded timestamps, jitter() must return an empty dict."""

    def test_fresh_metrics_jitter_empty(self):
        metrics = StreamingMetrics()
        assert metrics.jitter() == {}

    def test_empty_asr_and_tts_lists(self):
        metrics = StreamingMetrics()
        assert metrics._asr_chunk_timestamps == []
        assert metrics._tts_chunk_timestamps == []
        assert metrics.jitter() == {}

    def test_compute_jitter_stats_empty_list(self):
        result = StreamingMetrics._compute_jitter_stats([])
        assert result == {}


# ---------------------------------------------------------------------------
# 7. Single timestamp -> empty jitter dict (need at least 2)
# ---------------------------------------------------------------------------

class TestSingleTimestamp:
    """A single timestamp means zero intervals, so jitter must be empty."""

    def test_single_asr_timestamp_returns_empty(self):
        metrics = StreamingMetrics()
        _inject_timestamps(metrics, "_asr_chunk_timestamps", [42.0])

        stats = metrics.jitter()
        assert "asr_chunks" not in stats

    def test_single_tts_timestamp_returns_empty(self):
        metrics = StreamingMetrics()
        _inject_timestamps(metrics, "_tts_chunk_timestamps", [99.0])

        stats = metrics.jitter()
        assert "tts_chunks" not in stats

    def test_single_via_record_method(self):
        metrics = StreamingMetrics()
        metrics.record_asr_chunk()

        assert len(metrics._asr_chunk_timestamps) == 1
        assert metrics.jitter() == {}

    def test_compute_jitter_stats_single_value(self):
        result = StreamingMetrics._compute_jitter_stats([123.456])
        assert result == {}

    def test_two_timestamps_is_minimum(self):
        """Exactly 2 timestamps produce exactly 1 interval -- stats should
        be returned (count=1, stddev=0)."""
        metrics = StreamingMetrics()
        _inject_timestamps(metrics, "_asr_chunk_timestamps", [0.0, 0.025])

        stats = metrics.jitter()
        assert "asr_chunks" in stats
        asr = stats["asr_chunks"]
        assert asr["count"] == 1
        assert asr["mean_interval"] == pytest.approx(0.025, abs=1e-12)
        assert asr["jitter_stddev"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Bonus: record methods use real time
# ---------------------------------------------------------------------------

class TestRecordMethodsRealTime:
    """Verify that record_asr_chunk / record_tts_chunk produce timestamps
    based on time.perf_counter that increase monotonically."""

    def test_timestamps_are_monotonically_increasing(self):
        metrics = StreamingMetrics()
        for _ in range(5):
            metrics.record_asr_chunk()
            time.sleep(0.001)  # 1ms gap to guarantee ordering

        ts = metrics._asr_chunk_timestamps
        assert len(ts) == 5
        for i in range(len(ts) - 1):
            assert ts[i + 1] > ts[i], "Timestamps must be strictly increasing"

    def test_real_jitter_with_small_sleep(self):
        """Record a handful of chunks with real sleeps and verify we get
        plausible stats."""
        metrics = StreamingMetrics()
        for _ in range(4):
            metrics.record_tts_chunk()
            time.sleep(0.005)

        stats = metrics.jitter()
        assert "tts_chunks" in stats
        tts = stats["tts_chunks"]
        assert tts["count"] == 3
        # Mean interval should be roughly 5ms (allow generous tolerance)
        assert 0.003 <= tts["mean_interval"] <= 0.020
