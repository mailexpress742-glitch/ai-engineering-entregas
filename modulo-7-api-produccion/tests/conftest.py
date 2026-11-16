"""Fixtures comunes: Redis falso (fakeredis) y piezas del grafo con guion, sin red ni LLM."""

from __future__ import annotations

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.agents import action_agent
from app.graph import build_graph
from app.redis_checkpointer import AsyncRedisCheckpointer
from app.supervisor import DecisionLLM


@pytest.fixture
def servidor_redis() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def redis_factory(servidor_redis):
    """Igual que en producción: un cliente con decode_responses (jobs) y otro binario (checkpoints)."""
    return lambda decode: FakeAsyncRedis(server=servidor_redis, decode_responses=decode)


@pytest.fixture(autouse=True)
def limpiar_salida():
    action_agent.ENVIADOS.clear()
    yield
    action_agent.configurar_salida(None)


def supervisor_con_guion(*decisiones):
    """Supervisor que devuelve ``(siguiente, instruccion)`` en orden (repite el último)."""
    i = {"n": 0}

    async def decidir(_estado):
        sig, instr = decisiones[min(i["n"], len(decisiones) - 1)]
        i["n"] += 1
        return DecisionLLM(razon="(guion)", siguiente=sig, instruccion=instr)

    return decidir


async def investigador(_entrada):
    return {"contenido": "SEV1: 5 min; actualización cada 15 min; RTO 2 h.", "herramientas_usadas": ["buscar_documentacion"],
            "fuentes": ["02_respuesta_a_incidentes.md#2. Niveles de severidad"]}


async def analista(_entrada):
    return {"contenido": "120 / 15 = 8 actualizaciones.", "herramientas_usadas": ["calcular"], "fuentes": []}


async def sintetizar(estado):
    return "Respuesta final de prueba."


def grafo_con_redis(redis_factory, *decisiones, ejecutor=None, **piezas):
    """Grafo real (estado, reglas, aristas) con piezas de guion y checkpointer sobre Redis."""
    async def eje(entrada):
        await action_agent.enviar_comunicado.ainvoke({"destinatario": "guardia", "asunto": "SEV1", "mensaje": entrada[:40]})
        return {"contenido": "Comunicado enviado a guardia.", "herramientas_usadas": ["enviar_comunicado"], "fuentes": []}

    return build_graph(
        decidir=supervisor_con_guion(*decisiones),
        investigador=piezas.get("investigador", investigador),
        analista=piezas.get("analista", analista),
        ejecutor=ejecutor or eje,
        sintetizar=piezas.get("sintetizar", sintetizar),
        checkpointer=AsyncRedisCheckpointer(redis_factory(False)),
    )
