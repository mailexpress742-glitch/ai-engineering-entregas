"""Tests sin red ni cuentas: Pinecone y embeddings falsos."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

import config
import ingest
import setup_index
from evaluate import Resultado, load_golden_set, mrr, precision_at_k, recall_at_k
from rag_system import RAGSystem, tokenize

MODEL = "gemini-embedding-001"


# ------------------------------------------------------------------ fakes
class FakeEmbeddings(Embeddings):
    def _vec(self, text):
        v = [0.0] * 16
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 16] += 1.0
        return v

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


class FakeIndex:
    """Imita lo mínimo del Index de Pinecone que usa la ingesta."""

    def __init__(self):
        self.vectors: dict[str, dict] = {}
        self.upserts = 0
        self.config = SimpleNamespace(host="fake.pinecone.test", api_key="fake")

    def upsert(self, vectors, namespace="", **kw):
        self.upserts += 1
        for v in vectors:  # el SDK acepta tuplas (id, valores, metadata) o diccionarios
            vid, meta = (v[0], v[2]) if isinstance(v, tuple) else (v["id"], v["metadata"])
            self.vectors[vid] = {"namespace": namespace, "metadata": meta}
        # con async_req=True el SDK real devuelve un objeto con .get()
        return SimpleNamespace(get=lambda *a, **k: SimpleNamespace(upserted_count=len(vectors)))

    def describe_index_stats(self):
        n = len(self.vectors)
        ns = {config.namespace(): SimpleNamespace(vector_count=n)} if n else {}
        return SimpleNamespace(namespaces=ns)

    def fetch(self, ids, namespace=""):
        return SimpleNamespace(
            vectors={i: SimpleNamespace(metadata=self.vectors[i]["metadata"]) for i in ids if i in self.vectors}
        )

    def delete(self, delete_all=False, ids=None, namespace=""):
        if delete_all:
            self.vectors.clear()
        for i in ids or []:
            self.vectors.pop(i, None)

    def list(self, namespace=""):
        ids = sorted(self.vectors)
        for i in range(0, len(ids), 30):
            yield ids[i : i + 30]


class FakePinecone:
    def __init__(self, existing: dict | None = None):
        self.indexes = existing or {}
        self.created: list[dict] = []

    def has_index(self, name):
        return name in self.indexes

    def describe_index(self, name):
        return self.indexes[name]

    def create_index(self, **kw):
        self.created.append(kw)
        self.indexes[kw["name"]] = SimpleNamespace(dimension=kw["dimension"], metric=kw["metric"])

    def Index(self, name):  # noqa: N802 - igual que el SDK
        return FakeIndex()


class StaticRetriever(BaseRetriever):
    """Retriever vectorial falso que devuelve siempre los mismos documentos."""

    docs: list[Document]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun):
        return self.docs


def doc(doc_id: str, texto: str, i: int = 0, categoria: str = "utilidades") -> Document:
    return Document(
        page_content=texto,
        metadata={"doc_id": doc_id, "chunk": i, "chunk_id": f"{doc_id}::{i}", "categoria": categoria,
                  "embedding_model": MODEL},
    )


# ------------------------------------------------------------- tokenización
def test_tokenize_conserva_identificadores_y_los_parte():
    t = tokenize("¿Cómo uso asyncio.gather?")
    assert "asyncio.gather" in t and "gather" in t and "asyncio" in t


def test_tokenize_sin_tildes_ni_stopwords():
    t = tokenize("La función de caché")
    assert "funcion" in t and "cache" in t and "de" not in t and "la" not in t


# ------------------------------------------------------------ ingesta / chunks
def test_front_matter():
    meta, cuerpo = ingest.parse_front_matter("---\ncategoria: texto\netiquetas: a, b\n---\n# Hola\n")
    assert meta == {"categoria": "texto", "etiquetas": "a, b"} and cuerpo.startswith("# Hola")


def test_documentos_traen_categoria_y_etiquetas():
    docs = ingest.load_documents()
    assert len(docs) >= 15
    d = next(x for x in docs if x.metadata["doc_id"] == "heapq")
    assert d.metadata["categoria"] == "estructuras_de_datos" and d.metadata["etiquetas"]


def test_chunks_con_metadatos_avanzados():
    chunks = ingest.split_documents(ingest.load_documents(), MODEL)
    for c in chunks:
        m = c.metadata
        assert {"fuente", "doc_id", "categoria", "etiquetas", "pagina", "chunk", "chunk_id"} <= m.keys()
        assert m["pagina"] >= 1 and m["embedding_model"] == MODEL
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunks_respetan_el_tamano_en_tokens():
    import tiktoken

    enc = tiktoken.get_encoding(config.TOKEN_ENCODING)
    chunks = ingest.split_documents(ingest.load_documents(), MODEL)
    assert all(len(enc.encode(c.page_content)) <= config.CHUNK_TOKENS for c in chunks)


def test_huella_cambia_si_cambia_el_texto():
    a = ingest.split_documents(ingest.load_documents(), MODEL)
    b = ingest.split_documents(ingest.load_documents(), MODEL)
    assert ingest.fingerprint(a) == ingest.fingerprint(b)
    b[0].page_content += " cambio"
    assert ingest.fingerprint(a) != ingest.fingerprint(b)


def test_ingesta_guarda_el_texto_en_la_metadata_y_es_idempotente():
    index = FakeIndex()
    n = ingest.ingest(index, FakeEmbeddings())
    primero = index.upserts
    assert n == len(index.vectors) > 0
    meta = next(iter(index.vectors.values()))["metadata"]
    assert meta["text"] and meta["fuente"] and meta["huella"]  # el texto viaja en la metadata
    ingest.ingest(index, FakeEmbeddings())  # nada cambió
    assert index.upserts == primero
    ingest.ingest(index, FakeEmbeddings(), force=True)  # forzado: vuelve a subir
    assert index.upserts > primero


class CountingEmbeddings(FakeEmbeddings):
    def __init__(self):
        self.textos = 0

    def embed_documents(self, texts):
        self.textos += len(texts)
        return super().embed_documents(texts)


def test_ingesta_reanudable_solo_sube_lo_que_falta():
    index = FakeIndex()
    emb = CountingEmbeddings()
    ingest.ingest(index, emb)
    total = len(index.vectors)
    for vid in sorted(index.vectors)[:10]:  # simula una ingesta que se cortó: faltan 10
        del index.vectors[vid]
    emb2 = CountingEmbeddings()
    ingest.ingest(index, emb2)
    assert emb2.textos == 10 and len(index.vectors) == total  # no re-embebe los 67 restantes


def test_ingesta_reconstruye_si_cambia_el_contenido(tmp_path):
    import shutil

    datos = tmp_path / "data"
    shutil.copytree(config.DATA_DIR, datos)
    index = FakeIndex()
    ingest.ingest(index, FakeEmbeddings(), data_dir=datos)
    (datos / "heapq.md").write_text("---\ncategoria: texto\n---\n# Nuevo\n\ncontenido distinto", encoding="utf-8")
    emb = CountingEmbeddings()
    ingest.ingest(index, emb, data_dir=datos)
    assert emb.textos == len(index.vectors)  # reconstrucción completa: la huella cambió


# ---------------------------------------------------- límite de tokens por minuto
class Reloj:
    def __init__(self):
        self.t = 0.0
        self.esperas: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.esperas.append(s)
        self.t += s


def test_throttle_espera_cuando_se_llena_la_ventana():
    from embeddings import ThrottledEmbeddings

    reloj = Reloj()
    emb = ThrottledEmbeddings(FakeEmbeddings(), 100, sleep=reloj.sleep, clock=reloj.now)
    texto = "palabra " * 60  # ~60 tokens
    emb.embed_documents([texto])  # entra
    assert reloj.esperas == []
    emb.embed_documents([texto])  # 60 + 60 > 100: debe esperar a que venza la ventana
    assert reloj.esperas and reloj.esperas[0] > 50


def test_throttle_parte_pedidos_grandes_en_grupos():
    from embeddings import ThrottledEmbeddings

    llamadas = []

    class Registro(FakeEmbeddings):
        def embed_documents(self, texts):
            llamadas.append(len(texts))
            return super().embed_documents(texts)

    reloj = Reloj()
    emb = ThrottledEmbeddings(Registro(), 100, sleep=reloj.sleep, clock=reloj.now)
    vecs = emb.embed_documents(["palabra " * 40] * 5)  # 5 x ~40 tokens con presupuesto 100
    assert len(vecs) == 5 and max(llamadas) <= 2 and len(llamadas) >= 3


def test_throttle_reintenta_un_429_esperando_lo_que_indica_la_api():
    import httpx2 as httpx
    import openai

    from embeddings import ThrottledEmbeddings

    estado = {"n": 0}

    class Limitado(FakeEmbeddings):
        def embed_query(self, text):
            estado["n"] += 1
            if estado["n"] == 1:
                raise openai.RateLimitError(
                    "Quota exceeded. Please retry in 26.1s.",
                    response=httpx.Response(429, request=httpx.Request("POST", "https://x.test")),
                    body=None,
                )
            return super().embed_query(text)

    reloj = Reloj()
    emb = ThrottledEmbeddings(Limitado(), 1000, sleep=reloj.sleep, clock=reloj.now)
    assert emb.embed_query("hola")
    assert estado["n"] == 2 and 27 <= reloj.esperas[0] <= 28


# ----------------------------------------------------------- setup del índice
def test_crea_el_indice_serverless_si_no_existe():
    pc = FakePinecone()
    setup_index.ensure_index(pc, "mi-indice")
    spec = pc.created[0]
    assert spec["dimension"] == 1536 and spec["metric"] == "cosine"
    assert spec["spec"].cloud == config.PINECONE_CLOUD


def test_no_recrea_un_indice_existente():
    pc = FakePinecone({"mi-indice": SimpleNamespace(dimension=1536, metric="cosine")})
    setup_index.ensure_index(pc, "mi-indice")
    assert pc.created == []


def test_dimension_incompatible_aborta():
    pc = FakePinecone({"mi-indice": SimpleNamespace(dimension=768, metric="cosine")})
    with pytest.raises(setup_index.IndexConfigError):
        setup_index.ensure_index(pc, "mi-indice")


def test_falta_la_api_key(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    with pytest.raises(setup_index.IndexConfigError):
        setup_index.get_client()


# ----------------------------------------------------------------- híbrido
CORPUS = [
    doc("functools", "lru_cache guarda en caché los resultados de una función", 0),
    doc("heapq", "nlargest devuelve los n elementos más grandes de un iterable", 0),
    doc("logging", "los handlers envían los registros a destinos como archivos", 0),
    doc("re", "sub reemplaza las coincidencias del patrón en la cadena", 0),
]


def make_system(vector_docs, **kw):
    system = RAGSystem(FakeIndex(), FakeEmbeddings(), corpus=CORPUS, **kw)
    system._vector = lambda categoria: StaticRetriever(docs=vector_docs)  # type: ignore[method-assign]
    return system


def test_el_lexico_encuentra_terminos_tecnicos_que_el_vectorial_no():
    # El vectorial "se equivoca" (devuelve logging); BM25 acierta por el término lru_cache.
    system = make_system([CORPUS[2]])
    ids = [d.metadata["doc_id"] for d in system.retrieve("¿cómo uso lru_cache?")]
    assert ids[:2] == ["logging", "functools"] or ids[:2] == ["functools", "logging"]
    solo_vectorial = [d.metadata["doc_id"] for d in system.retrieve_semantic("¿cómo uso lru_cache?")]
    assert "functools" not in solo_vectorial  # el vectorial solo falla...
    assert "functools" in ids  # ...y el híbrido lo rescata gracias a BM25


def test_fusion_sin_duplicados_y_tope_k():
    system = make_system(list(CORPUS), k=3)
    top = system.retrieve("lru_cache nlargest handlers")
    ids = [d.metadata["chunk_id"] for d in top]
    assert len(ids) == len(set(ids)) and len(ids) <= 3


async def test_aretrieve_asincrono():
    system = make_system([CORPUS[1]])
    top = await system.aretrieve("nlargest")
    assert top[0].metadata["doc_id"] == "heapq"


def test_filtro_por_categoria_en_lexico():
    corpus = [*CORPUS, doc("threading", "lru_cache no existe aquí pero hilos sí", 0, "concurrencia")]
    system = RAGSystem(FakeIndex(), FakeEmbeddings(), corpus=corpus)
    res = system.retrieve_lexical("hilos", categoria="concurrencia")
    assert {d.metadata["categoria"] for d in res} == {"concurrencia"}


def test_metadata_numerica_se_normaliza_a_int():
    d = doc("heapq", "nlargest", 0)
    d.metadata.update(pagina=2.0, chunks_en_doc=5.0)
    d.metadata["chunk"] = 3.0
    top = make_system([d], k=5)._top([d])
    assert top[0].metadata["pagina"] == 2 and isinstance(top[0].metadata["pagina"], int)
    assert isinstance(top[0].metadata["chunk"], int)


def test_namespace_vacio_da_error_claro():
    with pytest.raises(RuntimeError, match="ingest.py"):
        RAGSystem(FakeIndex(), FakeEmbeddings(), corpus=[])


def test_modelo_de_embeddings_distinto_aborta():
    corpus = [doc("re", "texto", 0)]
    corpus[0].metadata["embedding_model"] = "text-embedding-3-small"
    with pytest.raises(RuntimeError, match="force"):
        RAGSystem(FakeIndex(), FakeEmbeddings(), corpus=corpus)


# -------------------------------------------------------------- evaluación
def res(esperado, recuperados):
    return Resultado("p", esperado, recuperados)


def test_recall_y_precision_a_mano():
    rs = [
        res("a", ["a", "x", "x", "x", "x"]),  # hit, precision 1/5
        res("b", ["x", "b", "b", "x", "x"]),  # hit, precision 2/5
        res("c", ["x", "x", "x", "x", "x"]),  # miss, precision 0
    ]
    assert recall_at_k(rs, 5) == pytest.approx(2 / 3)
    assert precision_at_k(rs, 5) == pytest.approx((0.2 + 0.4 + 0.0) / 3)


def test_mrr():
    rs = [res("a", ["a", "x"]), res("b", ["x", "b"]), res("c", ["x", "y"])]
    assert mrr(rs, 5) == pytest.approx((1 + 0.5 + 0) / 3)


def test_k_menor_que_la_posicion_no_cuenta():
    assert not res("a", ["x", "x", "a"]).hit(2)


def test_golden_set_valido_y_documentos_existentes():
    golden = load_golden_set()
    assert len(golden) >= 5
    existentes = {d.metadata["doc_id"] for d in ingest.load_documents()}
    assert {g["documento_id_esperado"] for g in golden} <= existentes
