"""Agente ReAct con memoria persistente (LangGraph + AsyncSqliteSaver).

Uso:
    python main.py --demo                                  # corre los escenarios y guarda las trazas
    python main.py --thread ana --pregunta "¿Cuántos pedidos tuvo el cliente 102?"
    python main.py --thread ana --pregunta "¿y el último?"    # recuerda el contexto (mismo thread_id)
    python main.py --thread ana                            # modo interactivo
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from graph import RECURSION_LIMIT, build_graph
from llm import get_chat_model
from runner import Traza, ejecutar_turno
from tools import reset_fallos

BASE_DIR = Path(__file__).resolve().parent
TRAZAS_DIR = BASE_DIR / "trazas"

# Escenarios del demo: (thread_id, [preguntas del mismo hilo]).
ESCENARIOS: dict[str, list[str]] = {
    "multipaso": [
        "¿Cuántos pedidos tuvo el cliente 102, cuál fue el total y qué productos incluyó su último pedido?",
        "¿y el pedido anterior a ese, cuánto costó?",  # sin repetir el cliente: usa la memoria
    ],
    "aclaracion_y_reintento": [
        "¿Qué compró Lucía en su último pedido?",  # ambiguo: hay dos Lucías -> pide aclaración
        "Lucía Fernández",  # responde la aclaración; el detalle del pedido falla una vez y se reintenta
    ],
    "error_cliente_inexistente": [
        "¿Cuántos pedidos tiene el cliente 999?",
    ],
}


def db_path(arg: str | None) -> Path:
    return Path(arg or os.getenv("CHECKPOINT_DB", BASE_DIR / "agente_memoria.sqlite"))


async def correr_demo(provider: str | None, db: Path) -> None:
    """Ejecuta los escenarios con una base de memoria nueva y guarda la traza completa."""
    for sufijo in ("", "-wal", "-shm"):
        Path(f"{db}{sufijo}").unlink(missing_ok=True)
    reset_fallos()
    TRAZAS_DIR.mkdir(exist_ok=True)

    todas: list[dict] = []
    log_lines: list[str] = []
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_graph(get_chat_model(provider), saver)
        for nombre, preguntas in ESCENARIOS.items():
            traza = Traza(thread_id=f"demo-{nombre}")
            print(f"\n{'=' * 70}\nEscenario: {nombre}  (thread_id={traza.thread_id})\n{'=' * 70}")
            for pregunta in preguntas:
                respuesta = await ejecutar_turno(graph, pregunta, traza.thread_id, traza=traza)
                print(f"\n> {pregunta}\n< {respuesta}")
            todas.append(traza.a_dict())
            log_lines.append(traza.formato_react())
            print(f"\nHerramientas usadas ({len(traza.herramientas_usadas())}): {traza.herramientas_usadas()}")

    import json

    (TRAZAS_DIR / "traza_ejemplo.json").write_text(
        json.dumps({"recursion_limit": RECURSION_LIMIT, "escenarios": todas}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (TRAZAS_DIR / "traza_ejemplo.log").write_text("\n\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nTrazas guardadas en {TRAZAS_DIR}")


async def conversar(provider: str | None, db: Path, thread_id: str, pregunta: str | None) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_graph(get_chat_model(provider), saver)
        if pregunta:
            print(await ejecutar_turno(graph, pregunta, thread_id))
            return
        print(f"Sesión '{thread_id}' (memoria en {db.name}). Línea vacía para salir.")
        while entrada := (await asyncio.to_thread(input, "\nVos: ")).strip():
            print(f"Agente: {await ejecutar_turno(graph, entrada, thread_id)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="corre los escenarios y guarda las trazas")
    ap.add_argument("--thread", default="default", help="thread_id de la sesión (memoria)")
    ap.add_argument("--pregunta")
    ap.add_argument("--provider", choices=["anthropic", "openai", "gemini"])
    ap.add_argument("--db", help="archivo SQLite de la memoria")
    args = ap.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    for ruidoso in ("httpx", "httpx2", "aiosqlite"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    if args.demo:
        asyncio.run(correr_demo(args.provider, db_path(args.db)))
    else:
        asyncio.run(conversar(args.provider, db_path(args.db), args.thread, args.pregunta))
