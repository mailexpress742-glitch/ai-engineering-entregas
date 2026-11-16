"""Orquestador multi-agente: supervisor + investigador + analista + sintetizador.

Uso:
    python main.py                       # corre la consulta de demostración
    python main.py "tu consulta"         # una consulta propia
    python main.py --guardar             # además guarda trazas/traza_ejemplo.{json,log}
    python main.py --mermaid             # imprime el diagrama Mermaid del grafo (sin LLM)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from graph import RECURSION_LIMIT, build_graph, mermaid
from llm import get_chat_model
from runner import ejecutar

TRAZAS_DIR = Path(__file__).resolve().parent / "trazas"

# Requiere DOS dominios: investigar en la documentación (datos) y calcular (análisis).
CONSULTA_DEMO = (
    "Según nuestra documentación de respuesta a incidentes, ¿cuál es el tiempo de respuesta de cada nivel de "
    "severidad (SEV1, SEV2 y SEV3)? Con esos datos calculá: (a) cuántas actualizaciones de estado debería "
    "publicar el equipo durante un incidente SEV1 que dura lo mismo que el RTO de las bases de datos de "
    "producción, y (b) el tiempo de respuesta total acumulado si en un mes ocurren 1 SEV1, 2 SEV2 y 3 SEV3."
)


async def principal(consulta: str, provider: str | None, guardar: bool) -> None:
    graph = build_graph(get_chat_model(provider, max_tokens=2048))
    estado, traza = await ejecutar(graph, consulta)

    print(f"\nFLUJO: {' -> '.join(traza.flujo())}  ({traza.duracion_s:.1f} s, límite de recursión {RECURSION_LIMIT})\n")
    print(traza.formato_log())
    if estado.get("advertencias"):
        print("\nADVERTENCIAS:", estado["advertencias"])
    if guardar:
        traza.guardar(TRAZAS_DIR, "traza_ejemplo")
        print(f"\nTraza guardada en {TRAZAS_DIR}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("consulta", nargs="?", default=CONSULTA_DEMO)
    ap.add_argument("--provider", choices=["anthropic", "openai"])
    ap.add_argument("--guardar", action="store_true")
    ap.add_argument("--mermaid", action="store_true")
    args = ap.parse_args()

    if args.mermaid:
        # El diagrama no necesita llamar a ningún modelo: se compila con piezas inertes.
        async def _nada(*_a, **_k):  # noqa: ANN002, ANN003
            raise RuntimeError("no se usa")

        print(mermaid(build_graph(decidir=_nada, investigador=_nada, analista=_nada, sintetizar=_nada)))
        raise SystemExit(0)

    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-7s %(message)s")
    asyncio.run(principal(args.consulta, args.provider, args.guardar))
