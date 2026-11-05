"""Inicialización de Pinecone: crea el índice Serverless solo si no existe.

Uso:
    python setup_index.py
"""

from __future__ import annotations

import logging
import os

from pinecone import Pinecone, ServerlessSpec

import config

logger = logging.getLogger("rag.setup")


class IndexConfigError(RuntimeError):
    """El índice existente no es compatible con la configuración (p. ej. dimensión)."""


def get_client() -> Pinecone:
    key = os.getenv("PINECONE_API_KEY")
    if not key:
        raise IndexConfigError("Falta PINECONE_API_KEY en el .env")
    return Pinecone(api_key=key)


def ensure_index(
    pc: Pinecone,
    name: str | None = None,
    *,
    dimension: int = config.EMBEDDING_DIMENSION,
    metric: str = config.METRIC,
):
    """Devuelve el ``Index`` listo para usar; lo crea (Serverless) si hace falta.

    Si ya existe, valida que su dimensión coincida con la de los embeddings: subir
    vectores de 1536 a un índice de 768 falla (o peor, se descarta en silencio), así
    que se aborta antes con un mensaje claro.
    """
    name = name or config.index_name()
    if pc.has_index(name):
        desc = pc.describe_index(name)
        if int(desc.dimension) != dimension:
            raise IndexConfigError(
                f"El índice '{name}' tiene dimensión {desc.dimension} pero los embeddings son de "
                f"{dimension}. Usá otro INDEX_NAME o borrá el índice."
            )
        if desc.metric != metric:
            logger.warning("El índice '%s' usa la métrica %s (se esperaba %s)", name, desc.metric, metric)
        logger.info("Índice '%s' ya existe (dimensión %s, métrica %s)", name, desc.dimension, desc.metric)
    else:
        logger.info(
            "Creando índice Serverless '%s' (dim=%d, %s, %s/%s)...",
            name, dimension, metric, config.PINECONE_CLOUD, config.PINECONE_REGION,
        )
        pc.create_index(
            name=name,
            dimension=dimension,
            metric=metric,
            spec=ServerlessSpec(cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION),
        )  # por defecto espera a que el índice esté listo
        logger.info("Índice '%s' creado", name)
    return pc.Index(name)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    index = ensure_index(get_client())
    print(index.describe_index_stats())
