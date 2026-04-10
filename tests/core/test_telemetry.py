"""Tests for core/telemetry.py"""
from unittest.mock import MagicMock, patch

import pytest

from core.telemetry import get_tracer, setup_tracing, _NoopTracer, _NoopSpan


# ---------------------------------------------------------------------------
# setup_tracing — disabled path
# ---------------------------------------------------------------------------

def test_setup_tracing_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    # Should not raise and should not configure a provider.
    with patch("core.telemetry.get_otel_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(enabled=False)
        setup_tracing()
        # If disabled, we never touch the OTel SDK.
        mock_cfg.assert_called_once()


def test_setup_tracing_enabled_configures_provider(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")

    mock_cfg = MagicMock(enabled=True, service_name="helix-test", endpoint="http://localhost:4317")
    mock_provider = MagicMock()
    mock_exporter = MagicMock()
    mock_processor = MagicMock()
    mock_resource = MagicMock()

    with patch("core.telemetry.get_otel_config", return_value=mock_cfg):
        with patch("core.telemetry._OTEL_AVAILABLE", True):
            with patch("opentelemetry.sdk.resources.Resource") as MockResource:
                MockResource.create.return_value = mock_resource
                with patch("opentelemetry.sdk.trace.TracerProvider", return_value=mock_provider):
                    with patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter", return_value=mock_exporter):
                        with patch("opentelemetry.sdk.trace.export.BatchSpanProcessor", return_value=mock_processor):
                            with patch("opentelemetry.trace.set_tracer_provider") as mock_set:
                                setup_tracing()
                                mock_set.assert_called_once_with(mock_provider)


def test_setup_tracing_otel_not_available_logs_warning(monkeypatch, caplog):
    import logging
    mock_cfg = MagicMock(enabled=True)

    with patch("core.telemetry.get_otel_config", return_value=mock_cfg):
        with patch("core.telemetry._OTEL_AVAILABLE", False):
            with caplog.at_level(logging.WARNING, logger="core.telemetry"):
                setup_tracing()

    assert any("opentelemetry-api is not installed" in r.message for r in caplog.records)


def test_setup_tracing_sdk_import_error_logs_warning(monkeypatch, caplog):
    import logging
    mock_cfg = MagicMock(enabled=True, service_name="helix", endpoint="http://localhost:4317")

    with patch("core.telemetry.get_otel_config", return_value=mock_cfg):
        with patch("core.telemetry._OTEL_AVAILABLE", True):
            with patch("builtins.__import__", side_effect=ImportError("sdk missing")):
                with caplog.at_level(logging.WARNING, logger="core.telemetry"):
                    setup_tracing()

    assert any("OTel setup failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------

def test_get_tracer_returns_real_tracer_when_otel_available():
    mock_tracer = MagicMock()
    with patch("core.telemetry._OTEL_AVAILABLE", True):
        with patch("core.telemetry._trace") as mock_trace:
            mock_trace.get_tracer.return_value = mock_tracer
            result = get_tracer("helix.qa")
    mock_trace.get_tracer.assert_called_once_with("helix.qa")
    assert result is mock_tracer


def test_get_tracer_returns_noop_when_otel_not_available():
    with patch("core.telemetry._OTEL_AVAILABLE", False):
        result = get_tracer("helix.qa")
    assert isinstance(result, _NoopTracer)


# ---------------------------------------------------------------------------
# _NoopTracer and _NoopSpan behaviour
# ---------------------------------------------------------------------------

def test_noop_span_context_manager():
    span = _NoopSpan()
    with span as s:
        s.set_attribute("key", "value")
        s.record_exception(Exception("boom"))
        s.set_status("ok")
    # No exception raised — all methods are silent no-ops.


def test_noop_tracer_start_as_current_span_returns_noop_span():
    tracer = _NoopTracer()
    span = tracer.start_as_current_span("my-span")
    assert isinstance(span, _NoopSpan)


def test_noop_tracer_usable_as_context_manager():
    tracer = _NoopTracer()
    with tracer.start_as_current_span("my-span") as span:
        span.set_attribute("incident_id", "abc-123")


# ---------------------------------------------------------------------------
# get_otel_config env var parsing
# ---------------------------------------------------------------------------

def test_otel_config_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.enabled is False


def test_otel_config_enabled_true(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.enabled is True


def test_otel_config_enabled_1(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "1")
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.enabled is True


def test_otel_config_endpoint_default(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.endpoint == "http://localhost:4317"


def test_otel_config_endpoint_override(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.endpoint == "http://otel-collector:4317"


def test_otel_config_service_name_default(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.service_name == "helix"


def test_otel_config_service_name_override(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "helix-dev-agent")
    from core.config import get_otel_config
    cfg = get_otel_config()
    assert cfg.service_name == "helix-dev-agent"
