"""OpenTelemetry tracer setup.

Spans are always created (so every request gets a trace id, satisfying
the Phase 2 "trace per request" deliverable) but are only exported
somewhere if ARCF_OTEL_EXPORTER_OTLP_ENDPOINT is set and the OTLP
exporter package happens to be installed — this module has no hard
dependency on it, since only opentelemetry-sdk/api are in the Phase 2
dependency set.
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from shared.config import Settings

_configured = False


def configure_tracing(settings: Settings) -> trace.Tracer:
    global _configured
    if not _configured:
        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.otel_service_name})
        )
        if settings.otel_exporter_otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
                    OTLPSpanExporter,
                )
            except ImportError:
                pass
            else:
                exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _configured = True
    return trace.get_tracer(settings.otel_service_name)
