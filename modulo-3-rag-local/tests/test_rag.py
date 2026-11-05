"""Tests sin red ni API keys: embeddings y LLM falsos, ChromaDB real en una carpeta temporal."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import tiktoken
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

import ingest
from config import CHUNK_OVERLAP_TOKENS, CHUNK_TOKENS, DATA_DIR, TOKEN_ENCODING
from rag import RagError, build_chain, format_context, get_rag_response
from schemas import NO_LO_SE, RagResponse, RespuestaModelo

ENC = tiktoken.get_encoding(TOKEN_ENCODING)


class FakeEmbeddings(Embeddings):
    """Embeddings deterministas por bolsa de palabras (sin red). Cuenta las llamadas."""

    DIM = 64

    def __init__(self) -> None:
        self.calls = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.DIM
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.DIM] += 1.0
        return v

    def embed_documents(self, texts):
        self.calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def store(tmp_path):
    return ingest.ensure_index(FakeEmbeddings(), persist_dir=tmp_path / "vs")


def fake_llm(salida_json: str, finish: str = "end_turn"):
    return RunnableLambda(lambda _p: AIMessage(content=salida_json, response_metadata={"stop_reason": finish}))


GROUNDED = (
    '{"respuesta": "Cada día a las 02:00 UTC.", "en_contexto": true, '
    '"fuentes": [{"fragmento": 1, "cita": "una vez por día, a las 02:00 UTC"}]}'
)
SIN_DATO = '{"respuesta": "no sé", "en_contexto": false, "fuentes": []}'
PREGUNTA = "snapshots completos de postgresql por día"


# ------------------------------------------------------------ chunking e ingesta
def test_los_fragmentos_respetan_el_tamano_en_tokens():
    chunks = ingest.split_documents(ingest.load_documents(DATA_DIR))
    assert len(chunks) > 4
    assert all(len(ENC.encode(c.page_content)) <= CHUNK_TOKENS for c in chunks)


def test_hay_solapamiento_entre_fragmentos_consecutivos():
    docs = ingest.load_documents(DATA_DIR)
    # Un texto largo sin títulos fuerza cortes por tamaño y, con ellos, solapamiento.
    largo = docs[0].model_copy(update={"page_content": " ".join(f"palabra{i}" for i in range(1500))})
    chunks = ingest.split_documents([largo])
    assert len(chunks) >= 3
    final_a = chunks[0].page_content.split()[-10:]
    assert any(p in chunks[1].page_content for p in final_a)
    solape = len(ENC.encode(" ".join(set(chunks[0].page_content.split()) & set(chunks[1].page_content.split()))))
    assert 0 < solape <= CHUNK_OVERLAP_TOKENS * 3


def test_cada_fragmento_conserva_su_fuente():
    chunks = ingest.split_documents(ingest.load_documents(DATA_DIR))
    assert {c.metadata["source"] for c in chunks} == {p.name for p in DATA_DIR.glob("*.md")}
    assert all("chunk" in c.metadata for c in chunks)


def test_carpeta_vacia(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest.load_documents(tmp_path)


def test_no_reindexa_si_el_indice_esta_vigente(tmp_path):
    emb = FakeEmbeddings()
    ingest.ensure_index(emb, persist_dir=tmp_path / "vs")
    primera = emb.calls
    ingest.ensure_index(emb, persist_dir=tmp_path / "vs")  # misma data, mismo índice
    assert emb.calls == primera


def test_reindexa_si_cambian_los_documentos(tmp_path):
    datos = tmp_path / "data"
    shutil.copytree(DATA_DIR, datos)
    emb = FakeEmbeddings()
    ingest.ensure_index(emb, data_dir=datos, persist_dir=tmp_path / "vs")
    primera = emb.calls
    (datos / "01_politica_de_backups.md").write_text("# Otro contenido\n\nTexto nuevo.", encoding="utf-8")
    ingest.ensure_index(emb, data_dir=datos, persist_dir=tmp_path / "vs")
    assert emb.calls > primera


def test_rebuild_fuerza_reindexado(tmp_path):
    emb = FakeEmbeddings()
    ingest.ensure_index(emb, persist_dir=tmp_path / "vs")
    primera = emb.calls
    ingest.ensure_index(emb, persist_dir=tmp_path / "vs", rebuild=True)
    assert emb.calls > primera


# ------------------------------------------------------------------- esquemas
def test_respuesta_fundamentada_exige_fuentes():
    with pytest.raises(ValidationError):
        RespuestaModelo(respuesta="x", en_contexto=True, fuentes=[])


def test_respuesta_sin_contexto_no_cita_fuentes():
    r = RespuestaModelo(
        respuesta="x", en_contexto=False, fuentes=[{"fragmento": 1, "cita": "texto de la cita"}]
    )
    assert r.fuentes == []


def test_rag_response_fundamentada_exige_referencias():
    with pytest.raises(ValidationError):
        RagResponse(pregunta="p", respuesta="r", en_contexto=True, referencias=[])


# ------------------------------------------------------------- get_rag_response
async def test_respuesta_con_fuentes(store):
    resp = await get_rag_response(PREGUNTA, store=store, chain=build_chain(fake_llm(GROUNDED)), max_distance=2)
    assert resp.en_contexto and resp.referencias
    assert resp.referencias[0].archivo.endswith(".md")


async def test_pregunta_fuera_de_contexto_dice_no_lo_se(store):
    resp = await get_rag_response(PREGUNTA, store=store, chain=build_chain(fake_llm(SIN_DATO)), max_distance=2)
    assert not resp.en_contexto and resp.respuesta == NO_LO_SE and resp.referencias == []


async def test_umbral_de_distancia_evita_llamar_al_llm(store):
    llamadas = []

    def llm(_p):
        llamadas.append(1)
        return AIMessage(content=GROUNDED)

    chain = build_chain(RunnableLambda(llm))
    resp = await get_rag_response("zzz qqq www", store=store, chain=chain, max_distance=0.0001)
    assert not resp.en_contexto and llamadas == []


async def test_cita_inventada_se_descarta(store):
    inventada = (
        '{"respuesta": "algo", "en_contexto": true, '
        '"fuentes": [{"fragmento": 1, "cita": "esta frase no existe en ningún documento"}]}'
    )
    resp = await get_rag_response(PREGUNTA, store=store, chain=build_chain(fake_llm(inventada)), max_distance=2)
    assert not resp.en_contexto and resp.respuesta == NO_LO_SE


async def test_cita_con_numero_de_fragmento_equivocado_se_corrige(store):
    # La cita existe en el corpus, pero el modelo indicó un número de fragmento incorrecto.
    mal_numerada = (
        '{"respuesta": "Cada día.", "en_contexto": true, '
        '"fuentes": [{"fragmento": 4, "cita": "una vez por día, a las 02:00 UTC"}]}'
    )
    resp = await get_rag_response(PREGUNTA, store=store, chain=build_chain(fake_llm(mal_numerada)), max_distance=2)
    assert resp.en_contexto
    assert resp.referencias[0].archivo == "01_politica_de_backups.md"
    assert "02:00 UTC" in resp.referencias[0].cita


async def test_reintenta_si_el_json_viene_mal(store):
    estado = {"n": 0}

    def llm(_p):
        estado["n"] += 1
        return AIMessage(content="esto no es json" if estado["n"] == 1 else GROUNDED)

    resp = await get_rag_response(PREGUNTA, store=store, chain=build_chain(RunnableLambda(llm)), max_distance=2)
    assert resp.en_contexto and estado["n"] == 2


async def test_descarta_respuesta_truncada(store):
    estado = {"n": 0}

    def llm(_p):
        estado["n"] += 1
        return AIMessage(content=GROUNDED, response_metadata={"stop_reason": "max_tokens" if estado["n"] == 1 else "end_turn"})

    resp = await get_rag_response(PREGUNTA, store=store, chain=build_chain(RunnableLambda(llm)), max_distance=2)
    assert resp.en_contexto and estado["n"] == 2


async def test_llm_caido_da_error_controlado(store):
    def llm(_p):
        raise KeyError("boom")

    with pytest.raises(RagError):
        await get_rag_response(PREGUNTA, store=store, chain=build_chain(RunnableLambda(llm)), max_distance=2)


async def test_pregunta_vacia(store):
    with pytest.raises(RagError):
        await get_rag_response("  ", store=store, chain=build_chain(fake_llm(GROUNDED)))


async def test_nunca_manda_mas_de_5_fragmentos(store):
    vistos = {}

    def llm(p):
        vistos["ctx"] = p.to_string()
        return AIMessage(content=GROUNDED)

    await get_rag_response(PREGUNTA, store=store, chain=build_chain(RunnableLambda(llm)), k=50, max_distance=2)
    assert vistos["ctx"].count("(fuente:") <= 5


def test_format_context_numera_fragmentos(store):
    scored = store.similarity_search_with_score(PREGUNTA, k=2)
    ctx = format_context(scored)
    assert ctx.startswith("[1] (fuente:") and "\n\n[2] (fuente:" in ctx
