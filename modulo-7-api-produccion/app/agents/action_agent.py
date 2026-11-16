"""Agente ejecutor: realiza acciones con **efectos secundarios** (enviar un comunicado).

Es el único agente cuya herramienta cambia el mundo exterior, por eso el grafo lo protege con
una aprobación humana obligatoria (``hitl.py``): el supervisor nunca llega acá sin pasar por
el nodo ``aprobacion``. El envío es simulado (no sale ningún mail real): queda registrado en
una "bandeja de salida" que la API persiste en Redis, y sirve para comprobar que, sin
aprobación, la acción NO ocurre.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool

EJECUTOR_PROMPT = (
    "Sos el EJECUTOR de un equipo. Ya te aprobaron una acción: tu tarea es llevarla a cabo con tu "
    "herramienta `enviar_comunicado`, una sola vez.\n"
    "- Redactá el comunicado usando EXCLUSIVAMENTE los datos y cifras que te pasan; no inventes nada.\n"
    "- Elegí un destinatario razonable si la instrucción no lo indica (por ejemplo «equipo-guardia»).\n"
    "- Cuando la herramienta confirme el envío, respondé en una línea qué enviaste y a quién."
)

Salida = Callable[[dict[str, Any]], Awaitable[None]]
ENVIADOS: list[dict[str, Any]] = []  # bandeja de salida por defecto (en memoria)


async def _salida_en_memoria(registro: dict[str, Any]) -> None:
    ENVIADOS.append(registro)


_salida: Salida = _salida_en_memoria


def configurar_salida(salida: Salida | None) -> None:
    """Cambia dónde se registran los envíos (la API usa una lista de Redis)."""
    global _salida
    _salida = salida or _salida_en_memoria


@tool
async def enviar_comunicado(destinatario: str, asunto: str, mensaje: str) -> str:
    """Envía un comunicado a un destinatario (ACCIÓN CON EFECTOS SECUNDARIOS: requiere aprobación humana previa)."""
    registro = {"destinatario": destinatario, "asunto": asunto, "mensaje": mensaje, "ts": time.time()}
    await _salida(registro)
    return f"Comunicado enviado a {destinatario} con asunto «{asunto}»."


EJECUTOR_TOOLS = [enviar_comunicado]
# Herramientas que el sistema considera críticas (efectos secundarios) → exigen aprobación humana.
HERRAMIENTAS_CRITICAS = frozenset(t.name for t in EJECUTOR_TOOLS)


def crear_ejecutor(llm: BaseChatModel):
    return create_agent(llm, EJECUTOR_TOOLS, system_prompt=EJECUTOR_PROMPT, name="ejecutor")
