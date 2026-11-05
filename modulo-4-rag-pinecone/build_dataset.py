"""Genera data/*.md con la documentación (docstrings) de módulos de la biblioteca estándar.

Se corre una sola vez; los .md resultantes están versionados en el repo para que el
dataset sea reproducible aunque cambie la versión de Python instalada.
    python build_dataset.py
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# módulo -> (categoría, etiquetas)
MODULOS: dict[str, tuple[str, list[str]]] = {
    "asyncio.tasks": ("concurrencia", ["asyncio", "tareas", "gather", "timeout"]),
    "asyncio.queues": ("concurrencia", ["asyncio", "colas", "productor-consumidor"]),
    "asyncio.locks": ("concurrencia", ["asyncio", "locks", "semaforo", "evento"]),
    "asyncio.taskgroups": ("concurrencia", ["asyncio", "taskgroup", "cancelacion"]),
    "asyncio.timeouts": ("concurrencia", ["asyncio", "timeout", "deadline"]),
    "threading": ("concurrencia", ["hilos", "locks", "threads"]),
    "collections": ("estructuras_de_datos", ["deque", "counter", "defaultdict", "namedtuple"]),
    "heapq": ("estructuras_de_datos", ["heap", "cola-de-prioridad"]),
    "itertools": ("estructuras_de_datos", ["iteradores", "combinaciones", "agrupar"]),
    "functools": ("estructuras_de_datos", ["cache", "partial", "reduce", "decoradores"]),
    "pathlib": ("archivos_y_datos", ["rutas", "archivos", "path"]),
    "json": ("archivos_y_datos", ["serializacion", "json", "dumps", "loads"]),
    "csv": ("archivos_y_datos", ["csv", "lectura", "escritura"]),
    "re": ("texto", ["regex", "expresiones-regulares", "match"]),
    "textwrap": ("texto", ["wrap", "indentacion", "formato"]),
    "logging": ("utilidades", ["logs", "handlers", "niveles"]),
    "argparse": ("utilidades", ["cli", "argumentos", "linea-de-comandos"]),
    "dataclasses": ("utilidades", ["dataclass", "field", "clases"]),
    "contextlib": ("utilidades", ["context-manager", "with", "closing"]),
    "statistics": ("utilidades", ["media", "mediana", "desviacion"]),
}


def _firma(obj: object) -> str:
    try:
        return str(inspect.signature(obj))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "(...)"


def _publicos(mod) -> list[tuple[str, object]]:
    nombres = getattr(mod, "__all__", None) or [n for n in dir(mod) if not n.startswith("_")]
    out = []
    for n in nombres:
        obj = getattr(mod, n, None)
        if (inspect.isfunction(obj) or inspect.isclass(obj)) and getattr(obj, "__module__", "") == mod.__name__:
            out.append((n, obj))
    return out


def documentar(nombre: str, categoria: str, etiquetas: list[str]) -> str:
    mod = importlib.import_module(nombre)
    partes = [
        "---",
        f"categoria: {categoria}",
        f"etiquetas: {', '.join(etiquetas)}",
        "---",
        f"# Módulo `{nombre}`",
        "",
        inspect.getdoc(mod) or "",
    ]
    for n, obj in _publicos(mod):
        doc = inspect.getdoc(obj)
        if not doc:
            continue
        tipo = "clase" if inspect.isclass(obj) else "función"
        partes += ["", f"## {tipo} `{nombre}.{n}{_firma(obj)}`", "", doc]
        if inspect.isclass(obj):
            for m, meth in inspect.getmembers(obj, inspect.isfunction):
                mdoc = inspect.getdoc(meth)
                if m.startswith("_") or not mdoc or meth.__qualname__.split(".")[0] != obj.__name__:
                    continue
                partes += ["", f"### método `{n}.{m}{_firma(meth)}`", "", mdoc]
    return "\n".join(partes).strip() + "\n"


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    total = 0
    for nombre, (cat, tags) in MODULOS.items():
        texto = documentar(nombre, cat, tags)
        (DATA_DIR / f"{nombre}.md").write_text(texto, encoding="utf-8")
        total += len(texto)
        print(f"{nombre:<22} {len(texto):>7} caracteres")
    print(f"TOTAL {total} caracteres (~{total // 4} tokens)")
