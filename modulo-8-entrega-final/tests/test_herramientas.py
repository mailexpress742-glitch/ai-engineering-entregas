"""Herramientas de los agentes (validación Pydantic) y seguimiento de piezas."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.agents import action_agent
from app.agents.action_agent import crear_herramientas_ejecutor
from app.agents.analyst_agent import crear_herramientas_analista, evaluar
from app.agents.research_agent import crear_herramientas_investigador
from app.calendario import dias_habiles_entre, es_habil, sumar_dias_habiles
from app.rag.ingesta import cargar_fragmentos
from app.rag.sistema import RAGSystem
from app.schemas import EscalamientoIn, NuevoReclamo, Pieza, RespuestaClienteIn
from app.tracking import PiezaInexistente, RepositorioPiezas

HOY = date(2026, 11, 18)  # miércoles


def herramienta(lista, nombre):
    return next(t for t in lista if t.name == nombre)


@pytest.fixture
def repo():
    return RepositorioPiezas(hoy=HOY)


# ------------------------------------------------------------------ calendario
def test_dias_habiles_no_cuentan_fines_de_semana_ni_feriados():
    assert dias_habiles_entre(date(2026, 11, 13), date(2026, 11, 16)) == 1  # viernes → lunes
    assert dias_habiles_entre(date(2026, 11, 20), date(2026, 11, 24)) == 1  # el lunes 23 es feriado: solo cuenta el martes
    assert dias_habiles_entre(date(2026, 11, 18), date(2026, 11, 18)) == 0 and dias_habiles_entre(HOY, date(2026, 11, 10)) == 0
    assert not es_habil(date(2026, 11, 23)) and es_habil(date(2026, 11, 24))


def test_sumar_dias_habiles_es_la_inversa():
    for n in (1, 3, 8, 15):
        assert dias_habiles_entre(date(2026, 11, 4), sumar_dias_habiles(date(2026, 11, 4), n)) == n


# --------------------------------------------------------------------- seguimiento
async def test_los_20_datos_sinteticos_son_validos_y_cubren_los_casos(repo):
    for pid in ("CD-100231", "CD-100233", "CD-100234", "CD-100236", "EN-204521", "NT-310077"):
        assert (await repo.consultar(pid)).pieza_id == pid
    assert len(await repo._cargar()) == 20


async def test_consultar_calcula_los_dias_habiles(repo):
    p = await repo.consultar("CD-100231")  # AMBA, impuesta hace 5 días hábiles, en distribución
    assert p.dias_habiles_desde_imposicion == 5 and p.estado == "EN_DISTRIBUCION" and p.zona == "AMBA"
    entregada = await repo.consultar("CD-100234")  # entregada: acuse pendiente
    assert entregada.estado == "ENTREGADA" and entregada.dias_habiles_desde_entrega == 9 and not entregada.acuse_devuelto
    visitas = await repo.consultar("CD-100233")
    assert visitas.visitas_negativas == 2 and visitas.estado == "VISITA_2_NEGATIVA"
    perdida = await repo.consultar("CD-100236")  # Patagonia, 25 días hábiles, última novedad hace 23
    assert perdida.dias_habiles_sin_movimiento == 23


async def test_pieza_inexistente(repo):
    with pytest.raises(PiezaInexistente):
        await repo.consultar("CD-999999")


def test_el_esquema_de_pieza_rechaza_datos_invalidos():
    base = {"pieza_id": "CD-100231", "servicio": "carta_documento", "cliente": "X", "provincia": "CABA", "zona": "AMBA",
            "cliente_corporativo": False, "fecha_imposicion": "2026-11-11", "estado": "IMPUESTA",
            "eventos": [{"fecha": "2026-11-11", "estado": "IMPUESTA", "detalle": "ok"}]}
    assert Pieza(**base)
    for cambio in ({"pieza_id": "ZZ-1"}, {"zona": "Marte"}, {"eventos": []}, {"fecha_imposicion": "ayer"}):
        with pytest.raises(ValidationError):
            Pieza(**{**base, **cambio})


# ------------------------------------------------------- herramientas del analista
async def test_consultar_pieza_tool_devuelve_datos_validados(repo):
    t = herramienta(crear_herramientas_analista(repo), "consultar_pieza")
    r = await t.ainvoke({"pieza_id": "EN-204519"})
    assert r["servicio"] == "encomienda" and r["zona"] == "Interior" and r["dias_habiles_desde_imposicion"] == 8
    assert (await t.ainvoke({"pieza_id": "EN-999999"}))["error"].startswith("La pieza EN-999999 no existe")


async def test_las_herramientas_rechazan_argumentos_invalidos(repo):
    analista = crear_herramientas_analista(repo)
    with pytest.raises(ValidationError):
        await herramienta(analista, "consultar_pieza").ainvoke({"pieza_id": "'; DROP TABLE piezas;--"})
    with pytest.raises(ValidationError):
        await herramienta(analista, "dias_habiles_entre").ainvoke({"desde": "ayer", "hasta": "2026-11-18"})
    with pytest.raises(ValidationError):
        await herramienta(analista, "consultar_pieza").ainvoke({"pieza_id": "CD-100231", "extra": 1})


async def test_calcular_y_dias_habiles(repo):
    analista = crear_herramientas_analista(repo)
    assert (await herramienta(analista, "calcular").ainvoke({"expresion": "5 - 3"}))["resultado"] == 2
    for malo in ("__import__('os').system('x')", "open('f')", "1/0", "2**9999"):
        assert "error" in await herramienta(analista, "calcular").ainvoke({"expresion": malo}), malo
    r = await herramienta(analista, "dias_habiles_entre").ainvoke({"desde": "2026-11-13", "hasta": "2026-11-18"})
    assert r["dias_habiles"] == 3 and evaluar("min(3, 2) + 1") == 3


# ----------------------------------------------------- herramientas del investigador
async def test_buscar_conocimiento_tool_valida_y_filtra():
    rag = RAGSystem(cargar_fragmentos(modelo="t"))
    inv = crear_herramientas_investigador(rag)
    r = await herramienta(inv, "buscar_conocimiento").ainvoke({"consulta": "plazo entrega carta documento", "servicio": "carta_documento"})
    assert r["resultados"] and r["resultados"][0]["fuente"].endswith(".md") and r["resultados"][0]["seccion"]
    vacio = await herramienta(inv, "buscar_conocimiento").ainvoke({"consulta": "zzzz qqqq"})
    assert vacio["resultados"] == [] and "sugerencia" in vacio
    for malo in ({"consulta": "ok"}, {"consulta": "plazo", "servicio": "paloma"}, {"consulta": "plazo", "max_resultados": 99}):
        with pytest.raises(ValidationError):
            await herramienta(inv, "buscar_conocimiento").ainvoke(malo)
    docs = (await herramienta(inv, "listar_documentos").ainvoke({}))["documentos"]
    assert len(docs) == 14


# ------------------------------------------------------- herramientas del ejecutor
async def test_el_ejecutor_valida_y_registra_en_la_bandeja():
    ejecutor = crear_herramientas_ejecutor()
    esc = herramienta(ejecutor, "escalar_caso")
    ok = {"pieza_id": "CD-100236", "area": "siniestros", "prioridad": "alta",
          "resumen": "Sin movimientos hace 23 días hábiles; se presume extravío. Pedir búsqueda."}
    await esc.ainvoke(ok)
    resp = herramienta(ejecutor, "responder_cliente")
    await resp.ainvoke({"pieza_id": "CD-100236", "destinatario": "Constructora Andina SRL", "asunto": "Búsqueda de su pieza CD-100236",
                        "mensaje": "Estimado cliente: iniciamos una búsqueda de su pieza con el área de Siniestros."})
    assert [e["tipo"] for e in action_agent.ENVIADOS] == ["escalamiento", "respuesta_cliente"]
    assert action_agent.ENVIADOS[0]["detalle"]["area"] == "siniestros"

    for malo in ({**ok, "area": "marketing"}, {**ok, "prioridad": "ya"}, {**ok, "resumen": "corto"}, {**ok, "pieza_id": "x"}):
        with pytest.raises(ValidationError):
            await esc.ainvoke(malo)
    assert len(action_agent.ENVIADOS) == 2  # nada inválido llegó a la bandeja


async def test_el_ejecutor_no_envia_plantillas_sin_completar():
    r = await action_agent.responder_cliente(
        pieza_id="CD-100231", destinatario="Cliente", asunto="Seguimiento de su pieza", mensaje="Estimado/a {cliente}: su pieza {pieza_id} está demorada, disculpe."
    )
    assert r.startswith("Error") and action_agent.ENVIADOS == []


def test_esquemas_de_la_api():
    assert NuevoReclamo(texto="No llegó mi carta documento", pieza_id="CD-100231", cliente="Ana").canal == "web"
    assert "CD-100231" in NuevoReclamo(texto="No llegó mi carta documento", pieza_id="CD-100231", cliente="Ana").como_consulta()
    with pytest.raises(ValidationError):
        RespuestaClienteIn(pieza_id="CD-100231", destinatario="A", asunto="x", mensaje="corto")
    with pytest.raises(ValidationError):
        EscalamientoIn(pieza_id="CD-100231", area="legales", prioridad="mañana", resumen="x" * 40)
