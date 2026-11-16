"""API REST del orquestador multi-agente (FastAPI).

    POST /tasks                → encola la tarea y devuelve {job_id} al instante (202). NO ejecuta el agente.
    GET  /tasks/{job_id}       → estado del job (PENDING/RUNNING/AWAITING_APPROVAL/DONE/FAILED) y resultado.
    POST /tasks/{job_id}/approve → resuelve la aprobación humana de una acción crítica (ver hitl.py).
    GET  /outbox               → comunicados que el ejecutor envió (evidencia de que SOLO ocurren tras aprobar).
    GET  /salud                → Redis, cola y workers.

El endpoint solo escribe en Redis; el trabajo pesado lo hacen los workers (``app/worker.py``), así
el event loop de la API nunca se bloquea con llamadas al LLM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.agents.action_agent import configurar_salida
from app.graph import build_graph
from app.hitl import router as hitl_router
from app.llm import get_chat_model
from app.observability import init_observability
from app.redis_checkpointer import AsyncRedisCheckpointer
from app.store import ColaTrabajos, JobStore
from app.worker import Worker, recuperar_huerfanos

logger = logging.getLogger("api")
OUTBOX = "outbox"

RedisFactory = Callable[[bool], Redis]  # decode_responses → cliente


def _redis_desde_entorno(decode: bool) -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=decode)


class NuevaTarea(BaseModel):
    consulta: str = Field(min_length=3, max_length=4000, description="Solicitud para el orquestador multi-agente.")


class TareaCreada(BaseModel):
    job_id: str
    status: str = "PENDING"


def create_app(
    *,
    graph: Any | None = None,
    redis_factory: RedisFactory | None = None,
    workers: int | None = None,
) -> FastAPI:
    """Fábrica de la app. ``graph``/``redis_factory``/``workers`` se inyectan en los tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()
        factory = redis_factory or _redis_desde_entorno
        r_txt, r_bin = factory(True), factory(False)  # str para jobs/cola; bytes para los checkpoints
        await r_txt.ping()
        store = JobStore(r_txt)
        cola = ColaTrabajos(store)
        app.state.store, app.state.cola, app.state.redis = store, cola, r_txt

        async def registrar_envio(registro: dict[str, Any]) -> None:
            await r_txt.rpush(OUTBOX, json.dumps(registro, ensure_ascii=False))

        configurar_salida(registrar_envio)

        n = workers if workers is not None else int(os.getenv("WORKERS", "5"))
        tareas: list[asyncio.Task] = []
        stop = asyncio.Event()
        app.state.workers = n
        if n > 0:
            init_observability()
            g = graph or build_graph(get_chat_model(max_tokens=2048), checkpointer=AsyncRedisCheckpointer(r_bin))
            worker = Worker(g, store, cola)
            if os.getenv("RECUPERAR_AL_INICIAR", "1") == "1":
                recuperados = await recuperar_huerfanos(store, cola)
                if recuperados:
                    logger.warning("Se reanudan %d jobs que quedaron RUNNING", recuperados)
            tareas = [asyncio.create_task(worker.run_forever(stop), name=f"worker-{i}") for i in range(n)]
        try:
            yield
        finally:
            stop.set()
            for t in tareas:
                t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            await r_txt.aclose()
            await r_bin.aclose()

    opciones: dict[str, Any] = {"title": "Orquestador multi-agente · API de producción", "version": "1.0", "lifespan": lifespan}
    try:
        # FastAPI recientes emiten spans OpenTelemetry por request: con el polling de GET /tasks/{id} llenarían
        # Phoenix de trazas de 10 ms y ensuciarían la latencia. Solo queremos las trazas de los jobs.
        app = FastAPI(**opciones, telemetry={"tracing": False})
    except TypeError:  # versiones sin ese parámetro (no emiten esos spans)
        app = FastAPI(**opciones)
    app.include_router(hitl_router)

    @app.post("/tasks", status_code=202, response_model=TareaCreada, tags=["Tareas"])
    async def crear_tarea(tarea: NuevaTarea) -> TareaCreada:
        """Registra el job como PENDING en Redis, lo encola y responde sin esperar al agente."""
        job_id = await app.state.store.crear(tarea.consulta)
        await app.state.cola.encolar(job_id, "run")
        return TareaCreada(job_id=job_id)

    @app.get("/tasks/{job_id}", tags=["Tareas"])
    async def estado_tarea(job_id: str) -> dict[str, Any]:
        job = await app.state.store.obtener(job_id)
        if job is None:
            raise HTTPException(404, "Job inexistente")
        return job

    @app.get("/outbox", tags=["HITL"])
    async def bandeja_de_salida() -> list[dict[str, Any]]:
        return [json.loads(x) for x in await app.state.redis.lrange(OUTBOX, 0, -1)]

    @app.get("/salud", tags=["Operación"])
    async def salud() -> dict[str, Any]:
        await app.state.redis.ping()
        return {"redis": "ok", "workers": app.state.workers, "cola": await app.state.store.longitud_cola()}

    return app


app = create_app()
