"""Observabilidad: trazas de cada ejecución hacia Arize Phoenix (vía OpenInference).

``init_observability()`` registra el exportador OTLP de Phoenix y activa la instrumentación de
LangChain/LangGraph: cada nodo del grafo, cada llamada al LLM (con tokens de entrada/salida, de
donde Phoenix calcula el costo) y cada herramienta se convierten en spans anidados.

``@observar`` abre un span propio (el "job") que contiene todo el trabajo de una ejecución, de
modo que la traza completa y su latencia total se vean como una sola unidad en el dashboard.

Alternativa LangSmith: no requiere código; basta con ``LANGSMITH_TRACING=true`` y
``LANGSMITH_API_KEY`` en el entorno (LangChain las lee solo).
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger("observabilidad")
T = TypeVar("T")
_inicializada = False


def init_observability() -> bool:
    """Activa el envío de trazas a Phoenix. Devuelve False (sin error) si no está configurado."""
    global _inicializada
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "").rstrip("/")
    if _inicializada or not endpoint or os.getenv("OBSERVABILIDAD", "phoenix").lower() == "off":
        return _inicializada
    # El SDK de Anthropic (versiones recientes) emite sus propios spans OpenTelemetry por cada llamada, con los mismos
    # tokens que ya registra la instrumentación de LangChain: Phoenix los sumaba dos veces (tokens y costo x2).
    # Se apagan antes de crear el cliente del modelo; el span del LLM sigue estando (lo emite LangChain).
    os.environ.setdefault("ANTHROPIC_OPEN_TELEMETRY", "false")
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from phoenix.otel import register

    proyecto = os.getenv("PHOENIX_PROJECT_NAME", "orquestador-m7")
    provider = register(project_name=proyecto, endpoint=f"{endpoint}/v1/traces", batch=True, auto_instrument=False)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    _inicializada = True
    logger.info("Observabilidad activa: proyecto '%s' → %s", proyecto, endpoint)
    return True


def observar(nombre: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorador: envuelve una corrutina en un span (CHAIN) con su entrada, salida y error."""

    def decorador(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def envuelta(*args: Any, **kwargs: Any) -> T:
            tracer = trace.get_tracer("orquestador")
            with tracer.start_as_current_span(nombre) as span:
                span.set_attribute("openinference.span.kind", "CHAIN")
                for k, v in kwargs.items():
                    if isinstance(v, (str, int, float, bool)):
                        span.set_attribute(f"job.{k}", v)
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        return envuelta

    return decorador
