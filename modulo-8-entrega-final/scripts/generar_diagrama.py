"""Regenera ``grafo.mmd`` (el diagrama Mermaid del grafo de agentes que se incluye en el README).

    python scripts/generar_diagrama.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import build_graph, mermaid  # noqa: E402
from app.supervisor import DecisionLLM  # noqa: E402


async def _nada(_entrada):
    return {"contenido": "", "herramientas_usadas": [], "fuentes": []}


async def _decidir(_estado):
    return DecisionLLM(razon="", siguiente="sintetizador")


async def _sintetizar(_estado):
    return ""


if __name__ == "__main__":
    grafo = build_graph(decidir=_decidir, investigador=_nada, analista=_nada, ejecutor=_nada, sintetizar=_sintetizar)
    destino = Path(__file__).resolve().parent.parent / "grafo.mmd"
    destino.write_text(mermaid(grafo), encoding="utf-8")
    print(destino.read_text(encoding="utf-8"))
