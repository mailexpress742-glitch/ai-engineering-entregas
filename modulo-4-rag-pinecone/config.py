"""Configuración del sistema: todo sale de variables de entorno (.env) con defaults seguros."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GOLDEN_SET_PATH = BASE_DIR / "eval" / "golden_set.json"

# --- Pinecone (Serverless) --------------------------------------------------
# El plan gratuito solo admite aws / us-east-1.
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")
METRIC = "cosine"


def index_name() -> str:
    return os.getenv("INDEX_NAME", "rag-escalable")


def namespace() -> str:
    """Namespace propio de este corpus: aísla los datos y acota la búsqueda."""
    return os.getenv("PINECONE_NAMESPACE", "docs-python-stdlib")


# --- Embeddings --------------------------------------------------------------
# Dimensión del índice = dimensión de los embeddings. Ambos proveedores se fijan en
# 1536 (text-embedding-3-small la entrega nativa; Gemini permite recortarla).
EMBEDDING_DIMENSION = 1536
EMBEDDING_MODELS = {
    "gemini": "gemini-embedding-001",
    "openai": "text-embedding-3-small",
}


def embedding_provider() -> str:
    return os.getenv("EMBEDDINGS_PROVIDER", "gemini").strip().lower()


# --- Chunking (en tokens): punto medio 500-800 --------------------------------
CHUNK_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 60
TOKEN_ENCODING = "cl100k_base"
# Las "páginas" de un .md se aproximan como ventanas de este tamaño (en caracteres).
CHARS_PER_PAGE = 3000

# --- Recuperación --------------------------------------------------------------
TOP_K = 5  # documentos que devuelve el sistema
CANDIDATES = 10  # candidatos que aporta cada recuperador antes de fusionar
WEIGHTS = (0.4, 0.6)  # (BM25 léxico, vectorial) para el EnsembleRetriever
