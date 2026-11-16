"""Verifica, punto por punto, el checklist de la Pre-entrega 5 contra el código y las trazas.

No usa red ni API keys. Cada línea indica dónde está la evidencia.

Uso:
    python verificar_entrega.py
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import get_type_hints

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.graph import MessagesState

import graph as modulo_grafo
import memoria
from tools import TOOLS

BASE = Path(__file__).resolve().parent
TRAZA_JSON = BASE / "trazas" / "traza_ejemplo.json"
PATRON_KEYS = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,}|pcsk_[A-Za-z0-9_]{20,}"
)

Resultado = tuple[bool, str]


def _grafo_compilado():
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult

    class _Mudo(BaseChatModel):  # modelo inerte: solo para compilar el grafo y mirar su forma
        @property
        def _llm_type(self) -> str:
            return "mudo"

        def bind_tools(self, tools, **kw):  # noqa: ANN001
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kw):  # noqa: ANN001
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

    return modulo_grafo.build_graph(_Mudo())


def _traza() -> dict:
    return json.loads(TRAZA_JSON.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------- chequeos
def python_312() -> Resultado:
    ok = sys.version_info >= (3, 12)
    return ok, f"Python {sys.version_info.major}.{sys.version_info.minor} (requerido >= 3.12; pyproject.toml: requires-python)"


def estado_hereda_messagesstate() -> Resultado:
    cls = modulo_grafo.EstadoAgente
    ok = MessagesState in cls.__orig_bases__  # TypedDict: no admite issubclass()
    return ok, f"graph.py: class {cls.__name__}(MessagesState) con campos {sorted(get_type_hints(cls))}"


def nodos_y_arista_condicional() -> Resultado:
    g = _grafo_compilado().get_graph()
    desde_agente = [e for e in g.edges if e.source == "agente"]
    condicional = any(e.conditional for e in desde_agente)
    ciclo = any(e.source == "tools" and e.target == "agente" for e in g.edges)
    ok = {"agente", "tools"} <= set(g.nodes) and condicional and ciclo
    return ok, "graph.py: nodos agente + tools, arista condicional tools_condition y retorno tools -> agente"


def usa_tools_condition_y_bind_tools() -> Resultado:
    src = inspect.getsource(modulo_grafo)
    ok = "tools_condition" in src and ".bind_tools(" in src
    return ok, "graph.py: add_conditional_edges('agente', tools_condition) y llm.bind_tools(TOOLS)"


def herramientas_con_tool() -> Resultado:
    ok = len(TOOLS) >= 1 and all(isinstance(t, BaseTool) and len(t.description) > 200 for t in TOOLS)
    return ok, f"tools.py: {len(TOOLS)} herramientas @tool con docstring descriptivo: {[t.name for t in TOOLS]}"


def persistencia_sqlite() -> Resultado:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: F401
    except ImportError as exc:
        return False, f"no se pudo importar el checkpointer: {exc}"
    if not memoria.DB_SNAPSHOT.exists():
        return False, f"falta {memoria.DB_SNAPSHOT.relative_to(BASE)}"
    sesiones = memoria.listar_sesiones(memoria.DB_SNAPSHOT)
    ok = len(sesiones) >= 2 and all(s["checkpoints"] > 0 for s in sesiones)
    return ok, (
        f"main.py: AsyncSqliteSaver (agente) + memoria.py: SqliteSaver (lectura). "
        f"{memoria.DB_SNAPSHOT.relative_to(BASE)} guarda {len(sesiones)} hilos: {[s['thread_id'] for s in sesiones]}"
    )


def thread_id_recuerda_la_sesion() -> Resultado:
    sesiones = {s["thread_id"]: s for s in memoria.listar_sesiones(memoria.DB_SNAPSHOT)}
    multi = sesiones.get("demo-multipaso")
    ok = bool(multi) and multi["turnos_del_usuario"] >= 2 and multi["mensajes"] > multi["turnos_del_usuario"]
    return ok, (
        "demo-multipaso conserva 2 turnos del usuario en el mismo thread_id "
        f"({multi['mensajes'] if multi else 0} mensajes)"
    )


def recursion_limit_definido() -> Resultado:
    import runner

    ok = modulo_grafo.RECURSION_LIMIT >= 1 and '"recursion_limit"' in inspect.getsource(runner)
    return ok, f"graph.py: RECURSION_LIMIT = {modulo_grafo.RECURSION_LIMIT}; runner.py lo pasa en config['recursion_limit']"


def traza_multipaso() -> Resultado:
    if not TRAZA_JSON.exists():
        return False, f"falta {TRAZA_JSON.relative_to(BASE)}"
    escenarios = _traza()["escenarios"]
    mejor = max(escenarios, key=lambda e: e["llamadas_a_herramientas"])
    ok = mejor["llamadas_a_herramientas"] >= 2
    return ok, (
        f"trazas/traza_ejemplo.json: '{mejor['thread_id']}' invoca herramientas "
        f"{mejor['llamadas_a_herramientas']} veces ({[p['herramienta'] for p in mejor['pasos'] if p['tipo'] == 'accion']})"
    )


def traza_con_reintento_tras_error() -> Resultado:
    for esc in _traza()["escenarios"]:
        acciones = [(p["herramienta"], json.dumps(p["argumentos"], sort_keys=True)) for p in esc["pasos"] if p["tipo"] == "accion"]
        obs = [p for p in esc["pasos"] if p["tipo"] == "observacion"]
        hubo_error = any(isinstance(o["resultado"], dict) and "error" in o["resultado"] for o in obs)
        if hubo_error and len(acciones) != len(set(acciones)):
            return True, f"trazas/traza_ejemplo.json: '{esc['thread_id']}' repite la misma llamada tras un error"
    return False, "ninguna traza muestra un reintento tras un error"


def trazas_en_log_y_json() -> Resultado:
    ok = TRAZA_JSON.exists() and (BASE / "trazas" / "traza_ejemplo.log").exists()
    return ok, "trazas/traza_ejemplo.json y trazas/traza_ejemplo.log"


def sin_api_keys() -> Resultado:
    hallazgos = []
    for ruta in BASE.rglob("*"):
        if ruta.is_file() and ".venv" not in ruta.parts and "__pycache__" not in ruta.parts \
                and ruta.suffix in {".py", ".md", ".json", ".log", ".toml", ".txt", ".example", ""}:
            try:
                if PATRON_KEYS.search(ruta.read_text(encoding="utf-8", errors="ignore")):
                    hallazgos.append(ruta.name)
            except OSError:
                pass
    try:
        versionados = subprocess.run(
            ["git", "ls-files", "--cached"], cwd=BASE, capture_output=True, text=True, check=True
        ).stdout.split()
        env_versionado = [f for f in versionados if f.split("/")[-1] == ".env"]
    except (OSError, subprocess.CalledProcessError):
        env_versionado = []
    ok = not hallazgos and not env_versionado
    return ok, f"ninguna API key en el código ni en las trazas; .env no versionado (hallazgos: {hallazgos or 'ninguno'})"


CHEQUEOS: list[tuple[str, Callable[[], Resultado]]] = [
    ("Python 3.12+", python_312),
    ("Estado hereda de MessagesState", estado_hereda_messagesstate),
    ("StateGraph: nodo modelo + nodo herramientas + arista condicional", nodos_y_arista_condicional),
    ("tools_condition y llm.bind_tools()", usa_tools_condition_y_bind_tools),
    ("Al menos 1 herramienta @tool con docstring", herramientas_con_tool),
    ("Persistencia con SqliteSaver", persistencia_sqlite),
    ("thread_id recuerda la sesión", thread_id_recuerda_la_sesion),
    ("recursion_limit definido", recursion_limit_definido),
    ("Prueba multi-paso (herramienta >= 2 veces)", traza_multipaso),
    ("Ciclo de retorno: reintento tras un error", traza_con_reintento_tras_error),
    ("Traza de ejemplo en .json y .log", trazas_en_log_y_json),
    ("Sin API keys en el repositorio", sin_api_keys),
]


def main() -> int:
    print("Verificación del checklist de la Pre-entrega 5\n")
    fallos = 0
    for nombre, fn in CHEQUEOS:
        try:
            ok, detalle = fn()
        except Exception as exc:  # noqa: BLE001 - un chequeo roto cuenta como fallo, no rompe el informe
            ok, detalle = False, f"{type(exc).__name__}: {exc}"
        fallos += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {nombre}\n         {detalle}")
    print(f"\n{len(CHEQUEOS) - fallos}/{len(CHEQUEOS)} puntos verificados")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
