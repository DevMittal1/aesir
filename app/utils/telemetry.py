import logging
from fastapi import FastAPI
from app.config import settings

logger = logging.getLogger(__name__)

def init_telemetry(app: FastAPI) -> None:
    """
    Initialize OpenTelemetry Tracing and instrument FastAPI and outbound HTTPX calls.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        
        # Configure Resource
        resource = Resource(attributes={
            "service.name": settings.otel_service_name
        })
        
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        
        # Configure Span Processor
        processor = None
        if settings.otel_exporter_otlp_endpoint:
            try:
                # Attempt to use OTLP Exporter
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
                processor = BatchSpanProcessor(exporter)
                logger.info(f"OpenTelemetry configured to export traces via OTLP to: {settings.otel_exporter_otlp_endpoint}")
            except Exception:
                logger.exception("Failed to initialize OTLP exporter. Falling back to Console exporter.")
                
        if processor is None:
            import sys
            is_testing = "pytest" in sys.modules or "unittest" in sys.modules
            if is_testing:
                from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
                exporter = InMemorySpanExporter()
                processor = BatchSpanProcessor(exporter)
                logger.info("OpenTelemetry configured to export traces to InMemorySpanExporter.")
            else:
                exporter = ConsoleSpanExporter()
                processor = BatchSpanProcessor(exporter)
                logger.info("OpenTelemetry configured to export traces to Console.")
            
        provider.add_span_processor(processor)
        
        # Instrument FastAPI Application
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI application instrumented with OpenTelemetry.")
        
        # Instrument Outbound HTTPX client calls
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX Client instrumented with OpenTelemetry.")
        
    except ImportError as err:
        logger.warning(f"OpenTelemetry packages not fully installed, running without telemetry. Error: {err}")
    except Exception:
        logger.exception("Error occurred while initializing OpenTelemetry.")
