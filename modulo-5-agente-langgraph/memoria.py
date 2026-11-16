"""Inspección de la memoria persistida: lee el archivo SQLite con ``SqliteSaver``.

El agente escribe sus checkpoints con ``AsyncSqliteSaver`` (la variante asíncrona, necesaria
porque el grafo corre con ``astream``/``ainvoke``). Este módulo abre el MISMO archivo con el
``SqliteSaver`` síncrono para comprobar, de forma independiente, qué quedó guardado por cada
``thread_id``.

Uso:
    python memoria.py                      # agente_memoria.sqlite (o la copia de trazas/)
    python memoria.py --db trazas/memoria_demo.sqlite
    python memoria.py --thread demo-multipaso   # además imprime el historial de ese hilo
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

BASE_DIR = Path(__file__).resolve().parent
DB_POR_DEFECTO = BASE_DIR / "agente_memoria.sqlite"
DB_SNAPSHOT = BASE_DIR / "trazas" / "memoria_demo.sqlite"


def _texto(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    return " ".join(b.get("text", "") for b in c if isinstance(b, dict))


def listar_sesiones(db: Path) -> list[dict[str, Any]]:
    """Una fila por ``thread_id``: cuántos checkpoints y mensajes tiene y qué dijo el usuario."""
    if not Path(db).exists():
        raise FileNotFoundError(f"No existe la base de memoria: {db}")
    ultimos: dict[str, Any] = {}
    cuenta: dict[str, int] = {}
    with SqliteSaver.from_conn_string(str(db)) as saver:
        for tupla in saver.list(None):  # todos los checkpoints, del más nuevo al más viejo
            tid = tupla.config["configurable"]["thread_id"]
            cuenta[tid] = cuenta.get(tid, 0) + 1
            ultimos.setdefault(tid, tupla)  # el primero que aparece es el más reciente
    filas = []
    for tid, tupla in sorted(ultimos.items()):
        valores = tupla.checkpoint["channel_values"]
        mensajes: list[BaseMessage] = valores.get("messages", [])
        usuario = [_texto(m) for m in mensajes if isinstance(m, HumanMessage)]
        filas.append(
            {
                "thread_id": tid,
                "checkpoints": cuenta[tid],
                "mensajes": len(mensajes),
                "turnos_del_usuario": len(usuario),
                "resultados_de_herramientas": sum(isinstance(m, ToolMessage) for m in mensajes),
                "llamadas_a_herramientas": valores.get("llamadas_a_herramientas", 0),
                "primera_pregunta": usuario[0] if usuario else "",
            }
        )
    return filas


def historial(db: Path, thread_id: str) -> list[BaseMessage]:
    """Mensajes del último checkpoint de un hilo."""
    with SqliteSaver.from_conn_string(str(db)) as saver:
        tupla = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    return list(tupla.checkpoint["channel_values"].get("messages", [])) if tupla else []


def db_existente() -> Path:
    return DB_POR_DEFECTO if DB_POR_DEFECTO.exists() else DB_SNAPSHOT


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path)
    ap.add_argument("--thread")
    args = ap.parse_args()
    ruta = args.db or db_existente()
    print(f"Memoria persistida en {ruta} (leída con SqliteSaver)\n")
    for f in listar_sesiones(ruta):
        print(
            f"- thread_id={f['thread_id']!r}: {f['checkpoints']} checkpoints, {f['mensajes']} mensajes, "
            f"{f['turnos_del_usuario']} turnos, {f['llamadas_a_herramientas']} llamadas a herramientas"
        )
        print(f"    primera pregunta: {f['primera_pregunta'][:90]}")
    if args.thread:
        print(f"\nHistorial de {args.thread!r}:")
        for m in historial(ruta, args.thread):
            print(f"  [{type(m).__name__}] {_texto(m)[:110]!r}")
