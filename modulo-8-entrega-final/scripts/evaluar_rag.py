"""Evalúa la recuperación contra el golden set: Recall@k, Precision@k y MRR por modo (léxico / semántico / híbrido).

    python scripts/evaluar_rag.py            # usa Pinecone (necesita la ingesta hecha)
    python scripts/evaluar_rag.py --local    # solo BM25, sin red

Un acierto es que el DOCUMENTO esperado aparezca en el top-k (se deduplican los fragmentos del mismo documento).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app import config  # noqa: E402
from app.rag.sistema import RAGSystem  # noqa: E402


def docs_unicos(resultados) -> list[str]:
    vistos: list[str] = []
    for r in resultados:
        if r.fuente not in vistos:
            vistos.append(r.fuente)
    return vistos


def metricas(casos: list[dict], recuperados: list[list[str]], k: int) -> dict[str, float]:
    recall = precision = mrr = 0.0
    for caso, docs in zip(casos, recuperados, strict=True):
        esperados = set(caso["esperado"])
        top = docs[:k]
        aciertos = [d for d in top if d in esperados]
        recall += 1.0 if aciertos else 0.0  # ¿apareció al menos un documento correcto?
        precision += len(aciertos) / max(len(top), 1)
        mrr += next((1 / (i + 1) for i, d in enumerate(top) if d in esperados), 0.0)
    n = len(casos)
    return {f"Recall@{k}": round(recall / n, 3), f"Precision@{k}": round(precision / n, 3), "MRR": round(mrr / n, 3)}


async def main(local: bool, k: int) -> None:
    from app.rag.fabrica import crear_rag
    from app.rag.ingesta import cargar_fragmentos

    casos = json.loads(config.GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    if local:
        rag, cerrar = RAGSystem(cargar_fragmentos()), None
    else:
        rag, cerrar = await crear_rag()
    try:
        modos = ["lexico"] if not rag.es_hibrido else ["lexico", "semantico", "hibrido"]
        print(f"{len(casos)} preguntas · top-{k} · fragmentos deduplicados por documento\n")
        for modo in modos:
            recuperados = []
            for c in casos:
                r = await rag.buscar(c["pregunta"], categoria=c.get("categoria"), servicio=c.get("servicio"), modo=modo, k=k * 2)
                recuperados.append(docs_unicos(r))
            print(f"{modo:<10}", metricas(casos, recuperados, k))
    finally:
        if cerrar:
            await cerrar()


if __name__ == "__main__":
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--k", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(main(a.local, a.k))
