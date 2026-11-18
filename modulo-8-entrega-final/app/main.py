"""API REST de la Mesa de reclamos MailEx (FastAPI, async).

    POST /reclamos                 → encola el reclamo y devuelve {job_id} al instante (202). NO ejecuta el agente.
    GET  /reclamos/{job_id}        → estado (PENDING/RUNNING/AWAITING_APPROVAL/DONE/FAILED) y resultado.
    POST /reclamos/{job_id}/aprobar → resuelve la aprobación humana de la respuesta/escalamiento (ver hitl.py).
    GET  /bandeja                  → acciones que el ejecutor realizó (solo ocurren tras aprobar).
    POST /conocimiento/buscar      → consulta directa al RAG híbrido (útil para depurar la recuperación).
    GET  /salud                    → Redis, RAG, workers y cola.

El endpoint solo escribe en Redis; el trabajo pesado lo hacen los workers (``app/worker.py``), así
el event loop de la API nunca se bloquea con llamadas al LLM. Toda entrada y salida usa modelos
Pydantic (``app/schemas.py``): lo inválido se rechaza con 422 antes de tocar el negocio.
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
from redis.asyncio import Redis

from app.agents.action_agent import configurar_salida
from app.graph import build_graph
from app.hitl import router as hitl_router
from app.llm import get_chat_model
from app.observability import init_observability
from app.rag.fabrica import crear_rag
from app.redis_checkpointer import AsyncRedisCheckpointer
from app.schemas import (
    BusquedaConocimientoIn,
    EnvioRegistrado,
    NuevoReclamo,
    ReclamoCreado,
    ReclamoEstado,
    ResultadoBusqueda,
    Salud,
)
from app.store import ColaTrabajos, JobStore
from app.worker import Worker, recuperar_huerfanos

logger = logging.getLogger("api")
OUTBOX = "outbox"

RedisFactory = Callable[[bool], Redis]  # decode_responses → cliente


def _redis_desde_entorno(decode: bool) -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=decode)


async def calentar(rag: Any, llm: Any) -> None:
    """Abre las conexiones (embeddings, Pinecone, proveedor del LLM) y carga el tokenizador ANTES de recibir tráfico.

    Sin esto, el primer reclamo después de arrancar paga la inicialización perezosa (TLS, tiktoken, clientes
    HTTP) dentro del event loop y retrasa a los demás durante un par de segundos. Si falla, solo se avisa.
    """
    try:
        await rag.buscar("calentamiento")
        await llm.ainvoke("Respondé solo: ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("El calentamiento falló (%s: %s); el primer reclamo será más lento", type(exc).__name__, exc)


def create_app(
    *,
    graph: Any | None = None,
    redis_factory: RedisFactory | None = None,
    workers: int | None = None,
    rag: Any | None = None,
) -> FastAPI:
    """Fábrica de la app. ``graph``/``redis_factory``/``workers``/``rag`` se inyectan en los tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()
        factory = redis_factory or _redis_desde_entorno
        r_txt, r_bin = factory(True), factory(False)  # str para jobs/cola; bytes para los checkpoints
        await r_txt.ping()
        store = JobStore(r_txt)
        cola = ColaTrabajos(store)
        app.state.store, app.state.cola, app.state.redis = store, cola, r_txt
        app.state.rag = rag

        async def registrar_envio(registro: dict[str, Any]) -> None:
            await r_txt.rpush(OUTBOX, json.dumps(registro, ensure_ascii=False))

        configurar_salida(registrar_envio)

        n = workers if workers is not None else int(os.getenv("WORKERS", "5"))
        tareas: list[asyncio.Task] = []
        stop = asyncio.Event()
        cerrar_rag = None
        app.state.workers = n
        if n > 0:
            g = graph
            if g is None:
                app.state.rag, cerrar_rag = await crear_rag()
                llm = get_chat_model(max_tokens=2048)
                await calentar(app.state.rag, llm)  # antes de instrumentar: el calentamiento no ensucia Phoenix con trazas sueltas
                init_observability()
                g = build_graph(llm, rag=app.state.rag, exigir_accion=True, checkpointer=AsyncRedisCheckpointer(r_bin))
            else:
                init_observability()
            worker = Worker(g, store, cola)
            if os.getenv("RECUPERAR_AL_INICIAR", "1") == "1":
                recuperados = await recuperar_huerfanos(store, cola)
                if recuperados:
                    logger.warning("Se reanudan %d reclamos que quedaron RUNNING", recuperados)
            tareas = [asyncio.create_task(worker.run_forever(stop), name=f"worker-{i}") for i in range(n)]
        try:
            yield
        finally:
            stop.set()
            for t in tareas:
                t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            if cerrar_rag:
                await cerrar_rag()
            await r_txt.aclose()
            await r_bin.aclose()

    opciones: dict[str, Any] = {
        "title": "Mesa de reclamos MailEx · The Intelligence System",
        "version": "1.0",
        "description": "RAG híbrido + agentes con supervisor + aprobación humana + Redis + trazas en Phoenix.",
        "lifespan": lifespan,
    }
    try:
        # FastAPI recientes emiten spans OpenTelemetry por request: con el polling de GET /reclamos/{id} llenarían
        # Phoenix de trazas de 10 ms y ensuciarían la latencia. Solo queremos las trazas de los reclamos.
        app = FastAPI(**opciones, telemetry={"tracing": False})
    except TypeError:  # versiones sin ese parámetro (no emiten esos spans)
        app = FastAPI(**opciones)
    app.include_router(hitl_router)

    @app.post("/reclamos", status_code=202, response_model=ReclamoCreado, tags=["Reclamos"])
    async def crear_reclamo(reclamo: NuevoReclamo) -> ReclamoCreado:
        """Registra el reclamo como PENDING en Redis, lo encola y responde sin esperar a los agentes."""
        job_id = await app.state.store.crear(reclamo.como_consulta())
        await app.state.cola.encolar(job_id, "run")
        return ReclamoCreado(job_id=job_id)

    @app.get("/reclamos/{job_id}", response_model=ReclamoEstado, response_model_exclude_none=True, tags=["Reclamos"])
    async def estado_reclamo(job_id: str) -> dict[str, Any]:
        job = await app.state.store.obtener(job_id)
        if job is None:
            raise HTTPException(404, "Reclamo inexistente")
        return job

    @app.get("/bandeja", response_model=list[EnvioRegistrado], tags=["HITL"])
    async def bandeja_de_salida() -> list[dict[str, Any]]:
        """Respuestas al cliente y escalamientos realizados por el ejecutor (siempre tras una aprobación)."""
        return [json.loads(x) for x in await app.state.redis.lrange(OUTBOX, 0, -1)]

    @app.post("/conocimiento/buscar", response_model=list[ResultadoBusqueda], tags=["RAG"])
    async def buscar_conocimiento(q: BusquedaConocimientoIn) -> list[ResultadoBusqueda]:
        """Consulta directa al RAG híbrido (BM25 + Pinecone) con filtros por metadatos."""
        if app.state.rag is None:
            raise HTTPException(503, "El RAG no está inicializado en este proceso")
        return await app.state.rag.buscar(q.consulta, categoria=q.categoria, servicio=q.servicio, k=q.max_resultados)

    @app.get("/salud", response_model=Salud, tags=["Operación"])
    async def salud() -> Salud:
        await app.state.redis.ping()
        r = app.state.rag
        modo = "no iniciado" if r is None else ("hibrido (bm25 + pinecone)" if r.es_hibrido else "solo lexico (bm25)")
        return Salud(redis="ok", rag=modo, workers=app.state.workers, cola=await app.state.store.longitud_cola())

    return app


app = create_app()
