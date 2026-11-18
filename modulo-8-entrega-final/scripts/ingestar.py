"""Crea el índice de Pinecone (si falta) y sube la base de conocimiento de ``data/conocimiento/``.

    python scripts/ingestar.py            # idempotente: no vuelve a subir lo que ya está al día
    python scripts/ingestar.py --force    # borra el namespace y vuelve a subir todo
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app import config  # noqa: E402
from app.rag.embeddings import get_embeddings  # noqa: E402
from app.rag.ingesta import cargar_fragmentos, ingestar  # noqa: E402
from app.rag.pinecone_backend import PineconeVectorial, abrir_indice  # noqa: E402


async def main(force: bool) -> None:
    fragmentos = cargar_fragmentos()
    print(f"{len(fragmentos)} fragmentos de {len({f.fuente for f in fragmentos})} documentos")
    index, cerrar = await abrir_indice(crear=True)
    try:
        total = await ingestar(index, get_embeddings(), fragmentos, force=force)
        en_ns = await PineconeVectorial(index).contar()
        print(f"Índice '{config.index_name()}' · namespace '{config.namespace()}': {total} fragmentos ({en_ns} vectores en Pinecone)")
    finally:
        await cerrar()


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    asyncio.run(main(ap.parse_args().force))
