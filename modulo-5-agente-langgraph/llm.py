"""Fábrica de modelos de chat de LangChain (misma idea que el Módulo 1).

``LLM_PROVIDER`` elige el proveedor; cada uno lee su API key del entorno.
Gemini se usa con ``ChatOpenAI`` apuntando al endpoint compatible de Google.
"""

from __future__ import annotations

import os
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

Provider = Literal["anthropic", "openai", "gemini"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.5-flash-lite",
}
ENV_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class ConfigError(ValueError):
    """Configuración inválida (proveedor desconocido o API key faltante)."""


def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    *,
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> BaseChatModel:
    provider = (provider or os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
    if provider not in ENV_KEYS:
        raise ConfigError(f"LLM_PROVIDER='{provider}' no es válido. Usá: {', '.join(ENV_KEYS)}")
    key = os.getenv(ENV_KEYS[provider])
    if not key:
        raise ConfigError(f"Falta la API key: definí {ENV_KEYS[provider]} en el .env")
    model = model or os.getenv("LLM_MODEL") or DEFAULT_MODELS[provider]
    secret = SecretStr(key)

    # max_retries=0 en el modelo: los reintentos los maneja la cadena (.with_retry()).
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model, api_key=secret, max_tokens=max_tokens, timeout=timeout, max_retries=0
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=secret,
        base_url=GEMINI_BASE_URL if provider == "gemini" else None,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=0,
    )
