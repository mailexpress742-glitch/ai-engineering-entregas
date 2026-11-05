"""Tests sin red: la cadena se prueba con un 'LLM estructurado' falso."""

from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from chain import PipelineError, build_chain, process_text
from llm import ConfigError, get_chat_model
from schemas import Criticidad, EntidadesTecnicas

VALIDO = EntidadesTecnicas(
    tecnologias=["FastAPI", "Redis"],
    nivel_de_criticidad="alta",
    resumen_tecnico="API con caché en Redis; cuello de botella en conexiones.",
)


def ok(finish="end_turn"):
    return {
        "raw": AIMessage(content="", response_metadata={"stop_reason": finish}),
        "parsed": VALIDO,
        "parsing_error": None,
    }


def fake_llm(*respuestas):
    """Devuelve (runnable, contador): cada llamada consume la siguiente respuesta.

    Si la respuesta es una excepción, se lanza."""
    estado = {"calls": 0}

    def _call(_prompt):
        item = respuestas[min(estado["calls"], len(respuestas) - 1)]
        estado["calls"] += 1
        if isinstance(item, BaseException):
            raise item
        return item

    return RunnableLambda(_call), estado


def cadena(*respuestas):
    llm, estado = fake_llm(*respuestas)
    return build_chain(llm, max_attempts=3), estado


# ------------------------------------------------------------------ schemas
def test_esquema_acepta_salida_valida():
    assert VALIDO.nivel_de_criticidad is Criticidad.alta


def test_tecnologias_no_puede_estar_vacia():
    with pytest.raises(ValidationError):
        EntidadesTecnicas(tecnologias=[], nivel_de_criticidad="baja", resumen_tecnico="x" * 20)


def test_tecnologias_se_limpian_y_deduplican():
    e = EntidadesTecnicas(
        tecnologias=[" Redis ", "redis", "", "FastAPI"],
        nivel_de_criticidad="media",
        resumen_tecnico="Resumen técnico suficientemente largo.",
    )
    assert e.tecnologias == ["Redis", "FastAPI"]


@pytest.mark.parametrize("relleno", ["<UNKNOWN>", "Sistema (no especificado)", "N/A", "sistema"])
def test_rechaza_tecnologias_de_relleno(relleno):
    with pytest.raises(ValidationError):
        EntidadesTecnicas(
            tecnologias=[relleno], nivel_de_criticidad="baja", resumen_tecnico="z" * 20
        )


def test_criticidad_invalida():
    with pytest.raises(ValidationError):
        EntidadesTecnicas(
            tecnologias=["x"], nivel_de_criticidad="critica", resumen_tecnico="y" * 20
        )


# ------------------------------------------------------------------- cadena
async def test_camino_feliz():
    chain, estado = cadena(ok())
    res = await process_text("texto", chain=chain)
    assert res == VALIDO and estado["calls"] == 1


async def test_reintenta_si_el_json_esta_mal_formado():
    malo = {"raw": AIMessage(content=""), "parsed": None,
            "parsing_error": OutputParserException("JSON inválido")}
    chain, estado = cadena(malo, ok())
    res = await process_text("texto", chain=chain)
    assert res == VALIDO and estado["calls"] == 2


async def test_reintenta_si_falla_la_validacion_pydantic():
    try:
        EntidadesTecnicas(tecnologias=[], nivel_de_criticidad="baja", resumen_tecnico="x" * 20)
    except ValidationError as exc:
        error = exc
    chain, estado = cadena(error, ok())
    res = await process_text("texto", chain=chain)
    assert res == VALIDO and estado["calls"] == 2


async def test_detecta_respuesta_truncada_por_finish_reason():
    truncado = ok("max_tokens")  # trae 'parsed' pero el modelo se quedó sin tokens
    chain, estado = cadena(truncado, ok())
    res = await process_text("texto", chain=chain)
    assert res == VALIDO and estado["calls"] == 2  # se descartó el truncado y se reintentó


async def test_agotados_los_reintentos_error_controlado():
    malo = {"raw": AIMessage(content=""), "parsed": None, "parsing_error": OutputParserException("x")}
    chain, estado = cadena(malo)
    with pytest.raises(PipelineError):
        await process_text("texto", chain=chain)
    assert estado["calls"] == 3


async def test_error_no_reintentable_no_se_reintenta():
    chain, estado = cadena(KeyError("bug"))
    with pytest.raises(PipelineError):
        await process_text("texto", chain=chain)
    assert estado["calls"] == 1


async def test_texto_vacio():
    chain, estado = cadena(ok())
    with pytest.raises(PipelineError):
        await process_text("   ", chain=chain)
    assert estado["calls"] == 0


# ---------------------------------------------------------------------- llm
def test_proveedor_invalido():
    with pytest.raises(ConfigError):
        get_chat_model("cohere")


def test_falta_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        get_chat_model("anthropic")
