"""
OpenTelemetry tracing setup for Helix.

Call setup_tracing() once at each agent's process startup. When OTEL_ENABLED is
not true, this is a no-op and all subsequent tracing calls resolve to the OTel
API's built-in no-op tracer — zero overhead, no errors.

When enabled, traces are exported via OTLP/gRPC to the endpoint set in
OTEL_EXPORTER_OTLP_ENDPOINT (default: http://localhost:4317). This is
compatible with Datadog, Grafana Tempo, Jaeger, Honeycomb, and any other
OpenTelemetry-compatible backend.

Usage:
    # Once at process startup (before any handle() calls):
    from core.telemetry import setup_tracing, get_tracer
    setup_tracing()

    # Per module that wants to create spans:
    _tracer = get_tracer("helix.qa")

    with _tracer.start_as_current_span("qa.handle_incident") as span:
        span.set_attribute("helix.incident_id", incident_id)
        await handle(...)
"""

import logging

from core.config import get_otel_config

logger = logging.getLogger(__name__)

# OTel API is a required dep. Import at module level so get_tracer() works
# without try/except at every call site.
try:
    from opentelemetry import trace as _trace
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


def setup_tracing() -> None:
    """
    Configure the OTel TracerProvider if OTEL_ENABLED=true.

    Imports the SDK and OTLP exporter lazily — only when actually needed —
    so that startup is fast and there is no overhead when tracing is disabled.

    Safe to call multiple times; subsequent calls after the provider is already
    set are effectively no-ops (the provider is only set once per process).
    """
    cfg = get_otel_config()
    if not cfg.enabled:
        logger.debug("OTel tracing disabled — set OTEL_ENABLED=true to enable")
        return

    if not _OTEL_AVAILABLE:
        logger.warning(
            "OTEL_ENABLED=true but opentelemetry-api is not installed — "
            "run `uv sync` to install OTel packages. Tracing disabled."
        )
        return

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        resource = Resource.create({"service.name": cfg.service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=cfg.endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _trace.set_tracer_provider(provider)

        logger.info(
            "OTel tracing enabled",
            extra={"service": cfg.service_name, "endpoint": cfg.endpoint},
        )
    except Exception as exc:
        logger.warning(
            "OTel setup failed — tracing disabled: %s", exc,
            extra={"error": str(exc)},
        )


def get_tracer(name: str):
    """
    Return an OTel tracer for the given instrumentation scope name.

    When tracing is disabled (no provider set), returns the OTel API's built-in
    no-op tracer — start_as_current_span() calls become no-ops with no overhead.

    When tracing is enabled (setup_tracing() was called and OTEL_ENABLED=true),
    returns a real tracer that creates and exports spans.

    Args:
        name: Instrumentation scope, e.g. "helix.llm", "helix.qa".

    Returns:
        An OTel Tracer (real or no-op depending on whether setup_tracing()
        configured a provider).
    """
    if _OTEL_AVAILABLE:
        return _trace.get_tracer(name)
    return _NoopTracer()


# ---------------------------------------------------------------------------
# Fallback no-op implementation for the rare case where the OTel API package
# is not installed. Mirrors the OTel API surface used in this codebase.
# ---------------------------------------------------------------------------

class _NoopSpan:
    """No-op span used when opentelemetry-api is not installed."""

    def set_attribute(self, key: str, value) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def set_status(self, status) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoopTracer:
    """No-op tracer used when opentelemetry-api is not installed."""

    def start_as_current_span(self, name: str, **kwargs):
        return _NoopSpan()
