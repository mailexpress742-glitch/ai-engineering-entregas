"""Construye el ``RAGSystem`` según el entorno (``RAG_BACKEND``): híbrido con Pinecone o solo léxico."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app import config
from app.rag.embeddings import get_embeddings
from app.rag.ingesta import cargar_fragmentos
from app.rag.pinecone_backend import PineconeVectorial, abrir_indice
from app.rag.sistema import RAGSystem

logger = logging.getLogger("rag.fabrica")


async def crear_rag() -> tuple[RAGSystem, Callable[[], Awaitable[None]]]:
    """Devuelve ``(rag, cerrar)``; ``cerrar`` libera las conexiones de Pinecone al apagar el servicio."""
    fragmentos = cargar_fragmentos()
    if config.rag_backend() == "local":
        logger.warning("RAG_BACKEND=local: recuperación SOLO léxica (BM25), sin Pinecone")

        async def nada() -> None:
            return None

        return RAGSystem(fragmentos), nada

    index, cerrar = await abrir_indice()
    try:
        vectorial = PineconeVectorial(index)
        en_pinecone = await vectorial.contar()
        if en_pinecone == 0:
            raise RuntimeError(
                f"El namespace '{config.namespace()}' del índice '{config.index_name()}' está vacío: "
                "corré primero `python scripts/ingestar.py`."
            )
        if en_pinecone != len(fragmentos):
            logger.warning(
                "Pinecone tiene %d vectores pero hay %d fragmentos locales: reingestá con `python scripts/ingestar.py`",
                en_pinecone, len(fragmentos),
            )
        rag = RAGSystem(fragmentos, embeddings=get_embeddings(), vectorial=vectorial)
    except BaseException:
        await cerrar()
        raise
    logger.info("RAG híbrido listo: %d fragmentos, índice '%s', namespace '%s'", len(fragmentos), config.index_name(), config.namespace())
    return rag, cerrar
