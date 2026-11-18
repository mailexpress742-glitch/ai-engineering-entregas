"""Utilidades comunes a los especialistas: ejecución aislada y extracción de resultados."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class ResultadoEspecialista(TypedDict):
    contenido: str
    herramientas_usadas: list[str]
    fuentes: list[str]


# Firma de un especialista dentro del grafo: recibe SOLO la entrada acotada (instrucción +
# contexto necesario) y devuelve su resultado. Es el punto de inyección para los tests.
Especialista = Callable[[str], Awaitable[ResultadoEspecialista]]


def texto(msg: Any) -> str:
    c = msg.content
    if isinstance(c, str):
        return c.strip()
    return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text").strip()


async def ejecutar_especialista(agente: Any, entrada: str, *, recursion_limit: int = 30) -> ResultadoEspecialista:
    """Corre un agente ReAct con un historial NUEVO que contiene solo ``entrada``.

    Así el especialista no hereda la conversación completa del sistema (contaminación de
    contexto): recibe la instrucción específica y los datos que necesita, nada más.
    """
    salida = await agente.ainvoke(
        {"messages": [HumanMessage(entrada)]}, {"recursion_limit": recursion_limit}
    )
    mensajes = salida["messages"]
    usadas = [m.name for m in mensajes if isinstance(m, ToolMessage) and m.name]
    recuperadas: list[str] = []
    for m in mensajes:
        if isinstance(m, ToolMessage) and m.name == "buscar_conocimiento":
            for f in _fuentes_de(texto(m)):
                if f not in recuperadas:
                    recuperadas.append(f)
    finales = [m for m in mensajes if isinstance(m, AIMessage) and not m.tool_calls]
    contenido = texto(finales[-1]) if finales else ""
    return {
        "contenido": contenido,
        "herramientas_usadas": usadas,
        "fuentes": fuentes_citadas(contenido, recuperadas),
    }


def fuentes_citadas(contenido: str, recuperadas: list[str]) -> list[str]:
    """Fuentes que el especialista REALMENTE cita en su respuesta (no todo lo que devolvió la búsqueda).

    La búsqueda devuelve varias secciones por consulta y la mayoría no se usa; contarlas todas como
    "fuentes" ensuciaría la procedencia. Si el texto no cita ninguna con el formato ``archivo#sección``,
    se conservan las 3 primeras recuperadas (las más relevantes según el buscador) para no perder la
    trazabilidad sin inflarla.
    """
    citadas = [f for f in recuperadas if f in contenido]
    return citadas or recuperadas[:3]


def _fuentes_de(resultado_herramienta: str) -> list[str]:
    try:
        datos = json.loads(resultado_herramienta)
    except json.JSONDecodeError:
        return re.findall(r"[\w.-]+\.md#[^\s\"',]+", resultado_herramienta)
    return [f"{r['fuente']}#{r['seccion']}" for r in datos.get("resultados", [])]
