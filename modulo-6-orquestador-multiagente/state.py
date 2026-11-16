"""Estado compartido del orquestador.

Todos los nodos leen y escriben este mismo estado. Los campos acumulativos usan el reducer
``operator.add``: cada nodo devuelve solo lo NUEVO y LangGraph lo agrega, de modo que nada se
pisa y siempre se sabe qué agente aportó qué (trazabilidad / procedencia).
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import MessagesState

Agente = Literal["investigador", "analista", "sintetizador"]


class Contribucion(TypedDict):
    """Un aporte de un especialista, con su procedencia."""

    agente: Literal["investigador", "analista"]
    version: int  # 1 = primer intento; 2 = refinamiento pedido por el supervisor
    paso: int  # número de decisión del supervisor que originó este aporte
    instruccion: str  # lo que el supervisor le pidió (y lo único que el especialista recibió)
    contenido: str  # resultado del especialista
    herramientas_usadas: list[str]  # herramientas que ejecutó, en orden
    fuentes: list[str]  # documentos/secciones consultados (investigador)
    fallida: bool  # True si el especialista no pudo completar la tarea (el contenido es solo un aviso)


class RegistroDecision(TypedDict):
    """Una decisión del supervisor y por qué (auditable)."""

    paso: int
    siguiente: Agente
    razon: str
    instruccion: str
    regla_aplicada: str | None  # si una regla de validación corrigió la decisión del modelo


class EstadoOrquestador(MessagesState):
    """Estado del grafo. Hereda ``messages`` (reducer ``add_messages``) de ``MessagesState``."""

    next_agent: Agente  # a quién enrutar a continuación (lo escribe el supervisor)
    instruccion_actual: str  # instrucción específica para el próximo especialista
    pasos: Annotated[int, operator.add]  # decisiones del supervisor (contador anti-bucle)
    contribuciones: Annotated[list[Contribucion], operator.add]  # historial completo de aportes
    decisiones: Annotated[list[RegistroDecision], operator.add]  # historial de decisiones
    advertencias: Annotated[list[str], operator.add]  # límites alcanzados, aportes dudosos, etc.
    task_completed: bool  # True cuando el sintetizador cerró la tarea
    respuesta_final: str


def ultima_contribucion(estado: EstadoOrquestador, agente: str) -> Contribucion | None:
    """Aporte vigente de un agente: la versión más reciente que NO haya fallado.

    Si un refinamiento falla, el aporte válido anterior no se pierde (sigue siendo el vigente).
    Solo si todos los intentos fallaron se devuelve el último (para poder informar el fallo).
    """
    propias = [c for c in estado.get("contribuciones", []) if c["agente"] == agente]
    validas = [c for c in propias if not c.get("fallida")]
    return (validas or propias)[-1] if propias else None


def contribuciones_vigentes(estado: EstadoOrquestador, agente: str) -> list[Contribucion]:
    """TODOS los aportes válidos de un agente, en orden.

    Un refinamiento puede *complementar* (traer un dato que faltaba) y no solo *reemplazar*, así que
    quien consume los aportes (analista, sintetizador) recibe el conjunto completo y no solo el último.
    Si todos los intentos fallaron devuelve el último, para poder informar el fallo.
    """
    propias = [c for c in estado.get("contribuciones", []) if c["agente"] == agente]
    validas = [c for c in propias if not c.get("fallida")]
    return validas or propias[-1:]


def texto_de_aportes(aportes: list[Contribucion]) -> str:
    """Aportes numerados por versión (con sus fuentes), listos para pasarlos a otro agente."""
    return "\n\n".join(
        f"[aporte v{c['version']}] (fuentes: {', '.join(c['fuentes']) or 'ninguna'})\n{c['contenido']}" for c in aportes
    )


def consulta_original(estado: EstadoOrquestador) -> str:
    """Primer mensaje del usuario: la solicitud que hay que resolver."""
    for m in estado["messages"]:
        if m.type == "human":
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""
