"""OpenTelemetry bootstrap: tracing export to the OTel Collector.

Kept out of ``domain``/``service`` on purpose: business code must not import
Grafana/Loki/Tempo/Prometheus/OpenTelemetry directly (see docs/plan/observabilidad.md).
Everything here is a no-op when ``otel_exporter_otlp_endpoint`` is unset, so local
dev, tests and CI never need the observability stack running.
"""

import logging
import os
from functools import lru_cache

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_APP_ENV = os.getenv("APP_ENV", "dev")
SERVICE_NAME = "fitcoach-ia"
SERVICE_VERSION = os.getenv("APP_VERSION", "unknown")


class OTelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        env_prefix="otel_",
        extra="ignore",
    )

    exporter_otlp_endpoint: str | None = None


@lru_cache
def get_otel_settings() -> OTelSettings:
    return OTelSettings()


def configure_telemetry(app: FastAPI) -> None:
    """Wire up tracing if an OTLP endpoint is configured; no-op otherwise.

    Safe to call unconditionally from the app lifespan: without an endpoint it
    only logs and returns, so tests/CI/local dev are unaffected.
    """
    settings = get_otel_settings()
    if not settings.exporter_otlp_endpoint:
        logger.info("otel_exporter_otlp_endpoint not set: tracing export disabled")
        return

    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": SERVICE_VERSION,
        "deployment.environment.name": _APP_ENV,
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.exporter_otlp_endpoint, timeout=5)
    # Async, non-blocking export: a down Collector must never slow down a request.
    provider.add_span_processor(BatchSpanProcessor(exporter, export_timeout_millis=5000))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()
    logger.info(f"tracing export enabled: endpoint={settings.exporter_otlp_endpoint}")


def shutdown_telemetry() -> None:
    """Flush and close the tracer provider; no-op if tracing was never configured."""
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
