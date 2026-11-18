"""Agente ejecutor: realiza acciones con **efectos secundarios** (responder al cliente, escalar a un área).

Es el único agente cuyas herramientas cambian el mundo exterior, por eso el grafo lo protege con una
aprobación humana obligatoria (``hitl.py``): el supervisor nunca llega acá sin pasar por el nodo
``aprobacion``. El envío es simulado (no sale ningún mail real): queda registrado en una "bandeja de
salida" que la API persiste en Redis y sirve para comprobar que, sin aprobación, la acción NO ocurre.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool

from app.schemas import EnvioRegistrado, EscalamientoIn, RespuestaClienteIn

EJECUTOR_PROMPT = (
    "Sos el EJECUTOR de la mesa de reclamos de MailEx. Ya te aprobaron una acción: tu tarea es llevarla a cabo "
    "con tus herramientas, UNA sola vez cada una:\n"
    "- `responder_cliente`: redacta y envía la respuesta al cliente. Basate en la plantilla de la base de "
    "conocimiento que te pasan (completá todos los campos con los datos reales de la pieza; no dejes llaves "
    "`{}` sin completar) y no prometas nada que no figure en los datos.\n"
    "- `escalar_caso`: deriva el caso al área que corresponde con su prioridad. Usalo solo si la instrucción "
    "o los datos indican que hay que escalar.\n"
    "El DIAGNÓSTICO del analista manda sobre la instrucción del supervisor: si se contradicen (por ejemplo, el "
    "analista dice que el plazo está VENCIDO), seguí al analista y elegí la plantilla que corresponde a ese "
    "diagnóstico; nunca uses la variante «dentro del plazo» para una pieza vencida.\n"
    "Reglas estrictas: usá el texto de la plantilla casi literal y completá solo sus campos; NO agregues "
    "compromisos ni acciones que la plantilla no contenga (por ejemplo «reentrega inmediata» o fechas "
    "prometidas); mencioná solo el escalamiento que realmente hacés y nunca la palabra «prioridad» al cliente. "
    "La prioridad del escalamiento es una de: baja, media, alta, urgente (nunca «normal»). Usá "
    "EXCLUSIVAMENTE los datos y cifras que te pasan; no inventes nada. Cuando termines, respondé en una o "
    "dos líneas qué acciones realizaste."
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


async def responder_cliente(pieza_id: str, destinatario: str, asunto: str, mensaje: str) -> str:
    """Envía la respuesta al cliente (ACCIÓN CON EFECTOS SECUNDARIOS: requiere aprobación humana previa)."""
    e = RespuestaClienteIn(pieza_id=pieza_id, destinatario=destinatario, asunto=asunto, mensaje=mensaje)
    if "{" in e.mensaje or "}" in e.mensaje:
        return "Error: el mensaje tiene campos de la plantilla sin completar ({...}). Completalos y volvé a enviar."
    registro = EnvioRegistrado(
        tipo="respuesta_cliente", pieza_id=e.pieza_id, ts=time.time(),
        detalle={"destinatario": e.destinatario, "asunto": e.asunto, "mensaje": e.mensaje},
    )
    await _salida(registro.model_dump(mode="json"))
    return f"Respuesta enviada a {e.destinatario} sobre {e.pieza_id} con asunto «{e.asunto}»."


async def escalar_caso(pieza_id: str, area: str, prioridad: str, resumen: str) -> str:
    """Escala el caso a un área interna (ACCIÓN CON EFECTOS SECUNDARIOS: requiere aprobación humana previa)."""
    e = EscalamientoIn(pieza_id=pieza_id, area=area, prioridad=prioridad, resumen=resumen)  # type: ignore[arg-type]
    registro = EnvioRegistrado(
        tipo="escalamiento", pieza_id=e.pieza_id, ts=time.time(),
        detalle={"area": e.area, "prioridad": e.prioridad, "resumen": e.resumen},
    )
    await _salida(registro.model_dump(mode="json"))
    return f"Caso {e.pieza_id} escalado a {e.area} con prioridad {e.prioridad}."


def crear_herramientas_ejecutor() -> list[BaseTool]:
    return [
        StructuredTool.from_function(coroutine=responder_cliente, name="responder_cliente", args_schema=RespuestaClienteIn),
        StructuredTool.from_function(coroutine=escalar_caso, name="escalar_caso", args_schema=EscalamientoIn),
    ]


# Herramientas que el sistema considera críticas (efectos secundarios) → exigen aprobación humana.
HERRAMIENTAS_CRITICAS = frozenset({"responder_cliente", "escalar_caso"})


def crear_ejecutor(llm: BaseChatModel):
    return create_agent(llm, crear_herramientas_ejecutor(), system_prompt=EJECUTOR_PROMPT, name="ejecutor")
