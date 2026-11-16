"""Worker: saca jobs de la cola Redis, corre el grafo y deja el resultado en Redis.

Corre como tareas asyncio dentro del proceso de la API (``WORKERS=n``) o como proceso aparte
(``python -m app.worker``): ambos hablan solo con Redis, así que escalan igual.

Garantías:
- Cualquier excepción del agente deja el job en ``FAILED`` con el error (el cliente nunca queda
  esperando para siempre).
- Un job que supera ``JOB_TIMEOUT_S`` pasa a ``FAILED`` por timeout.
- Si el proceso muere con jobs en ``RUNNING``, al reiniciar se los reanuda desde su último
  checkpoint de Redis (``recuperar_huerfanos``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.graph import RECURSION_LIMIT
from app.observability import observar
from app.store import AWAITING_APPROVAL, DONE, FAILED, RUNNING, ColaTrabajos, JobStore

logger = logging.getLogger("worker")
TIMEOUT_POR_DEFECTO_S = float(os.getenv("JOB_TIMEOUT_S", "300"))


def resumen_resultado(estado: dict[str, Any]) -> dict[str, Any]:
    """Lo que la API devuelve al cliente: respuesta + procedencia (quién aportó qué)."""
    return {
        "respuesta_final": estado.get("respuesta_final", ""),
        "task_completed": bool(estado.get("task_completed")),
        "pasos_del_supervisor": estado.get("pasos", 0),
        "flujo": [d["siguiente"] for d in estado.get("decisiones", [])],
        "contribuciones": [
            {"agente": c["agente"], "version": c["version"], "herramientas": c["herramientas_usadas"], "fuentes": c["fuentes"]}
            for c in estado.get("contribuciones", [])
        ],
        "advertencias": estado.get("advertencias", []),
        "aprobacion": estado.get("aprobacion"),
    }


class Worker:
    def __init__(
        self, graph: CompiledStateGraph, store: JobStore, cola: ColaTrabajos, *, timeout_s: float = TIMEOUT_POR_DEFECTO_S
    ) -> None:
        self.graph, self.store, self.cola, self.timeout_s = graph, store, cola, timeout_s

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                msg = await self.cola.tomar(timeout_s=1)
            except Exception:  # noqa: BLE001 - Redis caído un momento: reintentar, no morir
                logger.exception("Error leyendo la cola; reintento")
                await asyncio.sleep(1)
                continue
            if msg:
                await self.procesar(msg)

    async def procesar(self, msg: dict[str, Any]) -> None:
        job_id = msg["job_id"]
        try:
            await asyncio.wait_for(self._ejecutar(job_id, msg), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            await self._fallar(job_id, f"Timeout: el job superó {self.timeout_s:.0f} s")
        except asyncio.CancelledError:
            raise  # apagado del servicio: el job queda RUNNING y se reanuda al reiniciar
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del agente → FAILED
            logger.exception("El job %s falló", job_id)
            await self._fallar(job_id, f"{type(exc).__name__}: {exc}")

    async def _fallar(self, job_id: str, error: str) -> None:
        await self.store.actualizar(job_id, status=FAILED, error=error, finished_at=time.time())

    @observar("job")
    async def _ejecutar(self, job_id: str, msg: dict[str, Any]) -> None:
        job = await self.store.obtener(job_id)
        if job is None:
            logger.warning("Job %s inexistente; se descarta", job_id)
            return
        await self.store.actualizar(job_id, status=RUNNING)
        if "started_at" not in job:
            await self.store.actualizar(job_id, started_at=time.time())

        config = {
            "configurable": {"thread_id": job_id},  # el thread_id ES el job_id: los checkpoints cuelgan de él
            "recursion_limit": RECURSION_LIMIT,
            "run_name": "orquestador",
            "metadata": {"session_id": job_id, "job_id": job_id},  # Phoenix agrupa las trazas por sesión
        }
        tipo = msg.get("tipo", "run")
        if tipo == "run":
            entrada: Any = {"messages": [HumanMessage(job["consulta"])]}
        elif tipo == "resume":
            entrada = Command(resume={"aprobado": msg["aprobado"], "comentario": msg.get("comentario", "")})
        else:  # "continue": reanudar tras la caída del proceso, desde el último checkpoint
            entrada = None
        estado = await self.graph.ainvoke(entrada, config)

        snap = await self.graph.aget_state(config)
        pendientes = [i for t in snap.tasks for i in t.interrupts]
        if pendientes:  # el grafo se pausó en el nodo de aprobación humana
            await self.store.actualizar(job_id, status=AWAITING_APPROVAL, aprobacion_pendiente=pendientes[0].value)
            return
        await self.store.actualizar(job_id, status=DONE, resultado=resumen_resultado(estado), finished_at=time.time())


async def recuperar_huerfanos(store: JobStore, cola: ColaTrabajos) -> int:
    """Reencola los jobs que quedaron RUNNING (el proceso anterior murió): continúan desde su checkpoint."""
    ids = await store.jobs_en_estado(RUNNING)
    for job_id in ids:
        await cola.encolar(job_id, "continue")
    return len(ids)


async def _main() -> None:
    """Proceso worker independiente: ``python -m app.worker`` (comparte Redis con la API)."""
    from dotenv import load_dotenv

    from app.graph import build_graph
    from app.llm import get_chat_model
    from app.observability import init_observability
    from app.redis_checkpointer import AsyncRedisCheckpointer
    from redis.asyncio import Redis

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r_txt, r_bin = Redis.from_url(url, decode_responses=True), Redis.from_url(url)
    init_observability()
    store = JobStore(r_txt)
    graph = build_graph(get_chat_model(max_tokens=2048), checkpointer=AsyncRedisCheckpointer(r_bin))
    await Worker(graph, store, ColaTrabajos(store)).run_forever(asyncio.Event())


if __name__ == "__main__":
    asyncio.run(_main())
