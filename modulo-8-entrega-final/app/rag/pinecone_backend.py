"""Pinecone con el cliente **asyncio** oficial (``PineconeAsyncio`` / ``IndexAsyncio``).

Ninguna llamada a la base vectorial bloquea el event loop. ``abrir_indice`` devuelve el índice listo y
una función para cerrar las conexiones; ``asegurar_indice`` lo crea (Serverless) solo si no existe y
valida que su dimensión coincida con la de los embeddings.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from pinecone import PineconeAsyncio, ServerlessSpec

from app import config

logger = logging.getLogger("rag.pinecone")


class PineconeConfigError(RuntimeError):
    """Falta la key o el índice existente no es compatible."""


def _api_key() -> str:
    key = os.getenv("PINECONE_API_KEY")
    if not key:
        raise PineconeConfigError("Falta PINECONE_API_KEY en el .env")
    return key


async def asegurar_indice(pc: PineconeAsyncio, nombre: str | None = None) -> str:
    """Crea el índice si no existe y devuelve su host."""
    nombre = nombre or config.index_name()
    if await pc.has_index(nombre):
        desc = await pc.describe_index(nombre)
        if int(desc.dimension) != config.EMBEDDING_DIMENSION:
            raise PineconeConfigError(
                f"El índice '{nombre}' tiene dimensión {desc.dimension} pero los embeddings son de "
                f"{config.EMBEDDING_DIMENSION}. Usá otro INDEX_NAME o borrá el índice."
            )
        return desc.host
    logger.info("Creando índice Serverless '%s' (dim=%d)...", nombre, config.EMBEDDING_DIMENSION)
    desc = await pc.create_index(
        name=nombre, dimension=config.EMBEDDING_DIMENSION, metric=config.METRIC,
        spec=ServerlessSpec(cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION),
    )
    return desc.host


async def abrir_indice(*, crear: bool = False) -> tuple[Any, Callable[[], Awaitable[None]]]:
    """Devuelve ``(IndexAsyncio, cerrar)``. ``crear=True`` crea el índice si falta (solo la ingesta lo necesita)."""
    pc = PineconeAsyncio(api_key=_api_key())
    try:
        if crear:
            host = await asegurar_indice(pc)
        else:
            nombre = config.index_name()
            if not await pc.has_index(nombre):
                raise PineconeConfigError(f"El índice '{nombre}' no existe: corré `python scripts/ingestar.py`.")
            host = (await pc.describe_index(nombre)).host
        index = pc.IndexAsyncio(host=host)
    except BaseException:
        await pc.close()
        raise

    async def cerrar() -> None:
        await index.close()
        await pc.close()

    return index, cerrar


class PineconeVectorial:
    """``BuscadorVectorial`` sobre un ``IndexAsyncio`` y un namespace."""

    def __init__(self, index: Any, namespace: str | None = None) -> None:
        self.index, self.namespace = index, namespace or config.namespace()

    async def buscar(self, vector: list[float], k: int, filtro: dict[str, Any] | None) -> list[tuple[str, float]]:
        res = await self.index.query(
            vector=vector, top_k=k, namespace=self.namespace, filter=filtro, include_metadata=False
        )
        return [(m.id, float(m.score)) for m in res.matches]

    async def contar(self) -> int:
        stats = await self.index.describe_index_stats()
        ns = (stats.namespaces or {}).get(self.namespace)
        return int(ns.vector_count) if ns else 0
