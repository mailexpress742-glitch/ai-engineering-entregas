"""Configuración del sistema: todo sale de variables de entorno (``.env``) con defaults seguros.

Nada de IDs de índices, namespaces ni modelos escritos a mano en el código: cada uno tiene su
variable (ver ``.env.example``).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# El SDK de Anthropic (versiones recientes) emite sus propios spans OpenTelemetry con los mismos tokens que ya registra
# la instrumentación de LangChain: Phoenix los sumaba dos veces (tokens y costo x2). Se apagan ANTES de crear el
# cliente del modelo (por eso vive acá, en lo primero que se importa); el span del LLM lo sigue emitiendo LangChain.
os.environ.setdefault("ANTHROPIC_OPEN_TELEMETRY", "false")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
CONOCIMIENTO_DIR = DATA_DIR / "conocimiento"  # base de conocimiento del RAG (.md con metadatos)
PIEZAS_PATH = DATA_DIR / "piezas.json"  # seguimiento simulado de piezas
GOLDEN_SET_PATH = BASE_DIR / "eval" / "golden_set.json"

# --- Pinecone (Serverless) ---------------------------------------------------------
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")  # el plan gratuito solo admite aws / us-east-1
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")
METRIC = "cosine"


def index_name() -> str:
    return os.getenv("INDEX_NAME", "rag-escalable")


def namespace() -> str:
    """Namespace propio de este corpus: aísla los datos y acota la búsqueda."""
    return os.getenv("PINECONE_NAMESPACE", "reclamos-mailex")


def rag_backend() -> str:
    """``pinecone`` (híbrido: BM25 + vectorial) o ``local`` (solo BM25, sin cuenta ni red)."""
    return os.getenv("RAG_BACKEND", "pinecone").strip().lower()


# --- Embeddings --------------------------------------------------------------------
# Dimensión del índice = dimensión de los embeddings. Ambos proveedores se fijan en 1536.
EMBEDDING_DIMENSION = 1536
EMBEDDING_MODELS = {"gemini": "gemini-embedding-001", "openai": "text-embedding-3-small"}


def embedding_provider() -> str:
    return os.getenv("EMBEDDINGS_PROVIDER", "gemini").strip().lower()


# --- Chunking y recuperación ---------------------------------------------------------
CHUNK_TOKENS = 600  # un chunk por sección ``##``; solo se parte si pasa de este tamaño
CHUNK_OVERLAP_TOKENS = 60
TOKEN_ENCODING = "cl100k_base"
TOP_K = 5  # fragmentos que devuelve el sistema
CANDIDATES = 10  # candidatos que aporta cada recuperador antes de fusionar
WEIGHTS = (0.4, 0.6)  # (BM25 léxico, vectorial) para la fusión RRF
RRF_C = 60

# --- Calendario del negocio ----------------------------------------------------------
# "Hoy" fijo para que las demos y los tests sean reproducibles (los datos de seguimiento son sintéticos).
# Vacío = fecha real del sistema.
HOY_SIMULADO = os.getenv("HOY_SIMULADO", "2026-11-18")
FERIADOS_NACIONALES = frozenset(
    date.fromisoformat(d)
    for d in os.getenv("FERIADOS", "2026-10-12,2026-11-23,2026-12-08,2026-12-25").split(",")
    if d.strip()
)


def hoy() -> date:
    return date.fromisoformat(HOY_SIMULADO) if HOY_SIMULADO.strip() else date.today()
