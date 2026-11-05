"""Tests sin red ni API keys: el LLM se reemplaza por un modelo con guion."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

import tools
from graph import MAX_MENSAJES_CONTEXTO, build_graph, recortar_contexto
from runner import Traza, ejecutar_turno

_n = 0


def llamada(nombre: str, **args: Any) -> AIMessage:
    """Mensaje del 'LLM' que pide ejecutar una herramienta."""
    global _n
    _n += 1
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": args, "id": f"call_{_n}", "type": "tool_call"}])


class ModeloConGuion(BaseChatModel):
    """Chat model falso: responde con los mensajes del guion, en orden, y recuerda lo que vio."""

    guion: list[Any]
    vistos: list[Any] = Field(default_factory=list)
    llamadas: int = 0

    @property
    def _llm_type(self) -> str:
        return "guion"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ModeloConGuion:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.vistos.append(list(messages))
        base = self.guion[min(self.llamadas, len(self.guion) - 1)]
        self.llamadas += 1
        # Un LLM real devuelve un mensaje NUEVO en cada llamada. Si se reutilizara el mismo objeto,
        # el reducer (add_messages) lo tomaría por una actualización del mensaje ya guardado.
        msg = base.model_copy(
            update={
                "id": None,
                "tool_calls": [{**c, "id": f"call_{self.llamadas}"} for c in base.tool_calls],
            }
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture(autouse=True)
def _reiniciar_fallos():
    tools.reset_fallos()


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "memoria.sqlite")


# ---------------------------------------------------------------- herramientas
async def test_buscar_pedidos_resume_cantidad_y_total():
    r = await tools.buscar_pedidos.ainvoke({"cliente_id": 102})
    assert r["pedidos"] == 3 and r["total"] == 14500
    assert r["ids_pedidos"][-1]["id"] == "P-1013"  # ordenados: el último es el más reciente


async def test_los_pedidos_cancelados_no_suman():
    r = await tools.buscar_pedidos.ainvoke({"cliente_id": 103})
    assert r["pedidos"] == 1 and r["total"] == 8300


async def test_cliente_inexistente_devuelve_error_con_sugerencia():
    r = await tools.buscar_pedidos.ainvoke({"cliente_id": 999})
    assert "error" in r and "buscar_cliente" in r["sugerencia"]


async def test_buscar_cliente_ambiguo_y_sin_tildes():
    r = await tools.buscar_cliente.ainvoke({"nombre": "lucia"})
    assert len(r["coincidencias"]) == 2
    r = await tools.buscar_cliente.ainvoke({"nombre": "MARTIN"})
    assert r["coincidencias"][0]["cliente_id"] == 102


async def test_detalle_inestable_falla_una_vez_y_luego_responde():
    primero = await tools.detalle_pedido.ainvoke({"pedido_id": "P-1019"})
    assert primero["error"] and primero["reintentable"] is True
    segundo = await tools.detalle_pedido.ainvoke({"pedido_id": "P-1019"})
    assert "error" not in segundo and "Auriculares" in segundo["items"]


async def test_detalle_con_formato_invalido_o_inexistente():
    assert "formato" in (await tools.detalle_pedido.ainvoke({"pedido_id": "abc"}))["error"]
    assert "reintentable" not in await tools.detalle_pedido.ainvoke({"pedido_id": "P-9999"})


def test_docstrings_descriptivos_para_el_llm():
    for t in tools.TOOLS:
        assert len(t.description) > 200, t.name  # el LLM decide solo con esto
        assert "Devuelve" in t.description


# ----------------------------------------------------------------------- grafo
def test_estructura_del_grafo():
    g = build_graph(ModeloConGuion(guion=[AIMessage(content="hola")])).get_graph()
    assert {"agente", "tools"} <= set(g.nodes)
    desde_agente = [e for e in g.edges if e.source == "agente"]
    assert any(e.conditional for e in desde_agente)  # arista condicional (tools_condition)
    assert any(e.source == "tools" and e.target == "agente" for e in g.edges)  # el ciclo


async def test_responde_sin_herramientas_si_no_hacen_falta(db):
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(ModeloConGuion(guion=[AIMessage(content="¡Hola! ¿En qué te ayudo?")]), saver)
        traza = Traza("t")
        assert "Hola" in await ejecutar_turno(graph, "hola", "t", traza=traza)
        assert traza.herramientas_usadas() == []  # el agente decidió solo: no llamó herramientas


async def test_razonamiento_multipaso_llama_dos_herramientas(db):
    guion = [
        llamada("buscar_pedidos", cliente_id=102),
        llamada("detalle_pedido", pedido_id="P-1013"),
        AIMessage(content="El cliente 102 tuvo 3 pedidos por $14.500; el último incluyó un monitor."),
    ]
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(ModeloConGuion(guion=guion), saver)
        traza = Traza("t")
        resp = await ejecutar_turno(graph, "¿pedidos del 102 y qué incluyó el último?", "t", traza=traza)
    assert traza.herramientas_usadas() == ["buscar_pedidos", "detalle_pedido"]
    assert "14.500" in resp
    obs = [p for p in traza.pasos if p["tipo"] == "observacion"]
    assert obs[0]["resultado"]["total"] == 14500  # la observación llega al modelo y vuelve a la traza


async def test_ciclo_de_retorno_reintenta_tras_un_error(db):
    guion = [
        llamada("detalle_pedido", pedido_id="P-1019"),  # falla (timeout simulado)
        llamada("detalle_pedido", pedido_id="P-1019"),  # el modelo ve el error y reintenta
        AIMessage(content="Incluyó auriculares y una webcam."),
    ]
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(ModeloConGuion(guion=guion), saver)
        traza = Traza("t")
        await ejecutar_turno(graph, "¿qué incluyó P-1019?", "t", traza=traza)
    obs = [p["resultado"] for p in traza.pasos if p["tipo"] == "observacion"]
    assert "error" in obs[0] and "error" not in obs[1]


async def test_el_modelo_recibe_el_resultado_de_la_herramienta(db):
    modelo = ModeloConGuion(guion=[llamada("buscar_pedidos", cliente_id=102), AIMessage(content="listo")])
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        await ejecutar_turno(build_graph(modelo, saver), "pedidos del 102", "t")
    segunda_vista = modelo.vistos[1]
    assert any(isinstance(m, ToolMessage) and "14500" in str(m.content) for m in segunda_vista)


# ------------------------------------------------------------------ persistencia
async def test_memoria_por_thread_id(db):
    modelo = ModeloConGuion(guion=[AIMessage(content="uno"), AIMessage(content="dos")])
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(modelo, saver)
        await ejecutar_turno(graph, "mi cliente es el 102", "sesion-a")
        await ejecutar_turno(graph, "¿y el último?", "sesion-a")
    vistos = [m.content for m in modelo.vistos[1] if isinstance(m, HumanMessage)]
    assert vistos == ["mi cliente es el 102", "¿y el último?"]  # recuerda el turno anterior


async def test_otro_thread_id_no_comparte_memoria(db):
    modelo = ModeloConGuion(guion=[AIMessage(content="uno"), AIMessage(content="dos")])
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(modelo, saver)
        await ejecutar_turno(graph, "mi cliente es el 102", "sesion-a")
        await ejecutar_turno(graph, "¿y el último?", "sesion-b")
    assert [m.content for m in modelo.vistos[1] if isinstance(m, HumanMessage)] == ["¿y el último?"]


async def test_la_memoria_sobrevive_a_reiniciar_el_proceso(db):
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        await ejecutar_turno(build_graph(ModeloConGuion(guion=[AIMessage(content="ok")]), saver), "dato: 102", "s")
    # "proceso nuevo": otro saver, otro grafo, otro modelo, mismo archivo y mismo thread_id
    modelo = ModeloConGuion(guion=[AIMessage(content="ok")])
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        await ejecutar_turno(build_graph(modelo, saver), "¿qué dato te di?", "s")
    assert "dato: 102" in [m.content for m in modelo.vistos[0] if isinstance(m, HumanMessage)]


# ---------------------------------------------------------------- límites/estado
async def test_recursion_limit_corta_un_bucle_infinito(db):
    bucle = ModeloConGuion(guion=[llamada("buscar_pedidos", cliente_id=102)])  # siempre pide lo mismo
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        traza = Traza("t")
        resp = await ejecutar_turno(build_graph(bucle, saver), "x", "t", traza=traza, recursion_limit=5)
    assert "5 pasos" in resp and traza.pasos[-1]["tipo"] == "error"
    assert bucle.llamadas <= 4  # se cortó; no siguió llamando al LLM


def test_recortar_contexto_limita_y_no_separa_herramienta_de_resultado():
    msgs: list[Any] = []
    for i in range(30):
        msgs += [HumanMessage(f"pregunta {i}"), llamada("buscar_pedidos", cliente_id=102),
                 ToolMessage("{}", tool_call_id=f"x{i}", name="buscar_pedidos"), AIMessage(content=f"r{i}")]
    # (los ids de llamada y de resultado no coinciden: solo importa la forma del recorte)
    recortado = recortar_contexto(msgs)
    assert len(recortado) <= MAX_MENSAJES_CONTEXTO and isinstance(recortado[0], HumanMessage)
    assert recortado[-1].content == "r29"
