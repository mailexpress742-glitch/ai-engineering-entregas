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
    return {"contenido": "Carta documento AMBA: 3 días hábiles.", "herramientas_usadas": ["buscar_conocimiento"],
            "fuentes": ["03_plazos_de_entrega.md#Tabla de plazos de entrega"]}


async def analista(_entrada):
    return {"contenido": "5 - 3 = 2 días hábiles de atraso.", "herramientas_usadas": ["calcular"], "fuentes": []}


async def sintetizar(estado):
    return "Respuesta final de prueba."


def grafo_con_redis(redis_factory, *decisiones, ejecutor=None, exigir_accion=False, **piezas):
    """Grafo real (estado, reglas, aristas) con piezas de guion y checkpointer sobre Redis."""
    async def eje(entrada):
        await action_agent.responder_cliente(
            pieza_id="CD-100231", destinatario="Cliente de prueba", asunto="Seguimiento de su pieza CD-100231",
            mensaje="Estimado/a cliente: su pieza CD-100231 está en distribución con 2 días hábiles de atraso. " + entrada[:20],
        )
        return {"contenido": "Respuesta enviada al cliente.", "herramientas_usadas": ["responder_cliente"], "fuentes": []}

    return build_graph(
        decidir=supervisor_con_guion(*decisiones),
        exigir_accion=exigir_accion,
        investigador=piezas.get("investigador", investigador),
        analista=piezas.get("analista", analista),
        ejecutor=ejecutor or eje,
        sintetizar=piezas.get("sintetizar", sintetizar),
        checkpointer=AsyncRedisCheckpointer(redis_factory(False)),
    )
