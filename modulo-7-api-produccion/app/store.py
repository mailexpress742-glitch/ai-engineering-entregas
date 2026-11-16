"""Estado de los jobs y cola de trabajo, ambos en Redis.

- ``job:{id}`` (hash): estado del job. Es lo que lee ``GET /tasks/{id}``.
- ``jobs:queue`` (lista): cola FIFO de mensajes para los workers (RPUSH / BLPOP).

Estados: PENDING → RUNNING → DONE | FAILED, con el desvío RUNNING → AWAITING_APPROVAL → RUNNING
cuando el grafo se pausa para aprobación humana (``hitl.py``).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import WatchError

PENDING, RUNNING, AWAITING_APPROVAL, DONE, FAILED = "PENDING", "RUNNING", "AWAITING_APPROVAL", "DONE", "FAILED"
ESTADOS_FINALES = frozenset({DONE, FAILED})
COLA = "jobs:queue"
TTL_JOB_S = 7 * 24 * 3600  # los jobs se conservan una semana


def _clave(job_id: str) -> str:
    return f"job:{job_id}"


class JobStore:
    """``client`` debe usar ``decode_responses=True``."""

    def __init__(self, client: Redis) -> None:
        self.r = client

    async def crear(self, consulta: str) -> str:
        job_id = uuid.uuid4().hex
        ahora = time.time()
        await self.r.hset(
            _clave(job_id),
            mapping={"job_id": job_id, "status": PENDING, "consulta": consulta, "created_at": ahora, "updated_at": ahora},
        )
        await self.r.expire(_clave(job_id), TTL_JOB_S)
        return job_id

    async def actualizar(self, job_id: str, **campos: Any) -> None:
        campos = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in campos.items()}
        campos["updated_at"] = time.time()
        await self.r.hset(_clave(job_id), mapping=campos)

    async def obtener(self, job_id: str) -> dict[str, Any] | None:
        crudo = await self.r.hgetall(_clave(job_id))
        if not crudo:
            return None
        job: dict[str, Any] = dict(crudo)
        for campo in ("resultado", "aprobacion_pendiente"):
            if job.get(campo):
                job[campo] = json.loads(job[campo])
            else:
                job.pop(campo, None)
        for campo in ("created_at", "updated_at", "started_at", "finished_at"):
            if campo in job:
                job[campo] = float(job[campo])
        return job

    async def jobs_en_estado(self, *estados: str) -> list[str]:
        """IDs de los jobs en esos estados (recorre ``job:*``; pensado para el arranque, no para el camino caliente)."""
        ids = []
        async for k in self.r.scan_iter(match="job:*"):
            if await self.r.hget(k, "status") in estados:
                ids.append(k.split(":", 1)[1])
        return ids

    async def longitud_cola(self) -> int:
        return await self.r.llen(COLA)


class ColaTrabajos:
    """Cola de mensajes ``{job_id, tipo, ...}`` para los workers."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.r = store.r

    async def encolar(self, job_id: str, tipo: str = "run", **extra: Any) -> None:
        await self.r.rpush(COLA, json.dumps({"job_id": job_id, "tipo": tipo, **extra}))

    async def tomar(self, timeout_s: int = 1) -> dict[str, Any] | None:
        item = await self.r.blpop([COLA], timeout=timeout_s)
        return json.loads(item[1]) if item else None

    async def resolver_aprobacion(self, job_id: str, aprobado: bool, comentario: str) -> str:
        """Pasa AWAITING_APPROVAL → RUNNING de forma atómica y reencola el job.

        Devuelve "ok", "no_existe" o "no_pendiente". Con WATCH, dos aprobaciones simultáneas del mismo job
        no pueden reanudarlo dos veces: la segunda ve el estado ya cambiado.
        """
        clave = _clave(job_id)
        async with self.r.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(clave)
                estado = await pipe.hget(clave, "status")
                if estado is None:
                    return "no_existe"
                if estado != AWAITING_APPROVAL:
                    return "no_pendiente"
                pipe.multi()
                pipe.hset(clave, mapping={"status": RUNNING, "updated_at": time.time()})
                pipe.hdel(clave, "aprobacion_pendiente")
                await pipe.execute()
            except WatchError:
                return "no_pendiente"
        await self.encolar(job_id, "resume", aprobado=aprobado, comentario=comentario)
        return "ok"
