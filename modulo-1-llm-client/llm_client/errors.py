"""Traducción de excepciones de los SDKs a un ``LLMError`` estructurado."""

from __future__ import annotations

import anthropic
import openai

from .schemas import LLMError


def _detail(exc: BaseException) -> str:
    """Mensaje legible: el cuerpo del error de la API si existe (ej. 404 con motivo)."""
    text = str(exc)
    response = getattr(exc, "response", None)
    if response is not None and text.strip().startswith("Error code:"):
        try:
            body = response.text.strip()
        except Exception:  # noqa: BLE001
            body = ""
        if body:
            text = f"{text} - {' '.join(body.split())[:300]}"
    return text


def to_llm_error(exc: BaseException) -> LLMError:
    """Convierte cualquier excepción en un error controlado.

    Los SDKs de OpenAI y Anthropic comparten nombres de clases de error, por
    eso se manejan en el mismo lugar. Importante: ``APITimeoutError`` hereda de
    ``APIConnectionError``, así que se evalúa primero.
    """
    # Nunca interpolar la API key: los mensajes del SDK ya la enmascaran.
    msg = _detail(exc) or exc.__class__.__name__

    if isinstance(exc, (openai.APITimeoutError, anthropic.APITimeoutError, TimeoutError)):
        return LLMError(kind="timeout", message=msg, retryable=True)
    if isinstance(exc, (openai.APIConnectionError, anthropic.APIConnectionError)):
        return LLMError(kind="network", message=msg, retryable=True)
    if isinstance(exc, (openai.RateLimitError, anthropic.RateLimitError)):
        return LLMError(kind="rate_limit", message=msg, retryable=True, status_code=429)
    if isinstance(exc, (openai.AuthenticationError, anthropic.AuthenticationError)):
        return LLMError(kind="auth", message=msg, status_code=401)
    if isinstance(exc, (openai.PermissionDeniedError, anthropic.PermissionDeniedError)):
        return LLMError(kind="auth", message=msg, status_code=403)
    if isinstance(exc, (openai.BadRequestError, anthropic.BadRequestError)):
        return LLMError(kind="bad_request", message=msg, status_code=400)
    if isinstance(exc, (openai.APIStatusError, anthropic.APIStatusError)):
        status = exc.status_code
        return LLMError(
            kind="api_error",
            message=msg,
            retryable=status >= 500,
            status_code=status,
        )
    return LLMError(kind="unknown", message=f"{exc.__class__.__name__}: {msg}")
