"""Ingesta: carga documentos de /data, los fragmenta y los persiste en ChromaDB.

Uso:
    python ingest.py               # indexa solo si hace falta
    python ingest.py --rebuild     # fuerza la reindexación
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from config import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TOKENS,
    COLLECTION_NAME,
    DATA_DIR,
    EMBEDDING_MODEL,
    TOKEN_ENCODING,
    VECTORSTORE_DIR,
)

logger = logging.getLogger("rag.ingest")

EXTENSIONES = {".md", ".txt"}


# ------------------------------------------------------------------- carga
def load_documents(data_dir: Path = DATA_DIR) -> list[Document]:
    """Lee todos los .md y .txt de la carpeta (orden alfabético, determinista)."""
    docs = []
    for path in sorted(Path(data_dir).glob("*")):
        if path.suffix.lower() in EXTENSIONES and path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                docs.append(Document(page_content=text, metadata={"source": path.name}))
    if not docs:
        raise FileNotFoundError(f"No hay archivos .md o .txt en {data_dir}")
    return docs


# --------------------------------------------------------------- chunking
def build_splitter() -> RecursiveCharacterTextSplitter:
    """Splitter recursivo que mide en tokens y respeta la estructura Markdown.

    Corta primero por títulos y párrafos, y solo si un bloque excede los 500 tokens
    baja a líneas, frases y palabras. Así los fragmentos conservan sentido completo
    (una sección, una tabla) en vez de cortar a mitad de una idea.
    """
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=TOKEN_ENCODING,
        chunk_size=CHUNK_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        separators=RecursiveCharacterTextSplitter.get_separators_for_language(Language.MARKDOWN),
    )


def split_documents(docs: list[Document]) -> list[Document]:
    chunks: list[Document] = []
    splitter = build_splitter()
    for doc in docs:
        pieces = splitter.split_documents([doc])
        for i, piece in enumerate(pieces):
            piece.metadata = {**doc.metadata, "chunk": i, "chunks_en_archivo": len(pieces)}
            chunks.append(piece)
    return chunks


# ------------------------------------------------------------ persistencia
def fingerprint(docs: list[Document]) -> str:
    """Huella del contenido + parámetros que afectan al índice.

    Si cambia un documento, el chunking o el modelo de embeddings, la huella cambia
    y el índice se reconstruye; si no, se reutiliza el que ya está en disco.
    """
    h = hashlib.sha256()
    h.update(f"{EMBEDDING_MODEL}|{CHUNK_TOKENS}|{CHUNK_OVERLAP_TOKENS}|{TOKEN_ENCODING}".encode())
    for doc in docs:
        h.update(doc.metadata["source"].encode())
        h.update(doc.page_content.encode())
    return h.hexdigest()


def ensure_index(
    embeddings: Embeddings,
    *,
    data_dir: Path = DATA_DIR,
    persist_dir: Path = VECTORSTORE_DIR,
    rebuild: bool = False,
) -> Chroma:
    """Devuelve el vector store, indexando solo si no existe o quedó desactualizado."""
    docs = load_documents(data_dir)
    huella = fingerprint(docs)
    client = chromadb.PersistentClient(path=str(persist_dir))

    existente = next((c for c in client.list_collections() if c.name == COLLECTION_NAME), None)
    vigente = (
        existente is not None
        and existente.count() > 0
        and (existente.metadata or {}).get("fingerprint") == huella
    )

    def abrir() -> Chroma:
        return Chroma(
            client=client,
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            collection_metadata={
                "fingerprint": huella,
                "embedding_model": EMBEDDING_MODEL,
                "hnsw:space": "cosine",
            },
        )

    if vigente and not rebuild:
        logger.info("Índice existente y vigente (%d fragmentos): no se reindexa", existente.count())
        return abrir()

    if existente is not None:
        logger.info("Reconstruyendo el índice (%s)", "forzado" if rebuild else "datos cambiados")
        client.delete_collection(COLLECTION_NAME)

    chunks = split_documents(docs)
    logger.info("%d documentos -> %d fragmentos; generando embeddings...", len(docs), len(chunks))
    store = abrir()
    store.add_documents(chunks, ids=[f"{c.metadata['source']}::{c.metadata['chunk']}" for c in chunks])
    logger.info("Índice guardado en %s", persist_dir)
    return store


if __name__ == "__main__":
    from dotenv import load_dotenv

    from embeddings import get_embeddings

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="fuerza la reindexación")
    args = parser.parse_args()
    ensure_index(get_embeddings(), rebuild=args.rebuild)
