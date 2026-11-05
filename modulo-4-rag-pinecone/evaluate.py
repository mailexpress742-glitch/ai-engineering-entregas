"""Evaluación del recuperador con un golden set: Recall@k y Precision@k.

Uso:
    python evaluate.py                # compara híbrido vs. vectorial vs. BM25
    python evaluate.py --k 3
    python evaluate.py --solo-hibrido
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

import config


@dataclass
class Resultado:
    pregunta: str
    esperado: str
    recuperados: list[str]  # doc_id de cada chunk recuperado, en orden

    def hit(self, k: int) -> bool:
        return self.esperado in self.recuperados[:k]

    def precision(self, k: int) -> float:
        """Fracción de los k recuperados que pertenecen al documento esperado."""
        top = self.recuperados[:k]
        return sum(d == self.esperado for d in top) / k

    def rank(self, k: int) -> int | None:
        for i, d in enumerate(self.recuperados[:k], start=1):
            if d == self.esperado:
                return i
        return None


def load_golden_set(path: Path = config.GOLDEN_SET_PATH) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in data:
        if not {"pregunta", "documento_id_esperado"} <= item.keys():
            raise ValueError(f"Entrada inválida en el golden set: {item}")
    return data


def recall_at_k(resultados: list[Resultado], k: int) -> float:
    """Recall@k: proporción de preguntas cuyo documento correcto aparece entre los k recuperados."""
    return sum(r.hit(k) for r in resultados) / len(resultados)


def precision_at_k(resultados: list[Resultado], k: int) -> float:
    """Precision@k: promedio, por pregunta, del % de los k recuperados que son del documento correcto."""
    return sum(r.precision(k) for r in resultados) / len(resultados)


def mrr(resultados: list[Resultado], k: int) -> float:
    """Mean Reciprocal Rank: premia que el documento correcto aparezca más arriba."""
    return sum((1 / r.rank(k)) if r.rank(k) else 0 for r in resultados) / len(resultados)


def evaluar(
    golden: list[dict], retrieve: Callable[[str], list[Document]], k: int
) -> list[Resultado]:
    out = []
    for item in golden:
        docs = retrieve(item["pregunta"])[:k]
        out.append(
            Resultado(item["pregunta"], item["documento_id_esperado"], [d.metadata["doc_id"] for d in docs])
        )
    return out


def reporte(nombre: str, resultados: list[Resultado], k: int, *, detalle: bool) -> dict:
    metricas = {
        f"Recall@{k}": recall_at_k(resultados, k),
        f"Precision@{k}": precision_at_k(resultados, k),
        "MRR": mrr(resultados, k),
    }
    if detalle:
        print(f"\n--- {nombre}: detalle por pregunta")
        for r in resultados:
            marca = "OK " if r.hit(k) else "MAL"
            print(f"  [{marca}] esperado={r.esperado:<18} rank={r.rank(k) or '-'}  {r.pregunta[:70]}")
            if not r.hit(k):
                print(f"        recuperó: {r.recuperados[:k]}")
    return metricas


def main(k: int, solo_hibrido: bool) -> None:
    from dotenv import load_dotenv

    from embeddings import get_embeddings
    from rag_system import RAGSystem
    from setup_index import ensure_index, get_client

    load_dotenv()
    golden = load_golden_set()
    system = RAGSystem(ensure_index(get_client()), get_embeddings(), k=k)

    estrategias = {"Híbrido (BM25 + vectorial)": system.retrieve}
    if not solo_hibrido:
        estrategias["Solo vectorial (Pinecone)"] = system.retrieve_semantic
        estrategias["Solo léxico (BM25)"] = system.retrieve_lexical

    tabla: dict[str, dict] = {}
    for nombre, fn in estrategias.items():
        tabla[nombre] = reporte(nombre, evaluar(golden, fn, k), k, detalle=nombre.startswith("Híbrido"))

    print(f"\n=== Resultados sobre {len(golden)} preguntas (k={k}, namespace '{config.namespace()}')")
    cols = list(next(iter(tabla.values())))
    print(f"{'Estrategia':<30}" + "".join(f"{c:>13}" for c in cols))
    for nombre, m in tabla.items():
        print(f"{nombre:<30}" + "".join(f"{m[c]:>13.2f}" for c in cols))
    print(
        f"\nRecall@{k}: ¿está el documento correcto entre los {k} recuperados?  "
        f"Precision@{k}: % de los {k} recuperados que son del documento correcto."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=config.TOP_K)
    ap.add_argument("--solo-hibrido", action="store_true")
    args = ap.parse_args()
    main(args.k, args.solo_hibrido)
