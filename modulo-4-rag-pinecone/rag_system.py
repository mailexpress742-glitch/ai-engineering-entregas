"""RAGSystem: recuperador híbrido (BM25 léxico + vectorial en Pinecone) con EnsembleRetriever."""

from __future__ import annotations

import logging
import re
import unicodedata
import warnings
from collections.abc import Iterable

from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_pinecone import PineconeVectorStore

import config

with warnings.catch_warnings():  # langchain-community avisa que está en retiro; BM25Retriever sigue vigente
    warnings.simplefilter("ignore")
    from langchain_community.retrievers import BM25Retriever

logger = logging.getLogger("rag.system")

# ------------------------------------------------------------ tokenización BM25
_STOPWORDS = frozenset(
    "a al algo como con cual cuales cuando de del el en es esta este esto la las lo los me mi mis "
    "o para por que se si sin su sus un una uno unos unas y hago hace hacer puedo puede pueden "
    "sirve sirven the of is to and in it for on with a an".split()
)
_TOKEN = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")


def tokenize(text: str) -> list[str]:
    """Tokeniza para BM25 respetando términos técnicos.

    - Minúsculas y sin tildes («función» y «funcion» coinciden).
    - Los identificadores con puntos se conservan enteros y también partidos:
      ``asyncio.gather`` -> ``asyncio.gather``, ``asyncio``, ``gather``. Así una consulta
      que menciona ``gather`` encuentra el texto que dice ``asyncio.tasks.gather``.
    - Se descartan palabras vacías en español e inglés.
    """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    tokens: list[str] = []
    for tok in _TOKEN.findall(text):
        partes = tok.split(".")
        for t in ([tok] if len(partes) == 1 else [tok, *partes]):
            if t not in _STOPWORDS and len(t) > 1:
                tokens.append(t)
    return tokens


# --------------------------------------------------------------- corpus de BM25
def load_corpus(index, ns: str, *, batch: int = 50) -> list[Document]:
    """Reconstruye el corpus para BM25 leyendo el texto desde la metadata de Pinecone.

    Pinecone es la fuente de verdad: no hace falta tener los .md locales.
    """
    docs: list[Document] = []
    for ids in index.list(namespace=ns):
        for i in range(0, len(ids), batch):
            res = index.fetch(ids=list(ids[i : i + batch]), namespace=ns)
            for vid, vec in res.vectors.items():
                meta = dict(vec.metadata or {})
                text = meta.pop("text", "")
                if text:
                    docs.append(Document(page_content=text, metadata=meta, id=vid))
    return docs


# ------------------------------------------------------------------ RAGSystem
class RAGSystem:
    """Encapsula un ``EnsembleRetriever`` que fusiona BM25 y búsqueda vectorial (RRF).

    - **Vectorial (Pinecone):** capta paráfrasis y significado.
    - **BM25:** acierta con términos técnicos y nombres propios (``lru_cache``, ``TaskGroup``).
    - **Fusión:** Reciprocal Rank Fusion ponderada (``weights`` = BM25, vectorial).
    """

    def __init__(
        self,
        index,
        embeddings: Embeddings,
        *,
        namespace: str | None = None,
        k: int = config.TOP_K,
        candidates: int = config.CANDIDATES,
        weights: tuple[float, float] = config.WEIGHTS,
        corpus: Iterable[Document] | None = None,
    ) -> None:
        self.index = index
        self.embeddings = embeddings
        self.namespace = namespace or config.namespace()
        self.k = k
        self.candidates = candidates
        self.weights = weights
        self.corpus = list(corpus) if corpus is not None else load_corpus(index, self.namespace)
        if not self.corpus:
            raise RuntimeError(
                f"El namespace '{self.namespace}' está vacío: corré primero `python ingest.py`."
            )
        self._check_embedding_model()
        self._vector_store = PineconeVectorStore(index=index, embedding=embeddings, namespace=self.namespace)
        self._bm25_cache: dict[str | None, BM25Retriever] = {}
        logger.info("RAGSystem listo: %d chunks en BM25, namespace '%s'", len(self.corpus), self.namespace)

    # ----- verificación: mismo modelo de embeddings en ingesta y consulta -----
    def _check_embedding_model(self) -> None:
        from embeddings import embedding_model_name

        usados = {d.metadata.get("embedding_model") for d in self.corpus} - {None}
        esperado = embedding_model_name()
        if usados and usados != {esperado}:
            raise RuntimeError(
                f"El índice se generó con {sorted(usados)} pero se consulta con '{esperado}': "
                "las distancias no tendrían sentido. Reingestá con `python ingest.py --force`."
            )

    # ------------------------------------------------------------ recuperadores
    def _bm25(self, categoria: str | None) -> BM25Retriever:
        if categoria not in self._bm25_cache:
            docs = [d for d in self.corpus if categoria is None or d.metadata.get("categoria") == categoria]
            if not docs:
                raise ValueError(f"No hay documentos de la categoría '{categoria}'")
            self._bm25_cache[categoria] = BM25Retriever.from_documents(
                docs, preprocess_func=tokenize, k=self.candidates
            )
        return self._bm25_cache[categoria]

    def _vector(self, categoria: str | None) -> BaseRetriever:
        kwargs: dict = {"k": self.candidates}
        if categoria:
            kwargs["filter"] = {"categoria": {"$eq": categoria}}  # filtro por metadata en Pinecone
        return self._vector_store.as_retriever(search_kwargs=kwargs)

    def _ensemble(self, categoria: str | None) -> EnsembleRetriever:
        return EnsembleRetriever(
            retrievers=[self._bm25(categoria), self._vector(categoria)],
            weights=list(self.weights),
            id_key="chunk_id",  # un mismo chunk hallado por ambos se fusiona en uno
        )

    # -------------------------------------------------------------------- API
    def _top(self, docs: list[Document]) -> list[Document]:
        """Recorta a k y normaliza tipos: Pinecone devuelve los números de la metadata como float."""
        for d in docs[: self.k]:
            for campo in ("pagina", "chunk", "chunks_en_doc"):
                if isinstance(d.metadata.get(campo), float):
                    d.metadata[campo] = int(d.metadata[campo])
        return docs[: self.k]

    def retrieve(self, query: str, *, categoria: str | None = None) -> list[Document]:
        """Top-k documentos combinando resultados léxicos y semánticos."""
        return self._top(self._ensemble(categoria).invoke(query))

    async def aretrieve(self, query: str, *, categoria: str | None = None) -> list[Document]:
        return self._top(await self._ensemble(categoria).ainvoke(query))

    def retrieve_semantic(self, query: str, *, categoria: str | None = None) -> list[Document]:
        """Solo vectorial (para comparar en la evaluación)."""
        return self._top(self._vector(categoria).invoke(query))

    def retrieve_lexical(self, query: str, *, categoria: str | None = None) -> list[Document]:
        """Solo BM25 (para comparar en la evaluación)."""
        return self._top(self._bm25(categoria).invoke(query))
