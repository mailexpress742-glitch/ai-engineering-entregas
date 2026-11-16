"""Grafo del orquestador multi-agente (topología jerárquica con supervisor).

                    ┌───────────────┐
        START ────► │  supervisor   │ ◄──────────────┐
                    └───────┬───────┘                │
        (arista condicional, devuelve un Literal)    │
            ┌───────────────┼────────────────┐       │
            ▼               ▼                ▼       │
      investigador       analista       sintetizador │
            │               │                │       │
            └───────────────┴────────────────┼───────┘ (vuelven al supervisor)
                                             ▼
                                            END
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents import crear_analista, crear_ejecutor, crear_investigador
from app.agents.base import Especialista, ejecutar_especialista, texto
from app.state import Contribucion, EstadoOrquestador, consulta_original, contribuciones_vigentes, texto_de_aportes
from app.hitl import nodo_aprobacion
from app.supervisor import Decidir, crear_decisor_llm, crear_nodo_supervisor

logger = logging.getLogger("orquestador")

# Techo de pasos del grafo (supersteps). Con MAX_PASOS=6 decisiones del supervisor el flujo más
# largo posible usa ~13; 25 deja margen sin permitir bucles de costo ilimitado.
RECURSION_LIMIT = 25

Ruta = Literal["investigador", "analista", "aprobacion", "sintetizador"]
Sintetizar = Callable[[EstadoOrquestador], Awaitable[str]]

SINTETIZADOR_PROMPT = (
    "Sos el SINTETIZADOR de un equipo. Redactá la respuesta final a la solicitud del usuario usando "
    "EXCLUSIVAMENTE los aportes del investigador y del analista que te paso.\n"
    "- Respondé en español, de forma clara y completa pero breve.\n"
    "- NO calcules ni corrijas nada: usá EXACTAMENTE las cifras del analista y los datos del "
    "investigador. Vos solo redactás.\n"
    "- Citá las fuentes (archivo#sección) de los datos y mostrá cómo se calculó cada cifra, "
    "atribuyendo cada parte a quien la aportó: los datos al «investigador» y los cálculos al "
    "«analista». Nunca te atribuyas cálculos ni datos.\n"
    "- Si hubo una acción (comunicado), indicá que la realizó el «ejecutor» tras la aprobación humana; "
    "si un humano la rechazó, decí claramente que NO se realizó.\n"
    "- Si los aportes se contradicen entre sí o con la solicitud, señalalo explícitamente en vez de "
    "elegir uno en silencio.\n"
    "- No agregues datos que no estén en los aportes. Si hay advertencias o falta algo, aclaralo "
    "al final en una línea."
)


# ------------------------------------------------------------------- enrutamiento
def enrutar(estado: EstadoOrquestador) -> Ruta:
    """Arista condicional del supervisor. El ``Literal`` del retorno son los nombres de nodo válidos."""
    siguiente = estado["next_agent"]
    # La acción con efectos secundarios NUNCA va directo al ejecutor: pasa por la aprobación humana.
    return "aprobacion" if siguiente == "ejecutor" else siguiente  # type: ignore[return-value]


# ------------------------------------------------------------ nodos especialistas
def _entrada_investigador(estado: EstadoOrquestador) -> str:
    return estado["instruccion_actual"]  # solo la instrucción: sin historial


def _entrada_ejecutor(estado: EstadoOrquestador) -> str:
    """Instrucción + los datos y cálculos vigentes (lo único que el ejecutor necesita)."""
    aportes = [c for ag in ("investigador", "analista") for c in contribuciones_vigentes(estado, ag)]
    return f"{estado['instruccion_actual']}\n\nDATOS Y CÁLCULOS:\n{texto_de_aportes(aportes) if aportes else '(sin datos)'}"


def _entrada_analista(estado: EstadoOrquestador) -> str:
    """Instrucción + únicamente los datos que el analista necesita: los aportes válidos del investigador."""
    aportes = contribuciones_vigentes(estado, "investigador")
    datos = texto_de_aportes(aportes) if aportes else "(sin datos)"
    return f"{estado['instruccion_actual']}\n\nDATOS DEL INVESTIGADOR:\n{datos}"


def _crear_nodo_especialista(
    nombre: Literal["investigador", "analista", "ejecutor"],
    ejecutar: Especialista,
    construir_entrada: Callable[[EstadoOrquestador], str],
):
    async def nodo(estado: EstadoOrquestador) -> dict[str, Any]:
        entrada = construir_entrada(estado)
        previas = sum(c["agente"] == nombre for c in estado.get("contribuciones", []))
        advertencias: list[str] = []
        fallida = False
        try:
            res = await ejecutar(entrada)
        except Exception as exc:  # noqa: BLE001 - un especialista caído no tumba el sistema
            logger.error("%s falló: %s: %s", nombre, type(exc).__name__, exc)
            res = {"contenido": f"[El {nombre} no pudo completar la tarea: {type(exc).__name__}]",
                   "herramientas_usadas": [], "fuentes": []}
            fallida = True
            advertencias.append(f"El {nombre} falló en su intento v{previas + 1} ({type(exc).__name__}).")
        contribucion: Contribucion = {
            "agente": nombre,
            "version": previas + 1,
            "paso": estado.get("pasos", 0),
            "instruccion": estado["instruccion_actual"],
            "contenido": res["contenido"],
            "herramientas_usadas": res["herramientas_usadas"],
            "fuentes": res["fuentes"],
            "fallida": fallida,
        }
        logger.info("%s v%d: herramientas=%s", nombre, contribucion["version"], res["herramientas_usadas"])
        return {
            "contribuciones": [contribucion],
            "messages": [AIMessage(content=res["contenido"], name=nombre)],  # historial compartido legible
            "advertencias": advertencias,
        }

    return nodo


# ---------------------------------------------------------------- sintetizador
def crear_sintetizador_llm(llm: BaseChatModel) -> Sintetizar:
    async def sintetizar(estado: EstadoOrquestador) -> str:
        partes = [f"SOLICITUD DEL USUARIO:\n{consulta_original(estado)}\n"]
        for agente in ("investigador", "analista", "ejecutor"):
            aportes = contribuciones_vigentes(estado, agente)
            if aportes:
                partes.append(f"APORTES DEL {agente.upper()}:\n{texto_de_aportes(aportes)}\n")
        if estado.get("advertencias"):
            partes.append("ADVERTENCIAS: " + " | ".join(estado["advertencias"]))
        resp = await llm.ainvoke([SystemMessage(SINTETIZADOR_PROMPT), HumanMessage("\n".join(partes))])
        return texto(resp)

    return sintetizar


def _crear_nodo_sintetizador(sintetizar: Sintetizar):
    async def nodo(estado: EstadoOrquestador) -> dict[str, Any]:
        try:
            final = await sintetizar(estado)
        except Exception as exc:  # noqa: BLE001
            logger.error("El sintetizador falló: %s", exc)
            final = "No pude redactar la síntesis final. Aportes disponibles:\n" + "\n".join(
                f"- {c['agente']}: {c['contenido']}" for c in estado.get("contribuciones", [])
            )
        return {
            "respuesta_final": final,
            "task_completed": True,
            "messages": [AIMessage(content=final, name="sintetizador")],
        }

    return nodo


# ---------------------------------------------------------------------- grafo
def build_graph(
    llm: BaseChatModel | None = None,
    *,
    decidir: Decidir | None = None,
    investigador: Especialista | None = None,
    analista: Especialista | None = None,
    ejecutor: Especialista | None = None,
    sintetizar: Sintetizar | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compila el orquestador. Con ``llm`` arma los agentes reales; cada pieza puede reemplazarse
    por una implementación propia (así el grafo se prueba sin red)."""
    if llm is not None:
        decidir = decidir or crear_decisor_llm(llm)
        if investigador is None:
            agente_inv = crear_investigador(llm)
            investigador = lambda entrada: ejecutar_especialista(agente_inv, entrada)  # noqa: E731
        if analista is None:
            agente_ana = crear_analista(llm)
            analista = lambda entrada: ejecutar_especialista(agente_ana, entrada)  # noqa: E731
        if ejecutor is None:
            agente_eje = crear_ejecutor(llm)
            ejecutor = lambda entrada: ejecutar_especialista(agente_eje, entrada)  # noqa: E731
        sintetizar = sintetizar or crear_sintetizador_llm(llm)
    if not (decidir and investigador and analista and sintetizar):
        raise ValueError("Pasá un llm o las piezas (decidir, investigador, analista, sintetizar).")
    if ejecutor is None:  # sin acciones configuradas: el ejecutor existe pero no hace nada

        async def ejecutor(entrada: str):  # type: ignore[misc]
            return {"contenido": "(ejecutor sin acciones configuradas)", "herramientas_usadas": [], "fuentes": []}

    builder = StateGraph(EstadoOrquestador)
    builder.add_node("supervisor", crear_nodo_supervisor(decidir))
    builder.add_node("investigador", _crear_nodo_especialista("investigador", investigador, _entrada_investigador))
    builder.add_node("analista", _crear_nodo_especialista("analista", analista, _entrada_analista))
    builder.add_node("aprobacion", nodo_aprobacion)  # human-in-the-loop (interrupt)
    builder.add_node("ejecutor", _crear_nodo_especialista("ejecutor", ejecutor, _entrada_ejecutor))
    builder.add_node("sintetizador", _crear_nodo_sintetizador(sintetizar))

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", enrutar)  # supervisor -> investigador | analista | sintetizador
    builder.add_edge("investigador", "supervisor")  # los especialistas siempre devuelven el control
    builder.add_edge("analista", "supervisor")
    builder.add_edge("ejecutor", "supervisor")  # "aprobacion" decide con Command(goto=...) si va a ejecutor o vuelve
    builder.add_edge("sintetizador", END)
    return builder.compile(checkpointer=checkpointer)


def mermaid(graph: CompiledStateGraph) -> str:
    """Diagrama Mermaid del grafo compilado (el mismo que se incluye en el README)."""
    return graph.get_graph().draw_mermaid()
