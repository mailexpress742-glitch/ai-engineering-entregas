"""RAG híbrido: chunking con metadatos, BM25, fusión RRF y filtros — sin red (vectorial de juguete)."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import pytest
from langchain_core.embeddings import Embeddings

from app.rag.ingesta import cargar_fragmentos, huella, parse_front_matter
from app.rag.sistema import RAGSystem, tokenizar

FRAGMENTOS = cargar_fragmentos(modelo="test")


class EmbeddingsDeJuguete(Embeddings):
    """Bolsa de palabras hasheada en 64 dimensiones: determinista y suficiente para probar la mecánica."""

    def _vec(self, texto: str) -> list[float]:
        v = [0.0] * 64
        for t in tokenizar(texto):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % 64] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class VectorialDeJuguete:
    """Doble en memoria de Pinecone: similitud coseno + los mismos filtros de metadatos ($eq, $in, $and)."""

    def __init__(self, fragmentos, emb: EmbeddingsDeJuguete) -> None:
        self.emb = emb
        self.docs = {f.chunk_id: (emb.embed_query(f.texto), f) for f in fragmentos}
        self.filtros_recibidos: list[Any] = []

    def _cumple(self, f, filtro) -> bool:
        if not filtro:
            return True
        if "$and" in filtro:
            return all(self._cumple(f, c) for c in filtro["$and"])
        (campo, cond), = filtro.items()
        valor = getattr(f, campo)
        return valor == cond["$eq"] if "$eq" in cond else valor in cond["$in"]

    async def buscar(self, vector, k, filtro):
        self.filtros_recibidos.append(filtro)
        res = [(cid, sum(a * b for a, b in zip(vector, v, strict=True))) for cid, (v, f) in self.docs.items() if self._cumple(f, filtro)]
        return sorted(res, key=lambda x: x[1], reverse=True)[:k]


@pytest.fixture
def rag_hibrido():
    emb = EmbeddingsDeJuguete()
    vec = VectorialDeJuguete(FRAGMENTOS, emb)
    return RAGSystem(FRAGMENTOS, embeddings=emb, vectorial=vec), vec


# --------------------------------------------------------------------- ingesta
def test_el_corpus_se_parte_por_seccion_con_metadatos_validos():
    assert len(FRAGMENTOS) > 50 and len({f.fuente for f in FRAGMENTOS}) == 14
    assert len({f.chunk_id for f in FRAGMENTOS}) == len(FRAGMENTOS)  # ids únicos
    assert {f.categoria for f in FRAGMENTOS} == {"procedimiento", "plazos", "politica", "escalamiento", "plantilla"}
    assert {f.servicio for f in FRAGMENTOS} == {"general", "carta_documento", "encomienda", "notificacion", "acuse"}
    assert all(f.texto.startswith(f.fuente.split("_", 1)[0]) is False for f in FRAGMENTOS)  # el texto no arranca con el nombre de archivo
    tabla = [f for f in FRAGMENTOS if f.fuente == "03_plazos_de_entrega.md" and "Tabla" in f.seccion]
    assert tabla and "3 días hábiles" in tabla[0].texto and "| Carta documento |" in tabla[0].texto  # la tabla queda entera


def test_front_matter_y_huella_estable():
    meta, cuerpo = parse_front_matter("---\ncategoria: plazos\nservicio: general\n---\n# T\ncuerpo")
    assert meta == {"categoria": "plazos", "servicio": "general"} and cuerpo.startswith("# T")
    assert huella(FRAGMENTOS) == huella(cargar_fragmentos(modelo="test"))  # mismo contenido → misma huella
    assert huella(FRAGMENTOS) != huella(cargar_fragmentos(modelo="otro-modelo"))  # otro modelo de embeddings → reingestar


def test_tokenizar_conserva_codigos_y_quita_tildes():
    assert "cd-100231" in tokenizar("La pieza CD-100231 está en reparto") and "100231" in tokenizar("CD-100231")
    assert "habiles" in tokenizar("días hábiles") and "de" not in tokenizar("plazo de entrega")


# ------------------------------------------------------------------- recuperación
async def test_busqueda_hibrida_encuentra_el_documento_correcto(rag_hibrido):
    rag, _ = rag_hibrido
    r = await rag.buscar("¿cuántos días hábiles tarda una carta documento en el interior?")
    assert r[0].fuente == "03_plazos_de_entrega.md"
    assert len(r) <= 5 and all(0 < x.puntaje < 1 for x in r)


async def test_un_fragmento_hallado_por_ambos_recuperadores_suma_los_dos_aportes(rag_hibrido):
    rag, _ = rag_hibrido
    r = await rag.buscar("acuse pendiente zona interior rendición")
    por_ambos = [x for x in r if set(x.encontrado_por) == {"bm25", "vectorial"}]
    solo_uno = [x for x in r if len(x.encontrado_por) == 1]
    assert por_ambos and set(r[0].encontrado_por) == {"bm25", "vectorial"}  # el mejor es el que coinciden ambos
    assert all(por_ambos[0].puntaje > x.puntaje for x in solo_uno)


async def test_modos_lexico_y_semantico_por_separado(rag_hibrido):
    rag, _ = rag_hibrido
    lex = await rag.buscar("Siniestros indemnización tope", modo="lexico")
    sem = await rag.buscar("Siniestros indemnización tope", modo="semantico")
    assert {o for x in lex for o in x.encontrado_por} == {"bm25"} and {o for x in sem for o in x.encontrado_por} == {"vectorial"}


async def test_filtro_por_metadatos_se_aplica_en_bm25_y_en_pinecone(rag_hibrido):
    rag, vec = rag_hibrido
    r = await rag.buscar("respuesta al cliente", categoria="plantilla")
    assert r and all(x.categoria == "plantilla" for x in r)
    assert vec.filtros_recibidos[-1] == {"categoria": {"$eq": "plantilla"}}  # el filtro viaja a Pinecone

    r = await rag.buscar("plazo de entrega", servicio="encomienda")
    assert r and all(x.servicio in ("encomienda", "general") for x in r)  # los generales siempre se incluyen
    r = await rag.buscar("plazo", categoria="plazos", servicio="carta_documento")
    assert vec.filtros_recibidos[-1] == {"$and": [{"categoria": {"$eq": "plazos"}}, {"servicio": {"$in": ["carta_documento", "general"]}}]}


async def test_sin_coincidencias_devuelve_lista_vacia():
    rag = RAGSystem(FRAGMENTOS)  # modo local: solo BM25
    assert not rag.es_hibrido
    assert await rag.buscar("zzzz qqqq xxxx") == []
    assert await rag.buscar("plazo", categoria="plantilla", servicio="acuse") != []  # filtros combinados válidos


async def test_modo_local_funciona_sin_embeddings():
    r = await RAGSystem(FRAGMENTOS).buscar("extravío búsqueda Siniestros 3 días hábiles")
    assert r and r[0].fuente in ("06_extravio_y_danos.md", "13_plantilla_extravio.md")


def test_embeddings_y_vectorial_van_juntos():
    with pytest.raises(ValueError):
        RAGSystem(FRAGMENTOS, embeddings=EmbeddingsDeJuguete())


async def test_ids_desconocidos_de_pinecone_se_ignoran(rag_hibrido):
    rag, vec = rag_hibrido
    original = vec.buscar

    async def con_fantasma(vector, k, filtro):
        return [("fantasma::0", 0.99), *await original(vector, k, filtro)]  # índice desactualizado: id que ya no existe

    vec.buscar = con_fantasma  # type: ignore[method-assign]
    r = await rag.buscar("plazo de entrega")
    assert r and all(re.match(r"\d\d_", x.fuente) for x in r)
