"""Tests sin red ni API keys: supervisor y especialistas se reemplazan por piezas con guion."""

from __future__ import annotations

from typing import Any, Literal, get_args, get_type_hints

import pytest
from langgraph.graph import MessagesState

import app.supervisor as sup
from app.graph import build_graph, enrutar, mermaid
from app.runner import ejecutar
from app.agents.base import fuentes_citadas
from app.state import EstadoOrquestador, contribuciones_vigentes, texto_de_aportes, ultima_contribucion
from app.supervisor import DecisionLLM

CONSULTA = "¿Cuántas actualizaciones en un SEV1? TOKEN_SOLO_DEL_USUARIO"


# ---------------------------------------------------------------------- helpers
def guion_supervisor(*decisiones: tuple[str, str]):
    """Supervisor falso: devuelve (siguiente, instruccion) en orden; repite la última al agotarse."""
    estado = {"i": 0}

    async def decidir(_estado: Any) -> DecisionLLM:
        sig, instr = decisiones[min(estado["i"], len(decisiones) - 1)]
        estado["i"] += 1
        return DecisionLLM(razon=f"decisión {estado['i']}", siguiente=sig, instruccion=instr)  # type: ignore[arg-type]

    return decidir


def especialista(*respuestas: dict[str, Any]):
    """Especialista falso: devuelve cada respuesta en orden (repite la última) y registra sus entradas."""
    entradas: list[str] = []

    async def correr(entrada: str) -> dict[str, Any]:
        entradas.append(entrada)
        return respuestas[min(len(entradas) - 1, len(respuestas) - 1)]

    correr.entradas = entradas  # type: ignore[attr-defined]
    return correr


INV_OK = {"contenido": "SEV1: 5 min, update cada 15 min. RTO 2 h.", "herramientas_usadas": ["buscar_conocimiento"],
          "fuentes": ["02_respuesta_a_incidentes.md#2. Niveles de severidad"]}
INV_SIN_FUENTES = {"contenido": "Creo que SEV1 es 5 min.", "herramientas_usadas": [], "fuentes": []}
ANA_OK = {"contenido": "120 / 15 = 8 actualizaciones.", "herramientas_usadas": ["calcular"], "fuentes": []}
ANA_SIN_TOOLS = {"contenido": "Serían unas 8.", "herramientas_usadas": [], "fuentes": []}


async def sintetizar_ok(_estado: Any) -> str:
    return "RESPUESTA FINAL"


def armar(decidir, inv=None, ana=None):
    inv = inv or especialista(INV_OK)
    ana = ana or especialista(ANA_OK)
    return build_graph(decidir=decidir, investigador=inv, analista=ana, sintetizar=sintetizar_ok), inv, ana


FLUJO_FELIZ = [("investigador", "buscá severidades"), ("analista", "calculá updates"), ("sintetizador", "")]


# ----------------------------------------------------------------- flujo y estado
async def test_flujo_delegacion_completo():
    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ))
    estado, traza = await ejecutar(graph, CONSULTA)
    assert traza.flujo() == ["supervisor", "investigador", "supervisor", "analista", "supervisor", "sintetizador"]
    assert estado["task_completed"] is True and estado["respuesta_final"] == "RESPUESTA FINAL"


async def test_estado_compartido_rastrea_que_agente_aporto_que():
    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ))
    estado, _ = await ejecutar(graph, CONSULTA)
    contribs = estado["contribuciones"]
    assert [c["agente"] for c in contribs] == ["investigador", "analista"]
    assert contribs[0]["fuentes"] and contribs[1]["herramientas_usadas"] == ["calcular"]
    assert [c["paso"] for c in contribs] == [1, 2]  # procedencia: qué decisión del supervisor lo originó
    assert [d["siguiente"] for d in estado["decisiones"]] == ["investigador", "analista", "sintetizador"]
    assert estado["pasos"] == 3


def test_el_estado_hereda_de_messagesstate_con_reducers():
    assert MessagesState in EstadoOrquestador.__orig_bases__
    assert {"messages", "next_agent", "contribuciones", "decisiones", "pasos", "task_completed"} <= set(
        get_type_hints(EstadoOrquestador)
    )


# ----------------------------------------------------------------- aislamiento
async def test_los_especialistas_reciben_solo_lo_necesario():
    graph, inv, ana = armar(guion_supervisor(*FLUJO_FELIZ))
    await ejecutar(graph, CONSULTA)
    assert inv.entradas == ["buscá severidades"]  # solo la instrucción del supervisor
    assert "TOKEN_SOLO_DEL_USUARIO" not in inv.entradas[0] + ana.entradas[0]  # no ven el historial
    assert ana.entradas[0].startswith("calculá updates")
    assert "DATOS DEL INVESTIGADOR" in ana.entradas[0] and "RTO 2 h" in ana.entradas[0]  # contexto mínimo
    assert "decisión" not in ana.entradas[0]  # ni la "razón" interna del supervisor


# ------------------------------------------------------------- reglas de validación
async def test_no_se_puede_cerrar_sin_investigacion():
    graph, _, _ = armar(guion_supervisor(("sintetizador", ""), ("analista", "x"), ("sintetizador", "")))
    estado, traza = await ejecutar(graph, CONSULTA)
    assert estado["decisiones"][0]["siguiente"] == "investigador"
    assert estado["decisiones"][0]["regla_aplicada"] == "R4_cierre_sin_investigacion"
    assert traza.flujo()[1] == "investigador"


async def test_el_analista_nunca_va_antes_que_el_investigador():
    graph, _, _ = armar(guion_supervisor(("analista", "calculá"), *FLUJO_FELIZ[1:]))
    estado, _ = await ejecutar(graph, CONSULTA)
    assert estado["decisiones"][0]["siguiente"] == "investigador"
    assert estado["decisiones"][0]["regla_aplicada"] == "R2_analista_requiere_datos"


async def test_refinamiento_si_el_investigador_no_cita_fuentes():
    inv = especialista(INV_SIN_FUENTES, INV_OK)
    graph, _, _ = armar(guion_supervisor(("investigador", "buscá"), ("analista", "calc"), ("sintetizador", "")), inv)
    estado, _ = await ejecutar(graph, CONSULTA)
    versiones = [(c["agente"], c["version"]) for c in estado["contribuciones"]]
    assert ("investigador", 1) in versiones and ("investigador", 2) in versiones
    refinar = next(d for d in estado["decisiones"] if d["regla_aplicada"] == "R4_investigacion_sin_fuentes")
    assert "REFINAMIENTO" in refinar["instruccion"]
    assert "REFINAMIENTO" in inv.entradas[1]  # el especialista recibe qué corregir


async def test_refinamiento_si_el_analista_no_usa_herramientas():
    ana = especialista(ANA_SIN_TOOLS, ANA_OK)
    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ), ana=ana)
    estado, _ = await ejecutar(graph, CONSULTA)
    assert [c["version"] for c in estado["contribuciones"] if c["agente"] == "analista"] == [1, 2]
    assert estado["advertencias"] == []  # el refinamiento resolvió el problema


async def test_si_el_refinamiento_no_alcanza_cierra_con_advertencia():
    ana = especialista(ANA_SIN_TOOLS)  # siempre sin herramientas
    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ), ana=ana)
    estado, _ = await ejecutar(graph, CONSULTA)
    assert estado["task_completed"] is True
    assert sum(c["agente"] == "analista" for c in estado["contribuciones"]) == sup.MAX_CONTRIBUCIONES_POR_AGENTE
    assert any("no usó herramientas" in a for a in estado["advertencias"])


# -------------------------------------------------------------- anti-bucle infinito
async def test_supervisor_obstinado_no_genera_bucle():
    graph, inv, _ = armar(guion_supervisor(("investigador", "otra vez")))  # pide siempre lo mismo
    estado, traza = await ejecutar(graph, CONSULTA)
    assert estado["task_completed"] is True
    assert len(inv.entradas) == sup.MAX_CONTRIBUCIONES_POR_AGENTE  # el especialista tiene tope
    assert estado["pasos"] <= sup.MAX_PASOS
    assert "R3_limite_de_refinamientos" in [d["regla_aplicada"] for d in estado["decisiones"]]


async def test_tope_duro_de_pasos(monkeypatch):
    monkeypatch.setattr(sup, "MAX_PASOS", 2)
    graph, _, _ = armar(guion_supervisor(("investigador", "x")))
    estado, _ = await ejecutar(graph, CONSULTA)
    assert estado["decisiones"][-1]["regla_aplicada"] == "R1_tope_de_pasos"
    assert estado["task_completed"] is True and estado["pasos"] == 3


async def test_recursion_limit_corta_y_no_lanza():
    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ))
    estado, traza = await ejecutar(graph, CONSULTA, recursion_limit=3)  # techo absurdamente bajo
    assert traza.eventos[-1]["nodo"] == "error" and not estado.get("task_completed")


# ------------------------------------------------------------------- robustez
async def test_si_falla_el_llm_del_supervisor_hay_ruta_de_emergencia():
    async def roto(_e: Any) -> DecisionLLM:
        raise TimeoutError("sin respuesta")

    graph, _, _ = armar(roto)
    estado, traza = await ejecutar(graph, CONSULTA)
    assert traza.flujo() == ["supervisor", "investigador", "supervisor", "analista", "supervisor", "sintetizador"]
    assert all(d["regla_aplicada"] == "R0_fallo_del_supervisor" for d in estado["decisiones"])


async def test_un_especialista_caido_no_tumba_el_sistema():
    async def caido(_entrada: str) -> dict[str, Any]:
        raise ConnectionError("API caída")

    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ), inv=caido)
    estado, _ = await ejecutar(graph, CONSULTA)
    assert estado["task_completed"] is True
    assert any("falló" in a for a in estado["advertencias"])


async def test_un_refinamiento_fallido_no_pisa_el_aporte_valido():
    """Caso real hallado en la prueba en vivo: la v2 del analista falló y el sintetizador perdió la v1."""
    estado_visto: dict[str, Any] = {}
    llamadas = {"n": 0}

    async def analista_que_falla_en_v2(entrada: str) -> dict[str, Any]:
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise RuntimeError("se agotaron los pasos")
        return ANA_OK

    async def sintetizar(estado: Any) -> str:
        estado_visto.update(estado)
        return "FINAL"

    decidir = guion_supervisor(("investigador", "buscá"), ("analista", "calc"), ("analista", "refiná"), ("sintetizador", ""))
    graph = build_graph(decidir=decidir, investigador=especialista(INV_OK), analista=analista_que_falla_en_v2, sintetizar=sintetizar)
    estado, _ = await ejecutar(graph, CONSULTA)
    v = [(c["version"], c["fallida"]) for c in estado["contribuciones"] if c["agente"] == "analista"]
    assert v == [(1, False), (2, True)]
    vigente = ultima_contribucion(estado, "analista")
    assert vigente["version"] == 1 and "8 actualizaciones" in vigente["contenido"]  # sigue vigente la v1
    assert "8 actualizaciones" in sup.describir_situacion(estado_visto)  # y el supervisor la ve
    assert any("falló en su intento v2" in a for a in estado["advertencias"])


async def test_un_refinamiento_que_complementa_no_borra_el_aporte_anterior():
    """Caso real: la v2 del investigador trajo solo datos NUEVOS; el analista debe ver v1 y v2."""
    inv = especialista(
        {"contenido": "DATO-A: SEV1 responde en 5 min", "herramientas_usadas": ["buscar_conocimiento"], "fuentes": ["a.md#1"]},
        {"contenido": "DATO-B: RTO de 2 h", "herramientas_usadas": ["buscar_conocimiento"], "fuentes": ["b.md#4"]},
    )
    ana = especialista(ANA_OK)
    decidir = guion_supervisor(("investigador", "tiempos"), ("investigador", "RTO"), ("analista", "calc"), ("sintetizador", ""))
    graph, _, _ = armar(decidir, inv=inv, ana=ana)
    estado, _ = await ejecutar(graph, CONSULTA)
    assert "DATO-A" in ana.entradas[0] and "DATO-B" in ana.entradas[0]  # el analista ve los dos aportes
    assert [c["version"] for c in contribuciones_vigentes(estado, "investigador")] == [1, 2]
    assert "DATO-A" in texto_de_aportes(contribuciones_vigentes(estado, "investigador"))  # y el sintetizador también


def test_fuentes_citadas_ignora_lo_que_solo_devolvio_la_busqueda():
    recuperadas = ["02_incidentes.md#2. Niveles", "01_backups.md#4. RTO", "04_seguridad.md#4. Datos"]
    texto_final = "SEV1 = 5 min (fuente: `02_incidentes.md#2. Niveles`). RTO 2 h (**01_backups.md#4. RTO**)."
    assert fuentes_citadas(texto_final, recuperadas) == ["02_incidentes.md#2. Niveles", "01_backups.md#4. RTO"]
    muchas = [f"doc{i}.md#sec" for i in range(8)]
    assert fuentes_citadas("sin citas", muchas) == muchas[:3]  # sin citas: se conservan las 3 más relevantes


def test_ultima_contribucion_prefiere_la_ultima_valida():
    base = {"paso": 1, "instruccion": "", "herramientas_usadas": [], "fuentes": []}
    est: Any = {"contribuciones": [
        {**base, "agente": "analista", "version": 1, "contenido": "bueno", "fallida": False},
        {**base, "agente": "analista", "version": 2, "contenido": "[falló]", "fallida": True},
    ]}
    assert ultima_contribucion(est, "analista")["contenido"] == "bueno"
    est["contribuciones"] = [est["contribuciones"][1]]  # si TODOS fallaron, se informa el último
    assert ultima_contribucion(est, "analista")["contenido"] == "[falló]"


# ---------------------------------------------------------------- estructura
def test_estructura_y_diagrama_del_grafo():
    graph, _, _ = armar(guion_supervisor(*FLUJO_FELIZ))
    g = graph.get_graph()
    assert {"supervisor", "investigador", "analista", "aprobacion", "ejecutor", "sintetizador"} <= set(g.nodes)
    destinos = {e.target for e in g.edges if e.source == "supervisor" and e.conditional}
    assert destinos == {"investigador", "analista", "aprobacion", "sintetizador"}
    texto = mermaid(graph)
    assert "supervisor -.-> investigador" in texto and "graph TD" in texto


def test_el_retorno_de_enrutar_es_un_literal_con_los_nodos():
    ret = get_type_hints(enrutar)["return"]
    assert set(get_args(ret)) == {"investigador", "analista", "aprobacion", "sintetizador"}
    assert ret == Literal["investigador", "analista", "aprobacion", "sintetizador"]


async def test_decisor_llm_usa_rubrica_y_la_situacion():
    from langchain_core.runnables import RunnableLambda

    vistos: list[Any] = []

    class LLMFalso:
        def with_structured_output(self, schema: Any) -> Any:
            def f(msgs: Any) -> DecisionLLM:
                vistos.append(msgs)
                return DecisionLLM(razon="r", siguiente="investigador", instruccion="i")

            return RunnableLambda(f)

    decidir = sup.crear_decisor_llm(LLMFalso())  # type: ignore[arg-type]
    d = await decidir({"messages": [], "contribuciones": [], "pasos": 0})  # type: ignore[arg-type]
    assert d.siguiente == "investigador"
    assert "RÚBRICA DE VALIDACIÓN" in vistos[0][0].content  # la rúbrica está en el prompt del supervisor


# ------------------------------------------------------------------ herramientas
async def test_el_decisor_reintenta_una_vez_si_el_modelo_omite_un_campo():
    """Regresión real: Haiku a veces devuelve la decisión sin ``siguiente``; con un reintento alcanza."""
    from langchain_core.messages import HumanMessage

    llamadas = {"n": 0}

    class Estructurado:
        async def ainvoke(self, _mensajes):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                DecisionLLM.model_validate({"razon": "falta el campo siguiente"})  # ValidationError
            return DecisionLLM(razon="ok", siguiente="investigador")

    class LLM:
        def with_structured_output(self, _esquema):
            return Estructurado()

    d = await sup.crear_decisor_llm(LLM())({"messages": [HumanMessage("reclamo")], "contribuciones": []})  # type: ignore[arg-type]
    assert d.siguiente == "investigador" and llamadas["n"] == 2
