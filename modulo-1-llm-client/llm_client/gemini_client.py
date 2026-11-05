"""Cliente de Gemini vía el endpoint compatible con OpenAI de Google.

Reutiliza ``AsyncOpenAI`` apuntando a otro ``base_url``: no requiere un SDK extra.
"""

from __future__ import annotations

from .openai_client import OpenAIClient


class GeminiClient(OpenAIClient):
    provider = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    max_tokens_param = "max_tokens"
