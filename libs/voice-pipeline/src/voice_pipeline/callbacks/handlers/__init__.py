"""
Built-in callback handlers for Voice Pipeline.

Available handlers:
- LoggingHandler: Structured logging for pipeline events
- MetricsHandler: Latency and performance metrics collection
- StdOutHandler: Simple stdout printing for debugging
- OpenTelemetryHandler: Distributed tracing (requires opentelemetry)
"""

from voice_pipeline.callbacks.handlers.logging import LoggingHandler
from voice_pipeline.callbacks.handlers.metrics import (
    ComponentMetrics,
    MetricsHandler,
    PipelineMetrics,
)
from voice_pipeline.callbacks.handlers.stdout import StdOutHandler
from voice_pipeline.callbacks.handlers.tracing import (
    OTEL_AVAILABLE,
    OpenTelemetryHandler,
    create_otel_handler,
)

__all__ = [
    # Logging
    "LoggingHandler",
    # Metrics
    "MetricsHandler",
    "PipelineMetrics",
    "ComponentMetrics",
    # Stdout
    "StdOutHandler",
    # Tracing
    "OpenTelemetryHandler",
    "create_otel_handler",
    "OTEL_AVAILABLE",
]
