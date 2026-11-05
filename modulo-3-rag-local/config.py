"""Parámetros del sistema RAG en un solo lugar."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VECTORSTORE_DIR = BASE_DIR / "vectorstore"

COLLECTION_NAME = "nubra_docs"

# Chunking (en TOKENS, no en caracteres): mínimo 500 con 50 de solapamiento.
CHUNK_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
TOKEN_ENCODING = "cl100k_base"

# Un solo modelo de embeddings para indexar Y consultar (error común #1).
EMBEDDING_MODEL = "gemini-embedding-001"

# Recuperación: entre 3 y 5 fragmentos para evitar el "contexto infinito".
TOP_K = 4

# Distancia coseno (0 = idéntico, 2 = opuesto). Por encima de este valor el mejor
# fragmento se considera irrelevante y ni siquiera se llama al LLM.
# Calibrado con este corpus: preguntas relevantes 0.30-0.42, preguntas ajenas
# (capital de Francia, recetas) 0.45-0.51. Es un filtro barato: la defensa principal
# contra alucinaciones es el prompt (las preguntas "trampa" parecidas al tema, como
# vacaciones, caen en 0.39-0.44 y las resuelve el LLM con "No lo sé").
MAX_DISTANCE = 0.45
