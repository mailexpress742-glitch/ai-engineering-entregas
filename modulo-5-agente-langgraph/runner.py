"""Ejecución de un turno del agente con traza ReAct (log legible + JSON)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from graph import RECURSION_LIMIT

logger = logging.getLogger("agente")


def _texto(msg: BaseMessage) -> str:
    """Texto plano de un mensaje (los modelos pueden devolver una lista de bloques)."""
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()


def _args(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


@dataclass
class Traza:
    """Registro ordenado de los pasos del ciclo ReAct de uno o más turnos."""

    thread_id: str
    pasos: list[dict[str, Any]] = field(default_factory=list)

    def agregar(self, **evento: Any) -> dict[str, Any]:
        evento = {"paso": len(self.pasos) + 1, **evento}
        self.pasos.append(evento)
        return evento

    def herramientas_usadas(self) -> list[str]:
        return [p["herramienta"] for p in self.pasos if p["tipo"] == "accion"]

    def a_dict(self) -> dict[str, Any]:
        return {"thread_id": self.thread_id, "llamadas_a_herramientas": len(self.herramientas_usadas()),
                "pasos": self.pasos}

    def guardar_json(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(self.a_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def formato_react(self) -> str:
        etiquetas = {"usuario": "Usuario", "pensamiento": "Pensamiento", "accion": "Acción",
                     "observacion": "Observación", "respuesta": "Respuesta", "error": "ERROR"}
        lineas = [f"# thread_id = {self.thread_id}"]
        for p in self.pasos:
            if p["tipo"] == "accion":
                cuerpo = f"{p['herramienta']}({_args(p['argumentos'])})"
            elif p["tipo"] == "observacion":
                cuerpo = f"{p['herramienta']} -> {json.dumps(p['resultado'], ensure_ascii=False)}"
            else:
                cuerpo = p["contenido"]
            lineas.append(f"[{p['paso']:02d}] {etiquetas[p['tipo']]:<12} {cuerpo}")
        return "\n".join(lineas)


async def ejecutar_turno(
    graph: CompiledStateGraph,
    pregunta: str,
    thread_id: str,
    *,
    traza: Traza | None = None,
    recursion_limit: int = RECURSION_LIMIT,
) -> str:
    """Envía ``pregunta`` al agente dentro de la sesión ``thread_id`` y devuelve la respuesta.

    El ``thread_id`` es lo que recupera el historial desde el checkpointer: con el mismo id el
    agente recuerda turnos anteriores (incluso tras reiniciar el proceso). Si el agente excede
    ``recursion_limit`` pasos devuelve un mensaje controlado en vez de fallar.
    """
    traza = traza if traza is not None else Traza(thread_id)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
    logger.info("Usuario: %s", pregunta)
    traza.agregar(tipo="usuario", nodo="usuario", contenido=pregunta)
    inicio = time.perf_counter()
    respuesta = ""
    try:
        async for update in graph.astream(
            {"messages": [HumanMessage(pregunta)]}, config, stream_mode="updates"
        ):
            for nodo, salida in update.items():
                for msg in salida["messages"]:
                    respuesta = _registrar(traza, nodo, msg) or respuesta
    except GraphRecursionError:
        respuesta = (
            f"Me detuve tras {recursion_limit} pasos sin llegar a una respuesta. "
            "¿Podés reformular o dar más datos?"
        )
        logger.error("Límite de recursión alcanzado (%d pasos)", recursion_limit)
        traza.agregar(tipo="error", nodo="grafo", contenido=respuesta)
    logger.info("Turno completado en %.1f s", time.perf_counter() - inicio)
    return respuesta


def _registrar(traza: Traza, nodo: str, msg: BaseMessage) -> str | None:
    """Agrega a la traza lo que produjo un nodo. Devuelve el texto si es la respuesta final."""
    if isinstance(msg, AIMessage):
        texto = _texto(msg)
        if msg.tool_calls:
            if texto:
                logger.info("Pensamiento: %s", texto)
                traza.agregar(tipo="pensamiento", nodo=nodo, contenido=texto)
            for call in msg.tool_calls:
                logger.info("Acción: %s(%s)", call["name"], _args(call["args"]))
                traza.agregar(tipo="accion", nodo=nodo, herramienta=call["name"], argumentos=call["args"])
            return None
        logger.info("Respuesta: %s", texto)
        traza.agregar(tipo="respuesta", nodo=nodo, contenido=texto)
        return texto
    if isinstance(msg, ToolMessage):
        try:
            resultado: Any = json.loads(_texto(msg))
        except json.JSONDecodeError:
            resultado = _texto(msg)
        logger.info("Observación: %s -> %s", msg.name, resultado)
        traza.agregar(tipo="observacion", nodo=nodo, herramienta=msg.name, resultado=resultado)
    return None
