"""AsyncLLMManager: elige proveedor por configuración y blinda las llamadas."""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import AsyncIterator, Awaitable, Callable

from pydantic import SecretStr

from .anthropic_client import AnthropicClient
from .base import BaseLLMClient
from .errors import to_llm_error
from .openai_client import OpenAIClient
from .schemas import (
    ChatMessage,
    LLMError,
    ModelConfig,
    ModelResponse,
    Provider,
    StreamChunk,
)

# Factory: proveedor -> clase de cliente.
_PROVIDERS: dict[Provider, type[BaseLLMClient]] = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
}

_DEFAULT_MODELS: dict[Provider, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
}

_ENV_KEYS: dict[Provider, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class AsyncLLMManager:
    """Punto de entrada único. Nunca deja escapar excepciones del proveedor."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep  # inyectable para testear sin esperar
        self.client: BaseLLMClient | None = None
        self._init_error: LLMError | None = None
        env_key = _ENV_KEYS[config.provider]
        try:
            if config.api_key is None and not os.getenv(env_key):
                raise ValueError(f"falta la API key ({env_key} en el .env)")
            self.client = _PROVIDERS[config.provider](config)
        except Exception as exc:  # noqa: BLE001 - típicamente: falta la API key
            self._init_error = LLMError(
                kind="auth",
                message=f"No se pudo crear el cliente de {config.provider}: {exc}",
            )

    @classmethod
    def from_env(cls, **overrides: object) -> AsyncLLMManager:
        """Construye el manager desde variables de entorno.

        ``LLM_PROVIDER`` decide el proveedor; el resto (``LLM_MODEL``,
        ``LLM_TEMPERATURE``, ``LLM_MAX_TOKENS``...) es opcional. Si algún valor
        es inválido, Pydantic lanza ``ValidationError`` al arrancar: es un error
        de configuración, no de ejecución.
        """
        provider = str(overrides.pop("provider", None) or os.getenv("LLM_PROVIDER", "openai"))
        provider = provider.strip().lower()
        if provider not in _PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER='{provider}' no es válido. Usá: {', '.join(_PROVIDERS)}"
            )
        data: dict = {
            "provider": provider,
            "model": os.getenv("LLM_MODEL") or _DEFAULT_MODELS[provider],
        }
        if key := os.getenv(_ENV_KEYS[provider]):
            data["api_key"] = SecretStr(key)
        for field, env in (
            ("temperature", "LLM_TEMPERATURE"),
            ("max_tokens", "LLM_MAX_TOKENS"),
            ("timeout", "LLM_TIMEOUT"),
            ("max_retries", "LLM_MAX_RETRIES"),
        ):
            if value := os.getenv(env):
                data[field] = value
        data.update(overrides)
        return cls(ModelConfig(**data))

    # ------------------------------------------------------------------ #
    def _delay(self, attempt: int) -> float:
        """Backoff exponencial con jitter: ~1s, 2s, 4s..."""
        return (2**attempt) * (0.5 + random.random() / 2)

    def _error_response(self, error: LLMError) -> ModelResponse:
        return ModelResponse(
            provider=self.config.provider, model=self.config.model, error=error
        )

    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        """Respuesta completa. Si falla, devuelve ``ModelResponse`` con ``error``."""
        if self.client is None:
            assert self._init_error is not None
            return self._error_response(self._init_error)
        error: LLMError | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                return await self.client.generate(messages)
            except asyncio.CancelledError:
                raise  # nunca tragarse la cancelación del event loop
            except Exception as exc:  # noqa: BLE001 - se traduce a error controlado
                error = to_llm_error(exc)
                if not error.retryable or attempt == self.config.max_retries:
                    break
                await self._sleep(self._delay(attempt))
        assert error is not None
        return self._error_response(error)

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[StreamChunk]:
        """Genera fragmentos de texto a medida que llegan de la API.

        Se reintenta solo si el fallo ocurre *antes* del primer token (después
        ya se emitió texto y repetir duplicaría la salida). Un error se informa
        con un último ``StreamChunk(error=...)``.
        """
        if self.client is None:
            yield StreamChunk(error=self._init_error)
            return
        for attempt in range(self.config.max_retries + 1):
            started = False
            try:
                async for chunk in self.client.stream(messages):
                    started = True
                    yield chunk
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                error = to_llm_error(exc)
                if started or not error.retryable or attempt == self.config.max_retries:
                    yield StreamChunk(error=error)
                    return
                await self._sleep(self._delay(attempt))

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def __aenter__(self) -> AsyncLLMManager:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
