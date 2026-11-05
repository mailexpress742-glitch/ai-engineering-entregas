"""Embeddings: una sola fábrica para ingesta y consulta, siempre de 1536 dimensiones."""

from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable

import openai
import tiktoken
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

import config

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

logger = logging.getLogger("rag.embeddings")


class ConfigError(ValueError):
    """Variable de entorno faltante o valor inválido."""


def embedding_model_name() -> str:
    provider = config.embedding_provider()
    if provider not in config.EMBEDDING_MODELS:
        raise ConfigError(f"EMBEDDINGS_PROVIDER='{provider}' inválido. Usá: {', '.join(config.EMBEDDING_MODELS)}")
    return config.EMBEDDING_MODELS[provider]


_RETRY_IN = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


class ThrottledEmbeddings(Embeddings):
    """Envuelve unos embeddings respetando un presupuesto de tokens por minuto.

    El plan gratuito de Gemini admite 30.000 tokens de embeddings por minuto; un corpus
    mayor que eso se rechaza con 429. Este wrapper parte los pedidos en grupos que
    caben en el presupuesto, espera cuando la ventana de 60 s está llena y, si aun así
    llega un 429, espera el tiempo que indica la propia API y reintenta.
    """

    def __init__(
        self,
        inner: Embeddings,
        tokens_per_minute: int,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_retries: int = 5,
    ) -> None:
        self.inner = inner
        self.budget = tokens_per_minute
        self._sleep, self._clock, self.max_retries = sleep, clock, max_retries
        self._events: deque[tuple[float, int]] = deque()  # (instante, tokens)
        self._enc = tiktoken.get_encoding(config.TOKEN_ENCODING)

    def _tokens(self, text: str) -> int:
        return len(self._enc.encode(text)) + 1

    def _wait_for(self, needed: int) -> None:
        while True:
            now = self._clock()
            while self._events and now - self._events[0][0] >= 60:
                self._events.popleft()
            if sum(t for _, t in self._events) + needed <= self.budget or not self._events:
                return
            espera = 60 - (now - self._events[0][0]) + 0.5
            logger.info("Límite de embeddings por minuto: esperando %.0f s...", espera)
            self._sleep(espera)

    def _call(self, fn: Callable, payload, tokens: int):
        for intento in range(self.max_retries + 1):
            self._wait_for(tokens)
            try:
                result = fn(payload)
            except openai.RateLimitError as exc:
                if intento == self.max_retries:
                    raise
                m = _RETRY_IN.search(str(exc))
                espera = float(m.group(1)) + 1 if m else 30.0
                logger.warning("429 del proveedor: espero %.0f s y reintento (%d/%d)", espera, intento + 1, self.max_retries)
                self._sleep(espera)
                continue
            self._events.append((self._clock(), tokens))
            return result

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        grupo: list[str] = []
        usados = 0
        for t in texts:
            n = self._tokens(t)
            if grupo and usados + n > self.budget:
                out += self._call(self.inner.embed_documents, grupo, usados)
                grupo, usados = [], 0
            grupo.append(t)
            usados += n
        if grupo:
            out += self._call(self.inner.embed_documents, grupo, usados)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._call(self.inner.embed_query, text, self._tokens(text))


def get_embeddings() -> Embeddings:
    provider = config.embedding_provider()
    model = embedding_model_name()
    env_key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    key = os.getenv(env_key)
    if not key:
        raise ConfigError(f"Falta {env_key} en el .env (se usa para los embeddings)")
    inner = _build(provider, model, key)
    # Gemini (plan gratuito): 30.000 tokens/min -> se usa un margen de seguridad. 0 = sin límite.
    tpm = int(os.getenv("EMBEDDINGS_TOKENS_PER_MINUTE", "25000" if provider == "gemini" else "0"))
    return ThrottledEmbeddings(inner, tpm) if tpm > 0 else inner


def _build(provider: str, model: str, key: str) -> Embeddings:
    return OpenAIEmbeddings(
        model=model,
        api_key=SecretStr(key),
        base_url=GEMINI_BASE_URL if provider == "gemini" else None,
        dimensions=config.EMBEDDING_DIMENSION,
        check_embedding_ctx_length=False,
        max_retries=1,  # los 429 los maneja ThrottledEmbeddings esperando lo que indica la API
        timeout=60,
    )
