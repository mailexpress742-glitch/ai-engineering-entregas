"""Human-in-the-loop: pausa obligatoria antes de cualquier acción con efectos secundarios.

Cómo funciona:

1. El supervisor decide ``ejecutor`` (acción con efectos secundarios). El grafo NO va directo:
   pasa por el nodo ``aprobacion``.
2. ``aprobacion`` llama a ``interrupt(...)``. LangGraph guarda el checkpoint en Redis y la
   ejecución se detiene (el worker queda libre). El job pasa a ``AWAITING_APPROVAL`` y su
   solicitud queda visible en ``GET /tasks/{id}``.
3. Un humano responde con ``POST /tasks/{id}/approve``; el worker reanuda el grafo con
   ``Command(resume=...)`` desde el checkpoint. Aprobado → corre el ejecutor. Rechazado → vuelve
   al supervisor, que cierra informando que la acción no se realizó.

El nodo es idempotente a propósito: al reanudar, LangGraph re-ejecuta el nodo desde el
principio, por eso antes de ``interrupt`` no hay ningún efecto secundario.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import AIMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.agents.action_agent import HERRAMIENTAS_CRITICAS
from app.state import EstadoOrquestador, contribuciones_vigentes, texto_de_aportes


def solicitud_de_aprobacion(estado: EstadoOrquestador) -> dict[str, Any]:
    """Lo que ve el humano: qué se quiere hacer, por qué es crítico y con qué datos."""
    datos = [c for ag in ("investigador", "analista") for c in contribuciones_vigentes(estado, ag)]
    return {
        "tipo": "aprobacion_requerida",
        "accion_propuesta": estado["instruccion_actual"],
        "motivo": "La acción tiene efectos secundarios (herramientas: " + ", ".join(sorted(HERRAMIENTAS_CRITICAS)) + ").",
        "datos_de_respaldo": texto_de_aportes(datos)[:1500],
    }


async def nodo_aprobacion(estado: EstadoOrquestador) -> Command[Literal["ejecutor", "supervisor"]]:
    decision = interrupt(solicitud_de_aprobacion(estado))  # ← acá se pausa hasta que llegue el input externo
    aprobado = bool(decision.get("aprobado")) if isinstance(decision, dict) else bool(decision)
    comentario = decision.get("comentario", "") if isinstance(decision, dict) else ""
    registro = {"aprobado": aprobado, "comentario": comentario}
    if aprobado:
        return Command(goto="ejecutor", update={"aprobacion": registro})
    return Command(
        goto="supervisor",
        update={
            "aprobacion": registro,
            "accion_rechazada": True,
            "advertencias": ["Un humano RECHAZÓ la acción propuesta: no se ejecutó." + (f" Motivo: {comentario}" if comentario else "")],
            "messages": [AIMessage(content=f"Acción rechazada por el aprobador. {comentario}".strip(), name="aprobacion")],
        },
    )


# ------------------------------------------------------------------ endpoint
class DecisionHumana(BaseModel):
    aprobado: bool = Field(description="true para autorizar la acción, false para rechazarla.")
    comentario: str = Field(default="", max_length=500)


router = APIRouter()


@router.post("/tasks/{job_id}/approve", status_code=202, tags=["HITL"])
async def aprobar(job_id: str, decision: DecisionHumana, request: Request) -> dict[str, Any]:
    """Resuelve una aprobación pendiente y reencola el job para que continúe."""
    cola = request.app.state.cola
    resultado = await cola.resolver_aprobacion(job_id, decision.aprobado, decision.comentario)
    if resultado == "no_existe":
        raise HTTPException(404, "Job inexistente")
    if resultado == "no_pendiente":
        raise HTTPException(409, "El job no está esperando aprobación")
    return {"job_id": job_id, "status": "RUNNING", "aprobado": decision.aprobado}
