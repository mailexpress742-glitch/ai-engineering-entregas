"""Definición del agente ReAct como un StateGraph de LangGraph.

    START -> agente --(tools_condition)--> tools -> agente -> ... -> END

El nodo ``agente`` llama al LLM con las herramientas enlazadas (``bind_tools``); si el modelo
pide una herramienta, ``tools_condition`` envía el flujo al nodo ``tools`` (que las ejecuta) y
el resultado vuelve al agente. Cuando el modelo responde sin pedir herramientas, termina.
No hay ningún ``if/else`` manual: el modelo decide cuándo usar cada herramienta.
"""

from __future__ import annotations

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, trim_messages
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import TOOLS

# Techo de pasos (nodos ejecutados) por invocación: corta cualquier bucle infinito de herramientas.
# Un ciclo agente->tools son 2 pasos, así que 10 permite ~4 rondas de herramientas.
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "10"))

# El estado se acumula: solo los últimos mensajes viajan al modelo (el historial completo
# sigue guardado en el checkpointer).
MAX_MENSAJES_CONTEXTO = 24

SYSTEM_PROMPT = (
    "Sos un asistente de atención al cliente de una tienda. Respondés en español, de forma "
    "breve y precisa, consultando los datos con tus herramientas.\n"
    "Reglas:\n"
    "- Para cualquier dato de clientes o pedidos usá las herramientas; nunca inventes números, "
    "fechas ni productos.\n"
    "- Podés encadenar varias herramientas: lo que devuelve una puede ser la entrada de otra.\n"
    "- Si una herramienta devuelve un error, leé la `sugerencia`: si es reintentable, volvé a "
    "llamarla; si no, probá otra vía (por ejemplo buscar al cliente por nombre).\n"
    "- Si la consulta es ambigua (varias coincidencias) o falta un dato que no podés obtener, "
    "pedile una aclaración al usuario en lugar de adivinar.\n"
    "- Usá el historial de la conversación para entender referencias como 'ese pedido' o 'el "
    "anterior'.\n"
    "- Los montos están en pesos argentinos; formatealos como $14.500."
)


def recortar_contexto(mensajes: list[BaseMessage]) -> list[BaseMessage]:
    """Se queda con los últimos ``MAX_MENSAJES_CONTEXTO`` mensajes, empezando siempre en un
    mensaje del usuario para no separar una llamada a herramienta de su resultado."""
    return trim_messages(
        mensajes,
        max_tokens=MAX_MENSAJES_CONTEXTO,
        token_counter=len,  # cuenta mensajes, no tokens
        strategy="last",
        start_on="human",
        allow_partial=False,
    )


def build_graph(llm: BaseChatModel, checkpointer=None) -> CompiledStateGraph:
    """Compila el grafo del agente. ``checkpointer`` aporta la memoria por ``thread_id``."""
    llm_con_herramientas = llm.bind_tools(TOOLS)

    async def nodo_agente(state: MessagesState) -> dict[str, list[BaseMessage]]:
        contexto = recortar_contexto(state["messages"])
        respuesta = await llm_con_herramientas.ainvoke([SystemMessage(SYSTEM_PROMPT), *contexto])
        return {"messages": [respuesta]}  # el reducer de MessagesState lo agrega al historial

    builder = StateGraph(MessagesState)
    builder.add_node("agente", nodo_agente)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "agente")
    builder.add_conditional_edges("agente", tools_condition)  # -> "tools" o END
    builder.add_edge("tools", "agente")  # el ciclo: el resultado vuelve al modelo
    return builder.compile(checkpointer=checkpointer)
