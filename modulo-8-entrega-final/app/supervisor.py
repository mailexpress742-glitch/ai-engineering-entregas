"""Supervisor: decide quién interviene a continuación o si es momento de cerrar.

Dos capas, para que el sistema sea inteligente Y seguro:

1. **El LLM decide** (router inteligente) con una rúbrica de validación explícita en su prompt.
2. **Reglas en código validan esa decisión** antes de ejecutarla (``aplicar_reglas``): impiden
   cerrar sin investigación y análisis, exigen que los aportes cumplan una puerta de calidad,
   limitan los refinamientos por agente y cortan el flujo en un tope de pasos. Así un supervisor
   que se equivoque o se obstine no puede generar un bucle infinito.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from app.state import Agente, Contribucion, EstadoOrquestador, RegistroDecision, consulta_original, ultima_contribucion

logger = logging.getLogger("orquestador.supervisor")

MAX_PASOS = 7  # decisiones del supervisor por solicitud (criterio de parada duro)
MAX_CONTRIBUCIONES_POR_AGENTE = 2  # intento inicial + 1 refinamiento


class DecisionLLM(BaseModel):
    """Salida estructurada del supervisor."""

    razon: str = Field(description="Breve justificación de la decisión, basada en la rúbrica.")
    siguiente: Literal["investigador", "analista", "ejecutor", "sintetizador"] = Field(
        description="A quién enrutar: investigador, analista, ejecutor (acción con efectos secundarios), o sintetizador si la tarea está completa."
    )
    instruccion: str = Field(
        default="",
        description=(
            "Instrucción ESPECÍFICA para el especialista elegido (qué debe buscar o calcular). "
            "Si es un refinamiento, indicá exactamente qué corregir. Vacía si siguiente=sintetizador."
        ),
    )


Decidir = Callable[[EstadoOrquestador], Awaitable[DecisionLLM]]

SUPERVISOR_PROMPT = """Sos el SUPERVISOR de la mesa de reclamos de MailEx (correo y logística). Un cliente reclama por una pieza
(carta documento, encomienda o notificación) y tu equipo de agentes la resuelve. Tu equipo:
- investigador: busca en la base de conocimiento (RAG) los plazos, procedimientos, políticas, áreas de escalamiento
  y plantillas que aplican (no calcula, no consulta piezas).
- analista: consulta el estado REAL de la pieza en el seguimiento y calcula con herramientas (días hábiles, atraso)
  para concluir si el plazo está vencido, si falta un acuse, qué prioridad y qué área corresponden (no busca normativa).
- ejecutor: realiza las acciones con efectos secundarios: responder al cliente con la plantilla que corresponde y/o
  escalar el caso al área responsable. Un humano debe aprobarlas antes de ejecutarse: vos solo las proponés, con una
  instrucción que diga qué comunicar, a quién y qué escalar. Va DESPUÉS de tener la normativa y el diagnóstico.
- sintetizador: redacta el informe final (solo cuando la tarea está completa).

Dada la conversación actual, decidí quién debe intervenir ahora o si es momento de finalizar.

RÚBRICA DE VALIDACIÓN (revisá los aportes con estos criterios antes de cerrar):
1. COBERTURA: el reclamo del cliente tiene respuesta y, si corresponde, un escalamiento.
2. FUNDAMENTO: la normativa del investigador cita fuentes (archivo#sección) y no es inventada.
3. HECHOS VERIFICADOS: el estado de la pieza y los días hábiles salen de las herramientas del analista, y el
   analista los comparó con los plazos que investigó el investigador.
4. CONSISTENCIA: no hay contradicciones entre los aportes.
5. ENTRADAS COMPLETAS: el investigador reportó TODO lo que el analista y el ejecutor necesitan (plazo del servicio y
   zona, política aplicable, área de escalamiento, plantilla) y el analista no usó ningún valor supuesto.

REGLAS DE DECISIÓN:
- Antes de la primera instrucción, descomponé el reclamo: identificá el servicio de la pieza (CD = carta documento,
  EN = encomienda, NT = notificación), la zona si la conocés, y qué normativa hará falta (plazo de entrega, plazo de
  acuse, política de extravío o demora, escalamiento, plantilla). Pedísela al investigador junta, en una sola instrucción.
- NUNCA metas supuestos propios en las instrucciones (plazos, zonas, estados de la pieza que no figuren en lo
  investigado o consultado). Si falta un dato, mandá primero al especialista que lo obtiene.
- Faltan normativa/plantillas -> investigador. Hay normativa pero falta el diagnóstico de la pieza -> analista.
- Si un aporte incumple la rúbrica, reenviá al MISMO especialista con una instrucción que diga exactamente qué corregir
  (máximo un refinamiento por especialista).
- Con normativa y diagnóstico completos -> ejecutor (una sola vez): la instrucción debe decir qué respuesta enviar al
  cliente (qué plantilla y con qué datos) y si hay que escalar (a qué área y con qué prioridad). Si un humano la
  rechazó, no insistas: cerrá con el sintetizador. En esa instrucción nombrá solo plantillas y áreas que el
  investigador haya reportado (no inventes nombres de plantillas), con prioridades del conjunto baja/media/alta/urgente
  y áreas del conjunto distribucion/coordinacion_interior/siniestros/atencion_corporativa/legales.
- No reinterpretes el diagnóstico del analista: al instruir al ejecutor, reproducí sus conclusiones tal cual
  (por ejemplo «plazo VENCIDO por 3 días hábiles»), sin suavizarlas ni cambiarlas.
- Si el cliente menciona algo decisivo en su mensaje (un vencimiento legal, una penalidad contractual), copiáselo
  textualmente al analista y al ejecutor en tus instrucciones: ellos no ven el reclamo.
- Cuando la acción ya se hizo o fue rechazada -> sintetizador.
- Escribí instrucciones concretas y autocontenidas: el especialista NO ve la conversación, solo tu instrucción."""


# --------------------------------------------------------------------- contexto
def _recorte(texto: str, n: int = 700) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= n else texto[:n] + "…"


def describir_situacion(estado: EstadoOrquestador) -> str:
    """Resumen para el supervisor: la solicitud y qué aportó cada agente (con procedencia)."""
    lineas = [f"SOLICITUD DEL USUARIO:\n{consulta_original(estado)}\n"]
    contribs: list[Contribucion] = estado.get("contribuciones", [])
    if not contribs:
        lineas.append("APORTES: todavía no hay ninguno.")
    for c in contribs:
        estado_aporte = " [FALLIDO: el aporte vigente es la versión anterior]" if c.get("fallida") else ""
        lineas.append(
            f"APORTE de {c['agente']} (v{c['version']}, paso {c['paso']}){estado_aporte}: herramientas={c['herramientas_usadas'] or 'ninguna'}"
            f" fuentes={c['fuentes'] or 'ninguna'}\n{_recorte(c['contenido'])}"
        )
    if estado.get("accion_rechazada"):
        lineas.append("\nUN HUMANO RECHAZÓ LA ACCIÓN PROPUESTA: no se ejecutó y no se puede reintentar.")
    lineas.append(f"\nDecisiones tomadas: {estado.get('pasos', 0)} de un máximo de {MAX_PASOS}.")
    if estado.get("advertencias"):
        lineas.append("Advertencias: " + " | ".join(estado["advertencias"]))
    return "\n".join(lineas)


def crear_decisor_llm(llm: BaseChatModel, *, exigir_accion: bool = False) -> Decidir:
    """Decisor basado en un LLM con salida estructurada (``DecisionLLM``). ``exigir_accion`` solo documenta
    el modo: la regla R6 que lo hace cumplir está en ``aplicar_reglas``."""
    estructurado = llm.with_structured_output(DecisionLLM)

    async def decidir(estado: EstadoOrquestador) -> DecisionLLM:
        mensajes = [SystemMessage(SUPERVISOR_PROMPT), HumanMessage(describir_situacion(estado))]
        try:
            return await estructurado.ainvoke(mensajes)
        except ValidationError as exc:  # el modelo omitió un campo obligatorio: un reintento casi siempre alcanza
            logger.warning("Salida mal formada del supervisor (%d errores); reintento una vez", exc.error_count())
            return await estructurado.ainvoke(mensajes)

    return decidir


# ----------------------------------------------------------------------- reglas
def _cuenta(estado: EstadoOrquestador, agente: str) -> int:
    return sum(c["agente"] == agente for c in estado.get("contribuciones", []))


def _instruccion_por_defecto(agente: str, estado: EstadoOrquestador) -> str:
    q = consulta_original(estado)
    if agente == "investigador":
        return f"Buscá en la base de conocimiento la normativa (plazo del servicio, política, escalamiento, plantilla) para resolver este reclamo: {q}"
    if agente == "ejecutor":
        return f"Respondé al cliente con la plantilla que corresponde (y escalá al área si la política lo indica) para este reclamo: {q}"
    return f"Consultá la pieza y, con los plazos investigados, diagnosticá este reclamo: {q}"


def aplicar_reglas(
    estado: EstadoOrquestador, d: DecisionLLM, *, exigir_accion: bool = False
) -> tuple[Agente, str, str | None, list[str]]:
    """Valida la decisión del LLM. Devuelve (siguiente, instrucción, regla_aplicada, advertencias).

    Las reglas solo pueden REDIRIGIR hacia un especialista que todavía tenga margen o hacia el
    sintetizador, y el número de pasos está acotado: siempre se llega a ``sintetizador``.
    """
    paso = estado.get("pasos", 0) + 1
    inv, ana = ultima_contribucion(estado, "investigador"), ultima_contribucion(estado, "analista")
    siguiente, instruccion = d.siguiente, d.instruccion.strip()

    def puede(agente: str) -> bool:
        return _cuenta(estado, agente) < MAX_CONTRIBUCIONES_POR_AGENTE

    # R1 — criterio de parada duro: tope de decisiones.
    if paso > MAX_PASOS:
        return "sintetizador", "", "R1_tope_de_pasos", [f"Se alcanzó el tope de {MAX_PASOS} pasos: la respuesta puede ser parcial."]

    # R2 — el analista necesita datos: nunca antes que el investigador.
    if siguiente == "analista" and inv is None:
        return "investigador", _instruccion_por_defecto("investigador", estado), "R2_analista_requiere_datos", []

    # R5 — la acción con efectos secundarios es única, exige datos previos y no se reintenta tras un rechazo.
    if siguiente == "ejecutor":
        if inv is None:
            return "investigador", _instruccion_por_defecto("investigador", estado), "R5_accion_sin_datos", []
        if estado.get("accion_rechazada") or _cuenta(estado, "ejecutor") >= 1:
            return "sintetizador", "", "R5_accion_no_repetible", []
        return "ejecutor", instruccion or _instruccion_por_defecto("ejecutor", estado), None, []

    # R3 — un especialista que ya agotó sus intentos no puede volver a intervenir.
    if siguiente in ("investigador", "analista") and not puede(siguiente):
        aviso = [f"El {siguiente} alcanzó su límite de {MAX_CONTRIBUCIONES_POR_AGENTE} intentos."]
        # No se cierra de golpe: se avanza al siguiente paso que todavía falta (diagnóstico → acción → cierre).
        if ana is None and inv is not None and siguiente != "analista":
            return "analista", _instruccion_por_defecto("analista", estado), "R3_limite_de_refinamientos", aviso
        if exigir_accion and _cuenta(estado, "ejecutor") == 0 and not estado.get("accion_rechazada") and inv is not None and ana is not None:
            return "ejecutor", _instruccion_por_defecto("ejecutor", estado), "R3_limite_de_refinamientos", aviso
        return "sintetizador", "", "R3_limite_de_refinamientos", aviso

    # R4 — puertas de calidad antes de permitir el cierre.
    if siguiente == "sintetizador":
        if inv is None:
            return "investigador", _instruccion_por_defecto("investigador", estado), "R4_cierre_sin_investigacion", []
        if not inv["fuentes"] and puede("investigador"):
            return (
                "investigador",
                "REFINAMIENTO: tu aporte anterior no citó ninguna fuente. Buscá con `buscar_conocimiento` "
                "y reportá los datos exactos citando archivo#sección. " + _instruccion_por_defecto("investigador", estado),
                "R4_investigacion_sin_fuentes",
                [],
            )
        if ana is None:
            return "analista", _instruccion_por_defecto("analista", estado), "R4_cierre_sin_analisis", []
        if not ana["herramientas_usadas"] and puede("analista"):
            return (
                "analista",
                "REFINAMIENTO: tu aporte anterior no usó ninguna herramienta de cálculo. Consultá la pieza con `consultar_pieza` y rehacé "
                "los cálculos con `calcular`/`dias_habiles_entre`. " + _instruccion_por_defecto("analista", estado),
                "R4_analisis_sin_herramientas",
                [],
            )
        # R6 — (modo reclamos) no se cierra sin haber propuesto la acción: responder/escalar. Un rechazo humano la cuenta como hecha.
        if exigir_accion and _cuenta(estado, "ejecutor") == 0 and not estado.get("accion_rechazada"):
            return "ejecutor", _instruccion_por_defecto("ejecutor", estado), "R6_cierre_sin_accion", []
        adv = []
        if inv and not inv["fuentes"]:
            adv.append("El investigador no citó fuentes: los datos no están verificados.")
        if ana and not ana["herramientas_usadas"]:
            adv.append("El analista no usó herramientas de cálculo: las cifras no están verificadas.")
        return "sintetizador", "", None, adv

    # Decisión válida del LLM hacia un especialista.
    return siguiente, instruccion or _instruccion_por_defecto(siguiente, estado), None, []


def _ruta_de_emergencia(estado: EstadoOrquestador) -> Agente:
    """Si el LLM del supervisor falla: avanzar por el camino lógico investigador -> analista -> cierre."""
    if _cuenta(estado, "investigador") == 0:
        return "investigador"
    if _cuenta(estado, "analista") == 0:
        return "analista"
    return "sintetizador"


def crear_nodo_supervisor(
    decidir: Decidir, *, exigir_accion: bool = False
) -> Callable[[EstadoOrquestador], Awaitable[dict[str, Any]]]:
    async def nodo_supervisor(estado: EstadoOrquestador) -> dict[str, Any]:
        paso = estado.get("pasos", 0) + 1
        try:
            d = await decidir(estado)
        except Exception as exc:  # noqa: BLE001 - el supervisor nunca debe tumbar el flujo
            logger.error("El supervisor falló (%s: %s); se usa la ruta de emergencia", type(exc).__name__, exc)
            d = DecisionLLM(razon=f"fallo del LLM ({type(exc).__name__})", siguiente=_ruta_de_emergencia(estado))
            regla_base = "R0_fallo_del_supervisor"
        else:
            regla_base = None
        siguiente, instruccion, regla, adv = aplicar_reglas(estado, d, exigir_accion=exigir_accion)
        regla = regla or regla_base
        registro: RegistroDecision = {
            "paso": paso, "siguiente": siguiente, "razon": d.razon, "instruccion": instruccion, "regla_aplicada": regla,
        }
        logger.info("Supervisor [paso %d] -> %s%s", paso, siguiente, f" (regla {regla})" if regla else "")
        return {
            "next_agent": siguiente,
            "instruccion_actual": instruccion,
            "pasos": 1,
            "decisiones": [registro],
            "advertencias": adv,
        }

    return nodo_supervisor
