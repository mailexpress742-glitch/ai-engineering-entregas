"""Agente investigador: consulta la base de conocimiento (documentos de pre-entregas anteriores).

La "fuente externa" es un índice BM25 sobre los documentos de ``data/`` (el manual interno
de Nubra Cloud del Módulo 3). Sus herramientas son de solo lectura y acotadas a la búsqueda.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent  # sucesor de langgraph.prebuilt.create_react_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool
from rank_bm25 import BM25Okapi

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

INVESTIGADOR_PROMPT = (
    "Sos el INVESTIGADOR de un equipo. Tu única tarea es encontrar información en la "
    "documentación interna usando tus herramientas y reportarla con precisión.\n"
    "- Buscá siempre con `buscar_documentacion`; no respondas de memoria ni inventes datos.\n"
    "- Podés hacer varias búsquedas con consultas distintas si la primera no alcanza.\n"
    "- Reportá los datos EXACTOS (cifras, unidades, nombres) tal como figuran, y citá la fuente "
    "como `archivo#sección`.\n"
    "- NO hagas cálculos ni análisis: de eso se ocupa el analista. Si algo no está en los "
    "documentos, decilo explícitamente en vez de suponerlo.\n"
    "- Respondé en español, en formato claro (lista o tabla)."
)


# ------------------------------------------------------------------ índice BM25
_STOP = frozenset(
    "a al algo como con cual cuales cuando de del el en es esta este la las lo los me mi o para por "
    "que se si sin su sus un una uno y hay son ser the of is to and in".split()
)
_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenizar(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [w for w in _TOKEN.findall(t) if w not in _STOP and len(w) > 1]


@dataclass(frozen=True)
class Seccion:
    fuente: str
    seccion: str
    texto: str


def cargar_secciones(data_dir: Path = DATA_DIR) -> list[Seccion]:
    """Un fragmento por sección ``##`` de cada documento (cada uno conserva su título)."""
    out: list[Seccion] = []
    for ruta in sorted(Path(data_dir).glob("*.md")):
        bloques = re.split(r"\n(?=## )", ruta.read_text(encoding="utf-8").strip())
        titulo_doc = bloques[0].splitlines()[0].lstrip("# ").strip()
        for i, b in enumerate(bloques):
            titulo = b.splitlines()[0].lstrip("# ").strip() if i else titulo_doc
            out.append(Seccion(ruta.name, titulo, b.strip()))
    return out


class IndiceBM25:
    def __init__(self, secciones: list[Seccion]) -> None:
        self.secciones = secciones
        self._bm25 = BM25Okapi([tokenizar(f"{s.seccion} {s.texto}") for s in secciones])

    def buscar(self, consulta: str, k: int = 3) -> list[tuple[Seccion, float]]:
        puntajes = self._bm25.get_scores(tokenizar(consulta))
        orden = sorted(range(len(puntajes)), key=lambda i: puntajes[i], reverse=True)[:k]
        return [(self.secciones[i], float(puntajes[i])) for i in orden if puntajes[i] > 0]


_indice: IndiceBM25 | None = None


def _get_indice() -> IndiceBM25:
    global _indice
    if _indice is None:
        _indice = IndiceBM25(cargar_secciones())
    return _indice


# ------------------------------------------------------------------ herramientas
@tool
def listar_documentos() -> dict[str, Any]:
    """Lista los documentos de la base de conocimiento y las secciones de cada uno.

    Usala UNA vez al empezar si no sabés qué documentación existe, para decidir qué buscar.
    Devuelve `{"documentos": [{"fuente": "archivo.md", "secciones": [str, ...]}, ...]}`.
    No devuelve el contenido: para eso usá `buscar_documentacion`.
    """
    por_doc: dict[str, list[str]] = {}
    for s in _get_indice().secciones:
        por_doc.setdefault(s.fuente, []).append(s.seccion)
    return {"documentos": [{"fuente": f, "secciones": sec} for f, sec in por_doc.items()]}


@tool
def buscar_documentacion(consulta: str, max_resultados: int = 3) -> dict[str, Any]:
    """Busca en la documentación interna las secciones más relevantes para una consulta.

    Usala para obtener datos concretos (tiempos, retenciones, niveles de severidad, pasos de un
    procedimiento, responsables). Escribí la consulta con palabras clave del tema, por ejemplo
    "severidad tiempo de respuesta SEV1" o "retención snapshot diario".

    Devuelve `{"resultados": [{"fuente": "archivo.md", "seccion": "título", "texto": "...",
    "puntaje": float}, ...]}` ordenados por relevancia. El `texto` es la sección completa
    (puede incluir tablas). Si no hay coincidencias devuelve `{"resultados": [], "sugerencia": ...}`:
    probá con otras palabras clave.
    """
    k = max(1, min(int(max_resultados), 5))
    hallados = _get_indice().buscar(consulta, k)
    if not hallados:
        return {"resultados": [], "sugerencia": "Sin coincidencias: probá con otras palabras clave."}
    return {
        "resultados": [
            {"fuente": s.fuente, "seccion": s.seccion, "texto": s.texto[:2500], "puntaje": round(p, 2)}
            for s, p in hallados
        ]
    }


INVESTIGADOR_TOOLS = [listar_documentos, buscar_documentacion]


def crear_investigador(llm: BaseChatModel):
    """Agente ReAct del investigador (herramientas acotadas a la búsqueda)."""
    return create_agent(llm, INVESTIGADOR_TOOLS, system_prompt=INVESTIGADOR_PROMPT, name="investigador")
