"""
Simplified OpenTelemetry setup for Voice Pipeline.

Provides a one-call setup for TracerProvider and MeterProvider
with sensible defaults for voice pipeline observability.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        SimpleSpanProcessor,
    )

    OTEL_SDK_AVAILABLE = True
except ImportError:
    OTEL_SDK_AVAILABLE = False


def setup_telemetry(
    service_name: str = "voice-pipeline",
    service_version: str = "0.1.0",
    otlp_endpoint: Optional[str] = None,
    console: bool = False,
    use_batch_processor: bool = True,
    metric_export_interval_ms: int = 30000,
    resource_attributes: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Configure OpenTelemetry TracerProvider and MeterProvider.

    Args:
        service_name: Service name for the OTel Resource.
        service_version: Service version for the OTel Resource.
        otlp_endpoint: OTLP gRPC endpoint (e.g. "http://localhost:4317").
            If None, no OTLP exporter is configured.
        console: If True, add console exporters for traces and metrics.
        use_batch_processor: Use BatchSpanProcessor (True) or
            SimpleSpanProcessor (False) for spans.
        metric_export_interval_ms: Metric export interval in milliseconds.
        resource_attributes: Additional Resource attributes.

    Returns:
        Dict with keys: tracer_provider, meter_provider, resource.

    Raises:
        ImportError: If opentelemetry-sdk is not installed.

    Example:
        from voice_pipeline.telemetry import setup_telemetry

        providers = setup_telemetry(
            service_name="my-voice-app",
            otlp_endpoint="http://localhost:4317",
        )
        tracer_provider = providers["tracer_provider"]
    """
    if not OTEL_SDK_AVAILABLE:
        raise ImportError(
            "OpenTelemetry SDK is not installed. "
            "Install with: pip install voice-pipeline[observability]"
        )

    # Build resource
    attrs = {
        "service.name": service_name,
        "service.version": service_version,
    }
    if resource_attributes:
        attrs.update(resource_attributes)

    resource = Resource.create(attrs)

    # ==================== TracerProvider ====================
    tracer_provider = TracerProvider(resource=resource)

    # OTLP exporter
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            if use_batch_processor:
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(otlp_span_exporter)
                )
            else:
                tracer_provider.add_span_processor(
                    SimpleSpanProcessor(otlp_span_exporter)
                )
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp not installed. "
                "Skipping OTLP trace exporter. "
                "Install with: pip install voice-pipeline[observability]"
            )

    # Console exporter
    if console:
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            if use_batch_processor:
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(ConsoleSpanExporter())
                )
            else:
                tracer_provider.add_span_processor(
                    SimpleSpanProcessor(ConsoleSpanExporter())
                )
        except ImportError:
            logger.warning("Console span exporter not available.")

    trace.set_tracer_provider(tracer_provider)

    # ==================== MeterProvider ====================
    metric_readers = []

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )

            otlp_metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
            metric_readers.append(
                PeriodicExportingMetricReader(
                    otlp_metric_exporter,
                    export_interval_millis=metric_export_interval_ms,
                )
            )
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp not installed. "
                "Skipping OTLP metric exporter."
            )

    if console:
        try:
            from opentelemetry.sdk.metrics.export import (
                ConsoleMetricExporter,
                PeriodicExportingMetricReader,
            )

            metric_readers.append(
                PeriodicExportingMetricReader(
                    ConsoleMetricExporter(),
                    export_interval_millis=metric_export_interval_ms,
                )
            )
        except ImportError:
            logger.warning("Console metric exporter not available.")

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=metric_readers,
    )
    otel_metrics.set_meter_provider(meter_provider)

    return {
        "tracer_provider": tracer_provider,
        "meter_provider": meter_provider,
        "resource": resource,
    }
