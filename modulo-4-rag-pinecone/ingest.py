"""Pipeline de ingesta: documentos .md -> chunks con metadatos -> Pinecone.

Cada vector se guarda con el TEXTO ORIGINAL dentro de su metadata (campo ``text``),
de modo que recuperar un resultado no requiere consultar ninguna otra base de datos.

Uso:
    python ingest.py            # sube solo si el índice no está al día
    python ingest.py --force    # borra el namespace y vuelve a subir
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

import config
from embeddings import embedding_model_name

logger = logging.getLogger("rag.ingest")

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


# ------------------------------------------------------------------- carga
def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    """Separa el bloque ``---`` inicial (categoria / etiquetas) del cuerpo del documento."""
    m = _FRONT_MATTER.match(raw)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, raw[m.end():]


def load_documents(data_dir: Path = config.DATA_DIR) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(Path(data_dir).glob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        body = body.strip()
        if not body:
            continue
        etiquetas = [t.strip() for t in meta.get("etiquetas", "").split(",") if t.strip()]
        docs.append(
            Document(
                page_content=body,
                metadata={
                    "fuente": path.name,
                    "doc_id": path.stem,
                    "categoria": meta.get("categoria", "general"),
                    "etiquetas": etiquetas,
                },
            )
        )
    if not docs:
        raise FileNotFoundError(f"No hay archivos .md en {data_dir}")
    return docs


# --------------------------------------------------------------- chunking
def build_splitter() -> RecursiveCharacterTextSplitter:
    """Chunks de ~600 tokens (punto medio entre 500 y 800), cortando por estructura Markdown.

    Muy chicos pierden contexto semántico; muy grandes diluyen el embedding. Se
    corta primero por títulos y párrafos, y solo baja a líneas/frases si un bloque es muy largo.
    """
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=config.TOKEN_ENCODING,
        chunk_size=config.CHUNK_TOKENS,
        chunk_overlap=config.CHUNK_OVERLAP_TOKENS,
        separators=RecursiveCharacterTextSplitter.get_separators_for_language(Language.MARKDOWN),
    )


def split_documents(docs: list[Document], model: str | None = None) -> list[Document]:
    model = model or embedding_model_name()
    splitter = build_splitter()
    chunks: list[Document] = []
    for doc in docs:
        pieces = splitter.split_documents([doc])
        cursor = 0
        for i, piece in enumerate(pieces):
            # Se ubica el chunk en el documento buscando su inicio (``start_index`` de
            # LangChain devuelve -1 cuando no logra ubicarlo por el solapamiento en tokens).
            hallado = doc.page_content.find(piece.page_content[:80], max(cursor - 800, 0))
            start = cursor if hallado < 0 else hallado
            cursor = max(cursor, start)
            piece.metadata.pop("start_index", None)
            piece.metadata.update(
                chunk=i,
                chunks_en_doc=len(pieces),
                # Los .md no tienen páginas reales: se aproximan con ventanas de ~3000 caracteres.
                pagina=start // config.CHARS_PER_PAGE + 1,
                chunk_id=f"{doc.metadata['doc_id']}::{i}",
                embedding_model=model,
            )
            chunks.append(piece)
    return chunks


def fingerprint(chunks: list[Document]) -> str:
    """Huella del contenido y de los parámetros: decide si el índice está al día."""
    h = hashlib.sha256()
    h.update(f"{config.CHUNK_TOKENS}|{config.CHUNK_OVERLAP_TOKENS}|{config.EMBEDDING_DIMENSION}".encode())
    for c in chunks:
        h.update(c.metadata["chunk_id"].encode())
        h.update(c.metadata["embedding_model"].encode())
        h.update(c.page_content.encode())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ subida
def _existing_ids(index, ns: str) -> set[str]:
    """Ids que ya están en el namespace (``index.list`` pagina en lotes de ids)."""
    ids: set[str] = set()
    for batch in index.list(namespace=ns):
        ids.update(batch)
    return ids


def _stored_huella(index, ns: str, vector_id: str) -> str | None:
    got = index.fetch(ids=[vector_id], namespace=ns).vectors.get(vector_id)
    return (got.metadata or {}).get("huella") if got else None


def ingest(
    index,
    embeddings: Embeddings,
    *,
    data_dir: Path = config.DATA_DIR,
    ns: str | None = None,
    force: bool = False,
    batch_size: int = 20,
) -> int:
    """Sube los documentos a Pinecone. Devuelve la cantidad de chunks del namespace.

    Es **idempotente y reanudable**: si el namespace ya tiene este mismo contenido no
    hace nada, y si una ingesta anterior se cortó a mitad (p. ej. por un límite de la
    API de embeddings) solo sube los chunks que faltan, sin volver a pagar los demás.
    Si el contenido o los parámetros cambiaron (huella distinta), reconstruye el namespace.
    """
    ns = ns or config.namespace()
    chunks = split_documents(load_documents(data_dir))
    huella = fingerprint(chunks)
    for c in chunks:
        c.metadata["huella"] = huella
    wanted = {c.metadata["chunk_id"] for c in chunks}

    existentes: set[str] = set() if force else _existing_ids(index, ns)
    if existentes and _stored_huella(index, ns, next(iter(existentes))) != huella:
        logger.info("El contenido o los parámetros cambiaron: se reconstruye el namespace '%s'", ns)
        existentes = set()
        force = True
    if force:
        if _existing_ids(index, ns):
            index.delete(delete_all=True, namespace=ns)
    elif existentes - wanted:
        index.delete(ids=sorted(existentes - wanted), namespace=ns)  # chunks que ya no existen

    pendientes = [c for c in chunks if c.metadata["chunk_id"] not in existentes]
    if not pendientes:
        logger.info("Namespace '%s' al día (%d vectores): no se vuelve a subir", ns, len(chunks))
        return len(chunks)
    if existentes:
        logger.info("Retomando: %d de %d chunks ya estaban subidos", len(chunks) - len(pendientes), len(chunks))

    logger.info("Subiendo %d chunks a '%s' (lotes de %d)...", len(pendientes), ns, batch_size)
    store = PineconeVectorStore(index=index, embedding=embeddings, namespace=ns)  # texto en metadata["text"]
    for i in range(0, len(pendientes), batch_size):
        lote = pendientes[i : i + batch_size]
        store.add_documents(lote, ids=[c.metadata["chunk_id"] for c in lote], batch_size=batch_size)
        logger.info("  %d/%d chunks subidos", min(i + batch_size, len(pendientes)), len(pendientes))
    logger.info("Ingesta completa: %d vectores en el namespace '%s'", len(chunks), ns)
    return len(chunks)


if __name__ == "__main__":
    from dotenv import load_dotenv

    from embeddings import get_embeddings
    from setup_index import ensure_index, get_client

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="borra el namespace y vuelve a subir")
    args = ap.parse_args()
    ingest(ensure_index(get_client()), get_embeddings(), force=args.force)
