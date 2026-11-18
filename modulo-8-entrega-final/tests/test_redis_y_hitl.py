"""Checkpointer de Redis y flujo human-in-the-loop sobre el grafo real (sin LLM, con fakeredis)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agents import action_agent
from tests.conftest import grafo_con_redis

CONSULTA = {"messages": [HumanMessage("Calculá las actualizaciones de un SEV1 y avisá a la guardia.")]}
FLUJO_CON_ACCION = [
    ("investigador", "buscá datos"), ("analista", "calculá"), ("ejecutor", "avisá a la guardia"), ("sintetizador", ""),
]


def cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}, "recursion_limit": 25}


async def test_el_grafo_se_pausa_en_la_aprobacion_y_no_ejecuta_la_accion(redis_factory):
    graph = grafo_con_redis(redis_factory, *FLUJO_CON_ACCION)
    await graph.ainvoke(CONSULTA, cfg("t1"))

    snap = await graph.aget_state(cfg("t1"))
    assert snap.next == ("aprobacion",)  # pausado, esperando input externo
    interrupciones = [i for t in snap.tasks for i in t.interrupts]
    assert interrupciones and interrupciones[0].value["tipo"] == "aprobacion_requerida"
    assert "guardia" in interrupciones[0].value["accion_propuesta"]
    assert action_agent.ENVIADOS == []  # el efecto secundario NO ocurrió


async def test_aprobar_reanuda_desde_redis_y_ejecuta_la_accion(redis_factory):
    await grafo_con_redis(redis_factory, *FLUJO_CON_ACCION).ainvoke(CONSULTA, cfg("t2"))

    # Grafo NUEVO con cliente Redis NUEVO: simula un reinicio del proceso. El estado vive solo en Redis.
    # (El supervisor de guion es de proceso; uno real no tiene memoria propia: decide mirando el estado.)
    otro = grafo_con_redis(redis_factory, ("sintetizador", ""))
    final = await otro.ainvoke(Command(resume={"aprobado": True, "comentario": "ok"}), cfg("t2"))

    assert len(action_agent.ENVIADOS) == 1
    assert final["task_completed"] and final["aprobacion"] == {"aprobado": True, "comentario": "ok"}
    assert [c["agente"] for c in final["contribuciones"]] == ["investigador", "analista", "ejecutor"]
    assert not final.get("accion_rechazada")


async def test_rechazar_no_ejecuta_y_el_supervisor_cierra_informando(redis_factory):
    # El supervisor "obstinado" insiste en ejecutar; la regla R5 lo corta tras el rechazo.
    flujo = [("investigador", ""), ("analista", ""), ("ejecutor", "avisá"), ("ejecutor", "avisá de nuevo"), ("sintetizador", "")]
    graph = grafo_con_redis(redis_factory, *flujo)
    await graph.ainvoke(CONSULTA, cfg("t3"))
    final = await graph.ainvoke(Command(resume={"aprobado": False, "comentario": "no es el momento"}), cfg("t3"))

    assert action_agent.ENVIADOS == []
    assert final["accion_rechazada"] and final["task_completed"]
    assert any("RECHAZÓ" in a and "no es el momento" in a for a in final["advertencias"])
    assert "R5_accion_no_repetible" in [d["regla_aplicada"] for d in final["decisiones"]]


async def test_el_ejecutor_no_se_alcanza_sin_pasar_por_la_aprobacion(redis_factory):
    graph = grafo_con_redis(redis_factory, *FLUJO_CON_ACCION)
    aristas = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("supervisor", "ejecutor") not in aristas  # no hay camino directo
    assert ("aprobacion", "ejecutor") in aristas


async def test_ejecutor_sin_datos_previos_redirige_al_investigador(redis_factory):
    graph = grafo_con_redis(redis_factory, ("ejecutor", "avisá"), ("sintetizador", ""))
    await graph.ainvoke(CONSULTA, cfg("t4"))
    snap = await graph.aget_state(cfg("t4"))
    assert snap.next != ("aprobacion",) or action_agent.ENVIADOS == []  # nunca se ejecutó nada
    reglas = [d["regla_aplicada"] for d in snap.values["decisiones"]]
    assert "R5_accion_sin_datos" in reglas


async def test_los_checkpoints_quedan_en_redis_y_se_pueden_listar(redis_factory, servidor_redis):
    graph = grafo_con_redis(redis_factory, ("investigador", ""), ("analista", ""), ("sintetizador", ""))
    await graph.ainvoke(CONSULTA, cfg("t5"))

    claves = [k.decode() for k in await redis_factory(False).keys("lg:*")]
    assert any(k.startswith("lg:ck:t5:") for k in claves) and any(k.startswith("lg:bl:t5:") for k in claves)
    historial = [s async for s in graph.aget_state_history(cfg("t5"))]
    assert len(historial) >= 5  # un checkpoint por superstep
    assert historial[0].values["task_completed"] is True


async def test_hilos_distintos_estan_aislados_y_se_pueden_borrar(redis_factory):
    graph = grafo_con_redis(redis_factory, ("investigador", ""), ("analista", ""), ("sintetizador", ""))
    await graph.ainvoke(CONSULTA, cfg("a"))
    assert (await graph.aget_state(cfg("b"))).values == {}
    await graph.checkpointer.adelete_thread("a")
    assert (await graph.aget_state(cfg("a"))).values == {}


async def test_modo_reclamos_no_se_cierra_sin_proponer_la_accion(redis_factory):
    """R6: con exigir_accion=True el supervisor no puede cerrar sin pasar por la aprobación (el cliente siempre recibe respuesta)."""
    graph = grafo_con_redis(redis_factory, ("investigador", ""), ("analista", ""), ("sintetizador", ""), exigir_accion=True)
    await graph.ainvoke(CONSULTA, cfg("r6"))
    snap = await graph.aget_state(cfg("r6"))
    assert snap.next == ("aprobacion",)  # el supervisor quiso cerrar, pero R6 lo mandó al ejecutor (vía aprobación)
    assert "R6_cierre_sin_accion" in [d["regla_aplicada"] for d in snap.values["decisiones"]]
    assert action_agent.ENVIADOS == []


async def test_modo_reclamos_el_rechazo_cuenta_como_accion_resuelta(redis_factory):
    graph = grafo_con_redis(redis_factory, ("investigador", ""), ("analista", ""), ("ejecutor", "respondé"), ("sintetizador", ""), exigir_accion=True)
    await graph.ainvoke(CONSULTA, cfg("r6b"))
    final = await graph.ainvoke(Command(resume={"aprobado": False, "comentario": "lo hago a mano"}), cfg("r6b"))
    assert final["task_completed"] and action_agent.ENVIADOS == [] and "R6_cierre_sin_accion" not in [d["regla_aplicada"] for d in final["decisiones"]]


async def test_un_supervisor_que_insiste_con_el_investigador_no_se_salta_el_analisis_ni_la_accion(redis_factory):
    """Regresión real: investigador 2 veces → R3 cerraba sin diagnóstico ni acción. Ahora R3 avanza al paso que falta."""
    graph = grafo_con_redis(
        redis_factory, ("investigador", ""), ("investigador", "otra vez"), ("investigador", "y otra"), ("sintetizador", ""),
        exigir_accion=True,
    )
    await graph.ainvoke(CONSULTA, cfg("r3"))
    snap = await graph.aget_state(cfg("r3"))
    flujo = [d["siguiente"] for d in snap.values["decisiones"]]
    assert flujo[:4] == ["investigador", "investigador", "analista", "ejecutor"], flujo
    assert snap.next == ("aprobacion",)  # y termina pidiendo la aprobación humana, no cerrando en falso
    assert "R3_limite_de_refinamientos" in [d["regla_aplicada"] for d in snap.values["decisiones"]]
