"""Checkpointer de LangGraph sobre Redis **estándar** (sin módulos RediSearch/RedisJSON).

Por qué existe: ``langgraph-checkpoint-redis`` (el ``RedisSaver`` oficial) exige Redis Stack
(módulos de búsqueda e índices). Este checkpointer implementa el mismo contrato
(``BaseCheckpointSaver``) usando solo hashes de Redis, así que funciona con la imagen
``redis:7`` común, con Redis gestionado y con ``fakeredis`` en los tests.

Modelo de datos (todas las claves cuelgan de ``{prefijo}:{tipo}:{thread_id}:{namespace}``):

- ``ck``  hash  checkpoint_id → checkpoint + metadata + id del padre (el árbol de checkpoints).
- ``bl``  hash  "{canal}\\x1f{versión}" → valor serializado del canal (los blobs).
- ``wr:{checkpoint_id}``  hash  "{task_id}\\x1f{idx}" → escrituras pendientes (incluye las
  ``interrupt`` del human-in-the-loop: por eso una ejecución pausada sobrevive a un reinicio).

La serialización la hace ``self.serde`` (la de LangGraph), igual que los demás checkpointers.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    writes_sort_key,
)
from redis.asyncio import Redis

SEP = "\x1f"


def _pack(typed: tuple[str, bytes]) -> bytes:
    """(tipo, bytes) → bytes únicos para guardar en un campo de hash."""
    return typed[0].encode() + b"\n" + typed[1]


def _unpack(raw: bytes) -> tuple[str, bytes]:
    tipo, _, datos = raw.partition(b"\n")
    return tipo.decode(), datos


class AsyncRedisCheckpointer(BaseCheckpointSaver[str]):
    """Checkpointer asíncrono. ``client`` debe crearse SIN ``decode_responses`` (se guardan bytes)."""

    def __init__(self, client: Redis, *, prefix: str = "lg", ttl_seconds: int | None = None) -> None:
        super().__init__()
        self.client = client
        self.prefix = prefix
        self.ttl = ttl_seconds

    # ------------------------------------------------------------------ claves
    def _k(self, tipo: str, thread_id: str, ns: str, extra: str = "") -> str:
        return f"{self.prefix}:{tipo}:{thread_id}:{ns}" + (f":{extra}" if extra else "")

    async def _touch(self, *claves: str) -> None:
        if self.ttl:
            for c in claves:
                await self.client.expire(c, self.ttl)

    # ------------------------------------------------------------------- lectura
    async def _armar(self, thread_id: str, ns: str, checkpoint_id: str, raw: bytes) -> CheckpointTuple:
        cp_raw, md_raw, parent = (json.loads(raw)[k] for k in ("cp", "md", "parent"))
        checkpoint: Checkpoint = self.serde.loads_typed(_unpack(base64.b64decode(cp_raw)))
        metadata = self.serde.loads_typed(_unpack(base64.b64decode(md_raw)))

        valores: dict[str, Any] = {}
        versiones: ChannelVersions = checkpoint["channel_versions"]
        if versiones:
            campos = [f"{canal}{SEP}{ver}" for canal, ver in versiones.items()]
            blobs = await self.client.hmget(self._k("bl", thread_id, ns), campos)
            for canal, blob in zip(versiones, blobs, strict=True):
                if blob is None:
                    continue
                tipo, datos = _unpack(blob)
                if tipo != "empty":
                    valores[canal] = self.serde.loads_typed((tipo, datos))

        escrituras = await self.client.hgetall(self._k("wr", thread_id, ns, checkpoint_id))
        filas = []
        for campo, v in escrituras.items():
            task_id, idx = campo.decode().split(SEP)
            d = json.loads(v)
            filas.append((d["p"], task_id, int(idx), d["c"], (d["ty"], base64.b64decode(d["b"]))))
        filas.sort(key=lambda f: writes_sort_key(f[0], f[1], f[2]))
        pendientes = [(tid, canal, self.serde.loads_typed(t)) for _, tid, _, canal, t in filas]

        return CheckpointTuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id}},
            checkpoint={**checkpoint, "channel_values": valores},
            metadata=metadata,
            pending_writes=pendientes,
            parent_config=(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": parent}}
                if parent
                else None
            ),
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        clave = self._k("ck", thread_id, ns)
        if checkpoint_id is None:
            ids = await self.client.hkeys(clave)
            if not ids:
                return None
            checkpoint_id = max(i.decode() for i in ids)  # los ids son monótonos (uuid6)
        raw = await self.client.hget(clave, checkpoint_id)
        if raw is None:
            return None
        return await self._armar(thread_id, ns, checkpoint_id, raw)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return  # listar todos los hilos no se usa en este proyecto
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        filtro_id = get_checkpoint_id(config)
        antes = get_checkpoint_id(before) if before else None
        datos = await self.client.hgetall(self._k("ck", thread_id, ns))
        devueltos = 0
        for cid in sorted((k.decode() for k in datos), reverse=True):
            if filtro_id and cid != filtro_id:
                continue
            if antes and cid >= antes:
                continue
            tupla = await self._armar(thread_id, ns, cid, datos[cid.encode()])
            if filter and not all(tupla.metadata.get(k) == v for k, v in filter.items()):
                continue
            if limit is not None and devueltos >= limit:
                break
            devueltos += 1
            yield tupla

    # ------------------------------------------------------------------ escritura
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        c = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        valores: dict[str, Any] = c.pop("channel_values")  # type: ignore[misc]

        async with self.client.pipeline(transaction=True) as pipe:
            for canal, ver in new_versions.items():
                typed = self.serde.dumps_typed(valores[canal]) if canal in valores else ("empty", b"")
                pipe.hset(self._k("bl", thread_id, ns), f"{canal}{SEP}{ver}", _pack(typed))
            registro = {
                "cp": base64.b64encode(_pack(self.serde.dumps_typed(c))).decode(),
                "md": base64.b64encode(
                    _pack(self.serde.dumps_typed(get_checkpoint_metadata(config, metadata)))
                ).decode(),
                "parent": config["configurable"].get("checkpoint_id"),
            }
            pipe.hset(self._k("ck", thread_id, ns), checkpoint["id"], json.dumps(registro))
            await pipe.execute()
        await self._touch(self._k("bl", thread_id, ns), self._k("ck", thread_id, ns))
        return {
            "configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint["id"]}
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        clave = self._k("wr", thread_id, ns, config["configurable"]["checkpoint_id"])
        for idx, (canal, valor) in enumerate(writes):
            indice = WRITES_IDX_MAP.get(canal, idx)
            campo = f"{task_id}{SEP}{indice}"
            tipo, datos = self.serde.dumps_typed(valor)
            registro = json.dumps({"c": canal, "ty": tipo, "b": base64.b64encode(datos).decode(), "p": task_path})
            if indice >= 0:
                await self.client.hsetnx(clave, campo, registro)  # las escrituras normales no se pisan
            else:
                await self.client.hset(clave, campo, registro)  # interrupts/errores se sobrescriben
        await self._touch(clave)

    async def adelete_thread(self, thread_id: str) -> None:
        async for clave in self.client.scan_iter(match=f"{self.prefix}:*:{thread_id}:*"):
            await self.client.delete(clave)

    # --------------------------------------------- versión síncrona: no soportada
    # Este checkpointer es solo asíncrono (como el de Postgres async): se usa con ``ainvoke``.
    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError("AsyncRedisCheckpointer es asíncrono: usá aget_tuple / ainvoke.")

    def put(self, *a: Any, **k: Any) -> RunnableConfig:
        raise NotImplementedError("AsyncRedisCheckpointer es asíncrono: usá aput / ainvoke.")

    def put_writes(self, *a: Any, **k: Any) -> None:
        raise NotImplementedError("AsyncRedisCheckpointer es asíncrono: usá aput_writes / ainvoke.")

    def list(self, *a: Any, **k: Any):  # type: ignore[override]
        raise NotImplementedError("AsyncRedisCheckpointer es asíncrono: usá alist.")
