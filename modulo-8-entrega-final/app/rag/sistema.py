"""RAGSystem: recuperación **híbrida** y asíncrona (BM25 léxico + vectorial) con fusión RRF.

- **Vectorial** (Pinecone, cliente asyncio): capta paráfrasis y significado.
- **BM25**: acierta con términos exactos y códigos (``CD-``, «acuse», «Siniestros»).
- **Fusión**: Reciprocal Rank Fusion ponderada (``WEIGHTS`` = BM25, vectorial). Un fragmento hallado
  por ambos recuperadores suma los dos aportes.
- **Metadatos**: se filtra por ``categoria`` y por ``servicio`` (el filtro de servicio incluye siempre
  los documentos ``general``, que valen para todos). El filtro se aplica en BM25 y en Pinecone.

La parte vectorial es un ``BuscadorVectorial`` intercambiable: Pinecone en producción, un doble en los
tests, o ninguno (``RAG_BACKEND=local``: solo BM25, sin cuenta ni red).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Literal, Protocol

from langchain_core.embeddings import Embeddings
from rank_bm25 import BM25Okapi

from app import config
from app.schemas import Fragmento, ResultadoBusqueda

logger = logging.getLogger("rag.sistema")

_STOPWORDS = frozenset(
    "a al algo como con cual cuales cuando de del el en es esta este esto la las lo los me mi mis o para por "
    "que se si sin su sus un una uno unos unas y hace hacer puede pueden ya the of is to and in".split()
)
_TOKEN = re.compile(r"[a-z0-9_]+(?:-[a-z0-9_]+)*")


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sin tildes, sin palabras vacías. Los códigos con guion (``cd-100231``) se conservan
    enteros y también partidos (``cd``, ``100231``)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    out: list[str] = []
    for tok in _TOKEN.findall(t):
        partes = tok.split("-")
        for p in [tok] if len(partes) == 1 else [tok, *partes]:
            if p not in _STOPWORDS and len(p) > 1:
                out.append(p)
    return out


class BuscadorVectorial(Protocol):
    """Búsqueda por similitud: devuelve ``(chunk_id, similitud)`` ordenados de mayor a menor."""

    async def buscar(self, vector: list[float], k: int, filtro: dict[str, Any] | None) -> list[tuple[str, float]]: ...


Modo = Literal["hibrido", "lexico", "semantico"]


class RAGSystem:
    def __init__(
        self,
        fragmentos: list[Fragmento],
        *,
        embeddings: Embeddings | None = None,
        vectorial: BuscadorVectorial | None = None,
        k: int = config.TOP_K,
        candidatos: int = config.CANDIDATES,
        pesos: tuple[float, float] = config.WEIGHTS,
    ) -> None:
        if not fragmentos:
            raise ValueError("El RAG necesita al menos un fragmento")
        if (embeddings is None) != (vectorial is None):
            raise ValueError("embeddings y vectorial van juntos (o ninguno, para el modo solo léxico)")
        self.fragmentos = fragmentos
        self._por_id = {f.chunk_id: f for f in fragmentos}
        self.embeddings, self.vectorial = embeddings, vectorial
        self.k, self.candidatos, self.pesos = k, candidatos, pesos
        self._bm25: dict[tuple[str | None, str | None], tuple[list[Fragmento], BM25Okapi]] = {}

    @property
    def es_hibrido(self) -> bool:
        return self.vectorial is not None

    # ------------------------------------------------------------------ filtros
    def _elegibles(self, categoria: str | None, servicio: str | None) -> list[Fragmento]:
        return [
            f for f in self.fragmentos
            if (categoria is None or f.categoria == categoria)
            and (servicio is None or f.servicio in (servicio, "general"))
        ]

    @staticmethod
    def filtro_pinecone(categoria: str | None, servicio: str | None) -> dict[str, Any] | None:
        condiciones: list[dict[str, Any]] = []
        if categoria:
            condiciones.append({"categoria": {"$eq": categoria}})
        if servicio:
            condiciones.append({"servicio": {"$in": [servicio, "general"]}})
        if not condiciones:
            return None
        return condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}

    # --------------------------------------------------------------- recuperadores
    def _lexico(self, consulta: str, categoria: str | None, servicio: str | None) -> list[str]:
        clave = (categoria, servicio)
        if clave not in self._bm25:
            docs = self._elegibles(categoria, servicio)
            if not docs:
                return []
            self._bm25[clave] = (docs, BM25Okapi([tokenizar(f"{d.seccion} {d.texto}") for d in docs]))
        docs, bm25 = self._bm25[clave]
        puntajes = bm25.get_scores(tokenizar(consulta))  # CPU pura y de microsegundos: no necesita hilo aparte
        orden = sorted(range(len(docs)), key=lambda i: puntajes[i], reverse=True)[: self.candidatos]
        return [docs[i].chunk_id for i in orden if puntajes[i] > 0]

    async def _semantico(self, consulta: str, categoria: str | None, servicio: str | None) -> list[str]:
        assert self.vectorial is not None and self.embeddings is not None
        vector = await self.embeddings.aembed_query(consulta)
        hallados = await self.vectorial.buscar(vector, self.candidatos, self.filtro_pinecone(categoria, servicio))
        return [cid for cid, _ in hallados if cid in self._por_id]

    # ------------------------------------------------------------------ fusión
    def _fusionar(self, lexico: list[str], semantico: list[str]) -> list[tuple[str, float, list[str]]]:
        w_lex, w_sem = self.pesos
        puntaje: dict[str, float] = {}
        origen: dict[str, list[str]] = {}
        for ranking, peso, nombre in ((lexico, w_lex, "bm25"), (semantico, w_sem, "vectorial")):
            for rango, cid in enumerate(ranking, start=1):
                puntaje[cid] = puntaje.get(cid, 0.0) + peso / (config.RRF_C + rango)
                origen.setdefault(cid, []).append(nombre)
        orden = sorted(puntaje, key=lambda c: puntaje[c], reverse=True)
        return [(c, puntaje[c], origen[c]) for c in orden]

    # --------------------------------------------------------------------- API
    async def buscar(
        self, consulta: str, *, categoria: str | None = None, servicio: str | None = None,
        modo: Modo = "hibrido", k: int | None = None,
    ) -> list[ResultadoBusqueda]:
        """Top-k fragmentos relevantes. ``modo`` permite comparar léxico / semántico / híbrido en la evaluación."""
        k = k or self.k
        usar_sem = self.es_hibrido and modo in ("hibrido", "semantico")
        usar_lex = modo in ("hibrido", "lexico") or not usar_sem
        lexico = self._lexico(consulta, categoria, servicio) if usar_lex else []
        semantico = await self._semantico(consulta, categoria, servicio) if usar_sem else []
        fusion = self._fusionar(lexico, semantico)[:k]
        return [
            ResultadoBusqueda(
                fuente=self._por_id[c].fuente, seccion=self._por_id[c].seccion, categoria=self._por_id[c].categoria,
                servicio=self._por_id[c].servicio, texto=self._por_id[c].texto, puntaje=round(p, 5),
                encontrado_por=o,  # type: ignore[arg-type]
            )
            for c, p, o in fusion
        ]
