"""Cliente de Anthropic (SDK asíncrono ``AsyncAnthropic``)."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from anthropic.resources.messages import AsyncMessages

from .base import BaseLLMClient
from .schemas import ChatMessage, ModelConfig, ModelResponse, StreamChunk, Usage

_SDK_ACCEPTS_SAMPLING = "temperature" in inspect.signature(AsyncMessages.create).parameters


class AnthropicClient(BaseLLMClient):
    def __init__(self, config: ModelConfig) -> None:
        super().__init__(config)
        key = config.api_key.get_secret_value() if config.api_key else None
        self._client = AsyncAnthropic(api_key=key, timeout=config.timeout, max_retries=0)

    def _params(self, messages: list[ChatMessage]) -> dict:
        # Diferencia clave con OpenAI: el mensaje "system" va aparte,
        # no dentro de la lista de mensajes.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        params: dict = {
            "model": self.config.model,
            "messages": [m.model_dump() for m in messages if m.role != "system"],
            "max_tokens": self.config.max_tokens,
        }
        if system:
            params["system"] = system
        # Las versiones recientes del SDK/API de Anthropic dejaron de aceptar
        # parámetros de muestreo; solo se envían si el SDK instalado los admite.
        if _SDK_ACCEPTS_SAMPLING:
            # Anthropic admite temperature solo de 0 a 1 (el esquema permite 0-2).
            params["temperature"] = min(self.config.temperature, 1.0)
            if self.config.top_p is not None:
                params["top_p"] = self.config.top_p
        return params

    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        resp = await self._client.messages.create(**self._params(messages))
        # Otra diferencia: content es una lista de bloques, no un string.
        text = "".join(b.text for b in resp.content if b.type == "text")
        return ModelResponse(
            provider="anthropic",
            model=resp.model,
            content=text,
            finish_reason=resp.stop_reason,
            usage=Usage(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[StreamChunk]:
        async with self._client.messages.stream(**self._params(messages)) as stream:
            async for text in stream.text_stream:
                if text:
                    yield StreamChunk(text=text)

    async def aclose(self) -> None:
        await self._client.close()
