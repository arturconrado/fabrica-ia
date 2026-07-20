"""Content-free OpenTelemetry spans with an explicit production OTLP exporter."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator, Mapping

from app.core.config import Settings, get_settings


_configuration_lock = Lock()
_configured = False
_provider = None


def _headers(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in value.split(","):
        key, separator, content = item.strip().partition("=")
        if separator and key and content:
            parsed[key] = content
    return parsed


def configure_tracing(settings: Settings | None = None, *, service_name: str | None = None) -> bool:
    """Install one process-wide SDK provider and optional OTLP batch exporter.

    Tenant data and prompts are never attached by this module. Production
    validation requires an OTLP endpoint; local/test runtimes may deliberately
    keep the API provider unconfigured and rely on persisted evidence instead.
    """

    global _configured, _provider
    settings = settings or get_settings()
    if not settings.observability_enabled:
        return False
    with _configuration_lock:
        if _configured:
            return bool(_provider)
        endpoint = settings.otel_exporter_otlp_endpoint.strip()
        if not endpoint:
            return False
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name or settings.otel_service_name,
                    "service.namespace": "agentic-software-factory",
                    "deployment.environment": settings.environment,
                }
            )
        )
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=_headers(settings.otel_exporter_otlp_headers) or None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider = provider
        _configured = True
        return True


def shutdown_tracing() -> None:
    provider = _provider
    if provider is not None:
        provider.shutdown()


@contextmanager
def trace_span(name: str, attributes: Mapping[str, str | int | float | bool | None] | None = None) -> Iterator[object | None]:
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("agentic-software-factory")
        safe_attributes = {key: value for key, value in (attributes or {}).items() if value is not None}
        with tracer.start_as_current_span(name, attributes=safe_attributes) as span:
            yield span
    except ImportError:
        yield None
