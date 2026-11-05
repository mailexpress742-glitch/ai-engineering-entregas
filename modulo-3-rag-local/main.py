"""Demo end-to-end: ingesta (si hace falta) + una pregunta con respuesta y una trampa.

Uso:
    python main.py                                   # las dos pruebas del enunciado
    python main.py --pregunta "¿Cuál es el RPO?"     # una pregunta propia
    python main.py --rebuild                         # fuerza reindexar
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from dotenv import load_dotenv

from embeddings import get_embeddings
from ingest import ensure_index
from llm import get_chat_model
from rag import RagError, build_chain, get_rag_response

# Prueba 1: la respuesta SÍ está en los documentos (política de backups).
PREGUNTA_CON_RESPUESTA = "¿Cada cuánto se hacen los snapshots de las bases de datos y cuánto tiempo se guardan?"
# Prueba 2: pregunta trampa, suena a lo que hay en los documentos pero NO está.
PREGUNTA_TRAMPA = "¿Cuántos días de vacaciones le corresponden a una persona recién ingresada a Nubra Cloud?"


def mostrar(titulo: str, resp) -> None:
    print(f"\n=== {titulo}\n{resp.model_dump_json(indent=2)}")


async def main(pregunta: str | None, rebuild: bool, provider: str | None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    for ruidoso in ("httpx", "httpx2", "chromadb", "posthog"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    store = ensure_index(get_embeddings(), rebuild=rebuild)
    chain = build_chain(get_chat_model(provider))
    ask = lambda q: get_rag_response(q, store=store, chain=chain)  # noqa: E731

    try:
        if pregunta:
            mostrar("Respuesta", await ask(pregunta))
            return 0

        r1, r2 = await asyncio.gather(ask(PREGUNTA_CON_RESPUESTA), ask(PREGUNTA_TRAMPA))
    except RagError as exc:
        print(f"\nERROR controlado: {exc}")
        return 1

    mostrar(f"Prueba 1 (está en los documentos): {PREGUNTA_CON_RESPUESTA}", r1)
    mostrar(f"Prueba 2 (pregunta trampa): {PREGUNTA_TRAMPA}", r2)

    ok1, ok2 = r1.en_contexto and bool(r1.referencias), not r2.en_contexto
    print(f"\nPrueba 1 responde con fuentes: {'OK' if ok1 else 'FALLÓ'}")
    print(f"Prueba 2 no alucina ('No lo sé'): {'OK' if ok2 else 'FALLÓ'}")
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pregunta")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--provider", choices=["anthropic", "openai", "gemini"])
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.pregunta, args.rebuild, args.provider)))
