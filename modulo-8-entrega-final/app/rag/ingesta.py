"""Ingesta: documentos ``.md`` → fragmentos con metadatos → Pinecone (asíncrona, idempotente).

Chunking por estructura: **un fragmento por sección ``##``** (cada uno conserva el título del documento
y de la sección, así la cita ``archivo#sección`` apunta exactamente a lo que se leyó). Solo una
sección que supera ``CHUNK_TOKENS`` se parte en trozos solapados.

Cada vector se guarda con el TEXTO dentro de su metadata, de modo que recuperar un resultado no
requiere consultar otra base. La ingesta es **idempotente y reanudable**: una huella del contenido y
de los parámetros decide si el namespace está al día.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import tiktoken
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import config
from app.rag.embeddings import embedding_model_name
from app.schemas import Fragmento

logger = logging.getLogger("rag.ingesta")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    m = _FRONT_MATTER.match(raw.replace("\r\n", "\n"))
    if not m:
        return {}, raw
    meta = {}
    for linea in m.group(1).splitlines():
        if ":" in linea:
            k, v = linea.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, raw.replace("\r\n", "\n")[m.end():]


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=config.TOKEN_ENCODING, chunk_size=config.CHUNK_TOKENS, chunk_overlap=config.CHUNK_OVERLAP_TOKENS
    )


def cargar_fragmentos(data_dir: Path | None = None, *, modelo: str | None = None) -> list[Fragmento]:
    """Lee los ``.md`` y devuelve los fragmentos (validados con Pydantic) listos para indexar."""
    data_dir = Path(data_dir or config.CONOCIMIENTO_DIR)
    try:
        modelo = modelo if modelo is not None else embedding_model_name()
    except Exception:  # noqa: BLE001 - sin proveedor de embeddings configurado (modo local / tests)
        modelo = ""
    splitter = _splitter()
    enc = tiktoken.get_encoding(config.TOKEN_ENCODING)
    fragmentos: list[Fragmento] = []
    for ruta in sorted(data_dir.glob("*.md")):
        meta, cuerpo = parse_front_matter(ruta.read_text(encoding="utf-8"))
        bloques = re.split(r"\n(?=## )", cuerpo.strip())
        titulo_doc = bloques[0].splitlines()[0].lstrip("# ").strip()
        etiquetas = [t.strip() for t in meta.get("etiquetas", "").split(",") if t.strip()]
        n = 0
        for i, bloque in enumerate(bloques):
            lineas = bloque.splitlines()
            titulo = lineas[0].lstrip("# ").strip() if i else titulo_doc
            texto = f"{titulo_doc} — {titulo}\n" + "\n".join(lineas[1:]).strip()
            trozos = [texto] if len(enc.encode(texto)) <= config.CHUNK_TOKENS else splitter.split_text(texto)
            for trozo in trozos:
                fragmentos.append(
                    Fragmento(
                        chunk_id=f"{ruta.stem}::{n}",
                        fuente=ruta.name,
                        seccion=titulo,
                        categoria=meta.get("categoria", "procedimiento"),  # type: ignore[arg-type]
                        servicio=meta.get("servicio", "general"),
                        etiquetas=etiquetas,
                        texto=trozo,
                        embedding_model=modelo,
                    )
                )
                n += 1
    if not fragmentos:
        raise FileNotFoundError(f"No hay archivos .md en {data_dir}")
    return fragmentos


def huella(fragmentos: list[Fragmento]) -> str:
    h = hashlib.sha256(f"{config.CHUNK_TOKENS}|{config.CHUNK_OVERLAP_TOKENS}|{config.EMBEDDING_DIMENSION}".encode())
    for f in fragmentos:
        h.update(f"{f.chunk_id}|{f.embedding_model}|{f.categoria}|{f.servicio}|{f.texto}".encode())
    return h.hexdigest()[:16]


def metadata_de(f: Fragmento, huella_: str) -> dict[str, Any]:
    return {
        "texto": f.texto, "fuente": f.fuente, "seccion": f.seccion, "categoria": f.categoria,
        "servicio": f.servicio, "etiquetas": f.etiquetas, "embedding_model": f.embedding_model, "huella": huella_,
    }


async def _ids_existentes(index: Any, ns: str) -> set[str]:
    ids: set[str] = set()
    async for lote in index.list(namespace=ns):
        ids.update(getattr(lote, "ids", None) or [getattr(v, "id", v) for v in getattr(lote, "vectors", lote)])
    return ids


async def ingestar(
    index: Any, embeddings: Embeddings, fragmentos: list[Fragmento], *, ns: str | None = None,
    force: bool = False, lote: int = 20,
) -> int:
    """Sube los fragmentos a Pinecone (``IndexAsyncio``). Devuelve la cantidad de vectores del namespace."""
    ns = ns or config.namespace()
    h = huella(fragmentos)
    queridos = {f.chunk_id for f in fragmentos}
    existentes: set[str] = set() if force else await _ids_existentes(index, ns)
    if existentes:
        un_id = next(iter(existentes))
        got = (await index.fetch(ids=[un_id], namespace=ns)).vectors.get(un_id)
        if ((got.metadata or {}).get("huella") if got else None) != h:
            logger.info("El contenido o los parámetros cambiaron: se reconstruye el namespace '%s'", ns)
            existentes, force = set(), True
    if force and await _ids_existentes(index, ns):
        await index.delete(delete_all=True, namespace=ns)
    elif existentes - queridos:
        await index.delete(ids=sorted(existentes - queridos), namespace=ns)

    pendientes = [f for f in fragmentos if f.chunk_id not in existentes]
    if not pendientes:
        logger.info("Namespace '%s' al día (%d vectores): no se vuelve a subir", ns, len(fragmentos))
        return len(fragmentos)
    logger.info("Subiendo %d fragmentos a '%s'...", len(pendientes), ns)
    for i in range(0, len(pendientes), lote):
        parte = pendientes[i : i + lote]
        vectores = await embeddings.aembed_documents([f.texto for f in parte])
        await index.upsert(
            vectors=[{"id": f.chunk_id, "values": v, "metadata": metadata_de(f, h)} for f, v in zip(parte, vectores, strict=True)],
            namespace=ns,
            show_progress=False,
        )
        logger.info("  %d/%d fragmentos subidos", min(i + lote, len(pendientes)), len(pendientes))
    return len(fragmentos)
