"""Consulta rápida al recuperador híbrido.

Uso:
    python query.py "¿Cómo guardo en caché una función?"
    python query.py "¿Cómo leo un archivo?" --categoria archivos_y_datos
"""

from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

from embeddings import get_embeddings
from rag_system import RAGSystem
from setup_index import ensure_index, get_client

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pregunta")
    ap.add_argument("--categoria", help="filtra por metadata: concurrencia, estructuras_de_datos, archivos_y_datos, texto, utilidades")
    args = ap.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    system = RAGSystem(ensure_index(get_client()), get_embeddings())
    for i, doc in enumerate(system.retrieve(args.pregunta, categoria=args.categoria), start=1):
        m = doc.metadata
        print(f"\n[{i}] {m['fuente']} · pág. {m['pagina']} · chunk {m['chunk']} · {m['categoria']} · {m['etiquetas']}")
        print("    " + " ".join(doc.page_content.split())[:220] + "...")
