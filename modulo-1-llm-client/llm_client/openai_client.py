"""Cliente de OpenAI (SDK asíncrono ``AsyncOpenAI``)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from .base import BaseLLMClient
from .schemas import ChatMessage, ModelConfig, ModelResponse, StreamChunk, Usage


class OpenAIClient(BaseLLMClient):
    def __init__(self, config: ModelConfig) -> None:
        super().__init__(config)
        key = config.api_key.get_secret_value() if config.api_key else None
        # max_retries=0: los reintentos los controla el manager, no el SDK.
        self._client = AsyncOpenAI(api_key=key, timeout=config.timeout, max_retries=0)

    def _params(self, messages: list[ChatMessage]) -> dict:
        params: dict = {
            "model": self.config.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": self.config.temperature,
            "max_completion_tokens": self.config.max_tokens,
        }
        if self.config.top_p is not None:
            params["top_p"] = self.config.top_p
        return params

    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        # await sobre el cliente async: no bloquea el event loop.
        resp = await self._client.chat.completions.create(**self._params(messages))
        choice = resp.choices[0]
        usage = resp.usage
        return ModelResponse(
            provider="openai",
            model=resp.model,
            content=choice.message.content or "",
            finish_reason=choice.finish_reason,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[StreamChunk]:
        stream = await self._client.chat.completions.create(
            **self._params(messages), stream=True
        )
        async for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta.content
            if delta:
                yield StreamChunk(text=delta)

    async def aclose(self) -> None:
        await self._client.close()
