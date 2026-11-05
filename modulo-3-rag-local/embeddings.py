"""Embeddings: UNA sola fábrica, usada tanto al indexar como al consultar."""

from __future__ import annotations

import os

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from config import EMBEDDING_MODEL
from llm import GEMINI_BASE_URL, ConfigError


def get_embeddings() -> Embeddings:
    """Embeddings de Gemini vía su endpoint compatible con OpenAI.

    ``check_embedding_ctx_length=False`` evita que LangChain tokenice con tiktoken
    (pensado para modelos de OpenAI) y manda el texto tal cual.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ConfigError("Falta GEMINI_API_KEY en el .env (se usa para los embeddings)")
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=SecretStr(key),
        base_url=GEMINI_BASE_URL,
        check_embedding_ctx_length=False,
        max_retries=3,
        timeout=60,
    )
