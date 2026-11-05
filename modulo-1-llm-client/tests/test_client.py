"""Tests sin red ni API keys: los clientes se reemplazan por fakes."""

from __future__ import annotations

import openai

try:  # las versiones nuevas de los SDKs usan httpx2; las anteriores, httpx
    import httpx2 as httpx
except ImportError:
    import httpx
import pytest
from pydantic import ValidationError

from llm_client import (
    AnthropicClient,
    AsyncLLMManager,
    BaseLLMClient,
    GeminiClient,
    ChatMessage,
    ModelConfig,
    ModelResponse,
    OpenAIClient,
    StreamChunk,
)
from llm_client.errors import to_llm_error

MSGS = [ChatMessage(role="user", content="hola")]
REQ = httpx.Request("POST", "https://example.test")


def rate_limit_error() -> openai.RateLimitError:
    return openai.RateLimitError(
        "cuota agotada", response=httpx.Response(429, request=REQ), body=None
    )


def auth_error() -> openai.AuthenticationError:
    return openai.AuthenticationError(
        "key inválida", response=httpx.Response(401, request=REQ), body=None
    )


class FakeClient(BaseLLMClient):
    """Falla ``fail_times`` veces con ``exc`` y luego responde bien."""

    def __init__(self, config, exc=None, fail_times=0, tokens=("a", "b", "c")):
        super().__init__(config)
        self.exc, self.fail_times, self.tokens, self.calls = exc, fail_times, tokens, 0

    async def generate(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return ModelResponse(provider="openai", model="fake", content="ok")

    async def stream(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        for t in self.tokens:
            yield StreamChunk(text=t)


def make_manager(**client_kwargs) -> tuple[AsyncLLMManager, FakeClient]:
    async def no_sleep(_):
        return None

    cfg = ModelConfig(provider="openai", model="x", max_retries=2, api_key="k")
    mgr = AsyncLLMManager(cfg, sleep=no_sleep)
    mgr.client = FakeClient(cfg, **client_kwargs)
    return mgr, mgr.client


# ---------------------------------------------------------------- schemas
@pytest.mark.parametrize("temp", [-0.1, 2.1])
def test_temperature_fuera_de_rango(temp):
    with pytest.raises(ValidationError):
        ModelConfig(model="x", temperature=temp)


def test_max_tokens_debe_ser_positivo():
    with pytest.raises(ValidationError):
        ModelConfig(model="x", max_tokens=0)


def test_rol_invalido():
    with pytest.raises(ValidationError):
        ChatMessage(role="robot", content="hola")


def test_api_key_no_aparece_en_repr():
    cfg = ModelConfig(model="x", api_key="sk-super-secreta")
    assert "sk-super-secreta" not in repr(cfg)


# ---------------------------------------------------------------- factory
def test_factory_elige_proveedor(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert isinstance(AsyncLLMManager.from_env().client, AnthropicClient)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert isinstance(AsyncLLMManager.from_env().client, OpenAIClient)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    mgr = AsyncLLMManager.from_env()
    assert isinstance(mgr.client, GeminiClient) and mgr.config.model.startswith("gemini")


def test_factory_proveedor_invalido(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValueError):
        AsyncLLMManager.from_env()


# ---------------------------------------------------------------- errores
def test_mapeo_de_errores():
    assert to_llm_error(rate_limit_error()).kind == "rate_limit"
    assert to_llm_error(auth_error()).kind == "auth"
    assert to_llm_error(openai.APIConnectionError(request=REQ)).kind == "network"
    assert to_llm_error(openai.APITimeoutError(request=REQ)).kind == "timeout"
    assert to_llm_error(RuntimeError("boom")).kind == "unknown"


async def test_generate_ok():
    mgr, _ = make_manager()
    resp = await mgr.generate(MSGS)
    assert resp.ok and resp.content == "ok"


async def test_rate_limit_se_reintenta_y_se_recupera():
    mgr, client = make_manager(exc=rate_limit_error(), fail_times=2)
    resp = await mgr.generate(MSGS)
    assert resp.ok and client.calls == 3


async def test_rate_limit_persistente_devuelve_error_controlado():
    mgr, client = make_manager(exc=rate_limit_error(), fail_times=99)
    resp = await mgr.generate(MSGS)  # no lanza
    assert not resp.ok and resp.error.kind == "rate_limit"
    assert client.calls == 3  # 1 intento + 2 reintentos


async def test_auth_no_se_reintenta():
    mgr, client = make_manager(exc=auth_error(), fail_times=99)
    resp = await mgr.generate(MSGS)
    assert resp.error.kind == "auth" and client.calls == 1


async def test_error_inesperado_no_rompe_el_loop():
    mgr, _ = make_manager(exc=RuntimeError("boom"), fail_times=99)
    resp = await mgr.generate(MSGS)
    assert resp.error.kind == "unknown"


async def test_sin_api_key_devuelve_error_controlado(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mgr = AsyncLLMManager(ModelConfig(provider="openai", model="x"))
    resp = await mgr.generate(MSGS)
    assert resp.error.kind == "auth"
    chunks = [c async for c in mgr.stream(MSGS)]
    assert chunks[0].error.kind == "auth"
    await mgr.aclose()


# ---------------------------------------------------------------- streaming
async def test_stream_emite_tokens_en_orden():
    mgr, _ = make_manager()
    texts = [c.text async for c in mgr.stream(MSGS)]
    assert texts == ["a", "b", "c"]


async def test_stream_reintenta_antes_del_primer_token():
    mgr, client = make_manager(exc=rate_limit_error(), fail_times=1)
    chunks = [c async for c in mgr.stream(MSGS)]
    assert "".join(c.text for c in chunks) == "abc" and client.calls == 2


async def test_stream_error_final_controlado():
    mgr, _ = make_manager(exc=auth_error(), fail_times=99)
    chunks = [c async for c in mgr.stream(MSGS)]
    assert len(chunks) == 1 and chunks[0].error.kind == "auth"


async def test_stream_error_a_mitad_no_duplica_texto():
    class Cortado(FakeClient):
        async def stream(self, messages):
            yield StreamChunk(text="a")
            raise rate_limit_error()

    mgr, _ = make_manager()
    mgr.client = Cortado(mgr.config)
    chunks = [c async for c in mgr.stream(MSGS)]
    assert chunks[0].text == "a" and chunks[-1].error.kind == "rate_limit"
    assert len(chunks) == 2
