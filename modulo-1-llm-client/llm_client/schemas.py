"""Esquemas Pydantic: mensajes, configuración del modelo y respuestas.

Todo lo que entra o sale de los clientes pasa por estos modelos, así nunca
se trabaja con diccionarios anidados sin validar.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Provider = Literal["openai", "anthropic"]
Role = Literal["system", "user", "assistant"]

ErrorKind = Literal[
    "auth",  # API key inválida / sin permisos
    "rate_limit",  # límite de tasa o cuota agotada
    "network",  # error de conexión
    "timeout",  # la llamada tardó demasiado
    "bad_request",  # parámetros inválidos para el proveedor
    "api_error",  # error 5xx u otro error de la API
    "unknown",  # cualquier otra cosa inesperada
]


class ChatMessage(BaseModel):
    """Un mensaje de la conversación."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = Field(min_length=1)


class ModelConfig(BaseModel):
    """Configuración validada del modelo y del cliente."""

    model_config = ConfigDict(extra="forbid")

    provider: Provider = "openai"
    model: str = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0, le=200_000)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    timeout: float = Field(default=60.0, gt=0.0, description="Segundos por llamada")
    max_retries: int = Field(default=3, ge=0, le=10, description="Reintentos propios")
    # SecretStr evita que la key aparezca en repr(), logs o tracebacks.
    api_key: SecretStr | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(BaseModel):
    """Error controlado: lo que devolvemos en vez de dejar escapar una excepción."""

    kind: ErrorKind
    message: str
    retryable: bool = False
    status_code: int | None = None


class ModelResponse(BaseModel):
    """Respuesta unificada, igual para OpenAI y Anthropic."""

    provider: Provider
    model: str
    content: str = ""
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    error: LLMError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class StreamChunk(BaseModel):
    """Fragmento emitido por el streaming.

    Un chunk normal trae ``text``. Si algo falla, el generador emite un último
    chunk con ``error`` y termina limpiamente (no lanza excepción).
    """

    text: str = ""
    error: LLMError | None = None
