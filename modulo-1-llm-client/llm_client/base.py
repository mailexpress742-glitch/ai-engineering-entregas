"""Clase base abstracta común a todos los proveedores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .schemas import ChatMessage, ModelConfig, ModelResponse, StreamChunk


class BaseLLMClient(ABC):
    """Interfaz que cumplen OpenAIClient y AnthropicClient.

    Los métodos de las subclases *lanzan* las excepciones del SDK; el
    ``AsyncLLMManager`` es quien las captura, reintenta y las convierte en
    ``LLMError``. Así la lógica de reintentos vive en un solo lugar.
    """

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    @abstractmethod
    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        """Una respuesta completa."""

    @abstractmethod
    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[StreamChunk]:
        """Generador asíncrono de fragmentos de texto (``async for`` + ``yield``)."""

    async def aclose(self) -> None:
        """Libera el cliente HTTP subyacente."""
