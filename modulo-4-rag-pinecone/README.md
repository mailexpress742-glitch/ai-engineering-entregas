# Módulo 4 — Sistema RAG escalable en la nube con Pinecone

Pre-entrega 4 del curso **AI Engineering**. Recuperación **híbrida** (BM25 léxico +
vectorial) sobre un índice **Pinecone Serverless**, con ingesta con metadatos y un
script de evaluación (**Recall@5** y **Precision@5**) contra un *golden set*.

El corpus son 20 documentos con la **documentación real de módulos de la biblioteca
estándar de Python** (`asyncio`, `functools`, `heapq`, `re`, `json`, `logging`…),
generados desde sus docstrings con `build_dataset.py` y versionados en `data/`.

## Estructura

```
modulo-4-rag-pinecone/
├── data/                # 20 .md con front matter (categoría + etiquetas)
├── eval/golden_set.json # 12 preguntas con su documento esperado
├── config.py            # índice, namespace, chunking, pesos del ensemble (todo por .env)
├── setup_index.py       # crea el índice Serverless solo si no existe
├── embeddings.py        # embeddings de 1536 dim + limitador de tokens por minuto
├── ingest.py            # chunking + metadatos + subida a Pinecone (idempotente, reanudable)
├── rag_system.py        # clase RAGSystem: EnsembleRetriever (BM25 + Pinecone)
├── evaluate.py          # Recall@k, Precision@k y MRR
├── query.py             # consulta rápida desde consola (con filtro por categoría)
├── build_dataset.py     # genera data/*.md desde la stdlib de Python
├── tests/               # 28 tests sin red ni cuenta de Pinecone
├── .env.example
└── requirements.txt
```

## Cómo replicar el índice

Requiere **Python 3.12**, una cuenta de [Pinecone](https://app.pinecone.io) (el plan
gratuito alcanza) y una API key de embeddings (Gemini de [AI Studio](https://aistudio.google.com/apikey)
u OpenAI).

```bash
cd modulo-4-rag-pinecone
py -3.12 -m venv .venv
.venv\Scripts\activate              # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # Linux/Mac: cp .env.example .env
# editá .env con tus keys (ver tabla)

python setup_index.py               # 1) crea el índice Serverless (si no existe)
python ingest.py                    # 2) chunking + embeddings + subida (≈2 min con Gemini gratis)
python evaluate.py                  # 3) métricas
python query.py "¿Cómo guardo en caché una función?" --categoria estructuras_de_datos
```

| Variable | Descripción |
|---|---|
| `PINECONE_API_KEY` | key de Pinecone |
| `INDEX_NAME` | nombre del índice (por defecto `rag-escalable`) |
| `EMBEDDINGS_PROVIDER` | `gemini` (por defecto, `gemini-embedding-001`) u `openai` (`text-embedding-3-small`) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | key del proveedor de embeddings |
| `PINECONE_NAMESPACE`, `PINECONE_CLOUD`, `PINECONE_REGION` | opcionales (el plan gratuito solo admite `aws` / `us-east-1`) |

Las keys viven solo en `.env` (ignorado por git).

## Cómo funciona

### Infraestructura (`setup_index.py`)
Verifica si el índice existe y, si no, lo crea en modo **Serverless**
(`dimension=1536`, métrica `cosine`). Si existe con otra dimensión, **aborta** con un
mensaje claro en vez de subir vectores incompatibles (error de mismatch de dimensiones).
Ambos proveedores de embeddings se fijan en 1536 dimensiones (Gemini permite recortarlas).

### Ingesta y metadatos (`ingest.py`)
- `RecursiveCharacterTextSplitter` medido en **tokens**, con separadores Markdown:
  chunks de **600 tokens** (punto medio entre 500 y 800) y 60 de solapamiento.
  Resultado: 20 documentos → **77 chunks**.
- Cada vector lleva en su **metadata**: `text` (el **texto original**, así recuperar no
  requiere otra base de datos), `fuente`, `doc_id`, `pagina`, `chunk`, `categoria`,
  `etiquetas` (lista), `chunk_id`, `embedding_model` y `huella`. Los `.md` no tienen
  páginas reales: `pagina` se aproxima con ventanas de ~3000 caracteres.
- Todo se sube a un **namespace** propio (`docs-python-stdlib`), que aísla este corpus
  y acota la búsqueda.
- **Idempotente y reanudable:** si el namespace ya tiene el mismo contenido no sube
  nada; si una ingesta se cortó a mitad, sube solo lo que falta; si cambió el contenido
  o los parámetros (huella distinta), reconstruye.
- **Límite del plan gratuito de Gemini (30.000 tokens/min):** `ThrottledEmbeddings`
  parte los pedidos, espera cuando la ventana de 60 s está llena y, ante un `429`,
  espera el tiempo que indica la propia API. (La primera versión subía lotes de 50
  chunks y la API los rechazaba.)

### Recuperador híbrido (`rag_system.py`)
`RAGSystem` encapsula un `EnsembleRetriever` que fusiona con *Reciprocal Rank Fusion*
ponderada (BM25 **0.4** / vectorial **0.6**) y devuelve el **top-5**:
- **Vectorial:** `PineconeVectorStore` (cosine), con filtro opcional por metadata
  (`categoria`).
- **Léxico:** `BM25Retriever` con un tokenizador propio que pasa a minúsculas, quita
  tildes y conserva los identificadores con punto (`asyncio.gather` → `asyncio.gather`,
  `asyncio`, `gather`).
- El corpus de BM25 se reconstruye al arrancar leyendo el campo `text` de la metadata
  de Pinecone: no hace falta tener los archivos locales.
- Verifica que el índice se generó con el **mismo modelo de embeddings** con el que se
  consulta.
- Expone `retrieve()` y `aretrieve()` (asíncrono), además de `retrieve_semantic()` y
  `retrieve_lexical()` para comparar.

### Evaluación (`evaluate.py`)
Golden set de 12 preguntas `{"pregunta", "documento_id_esperado"}`; cada una se
verificó contra el texto del dataset antes de usarla. Con los 5 chunks recuperados:
- **Recall@5:** proporción de preguntas cuyo documento correcto aparece entre los 5.
- **Precision@5:** promedio del % de los 5 recuperados que son del documento correcto.
- **MRR:** qué tan arriba aparece el documento correcto.

## Resultados (12 preguntas, k=5, índice real en Pinecone)

| Estrategia | Recall@5 | Precision@5 | MRR |
|---|---|---|---|
| **Híbrido (BM25 + vectorial)** | **1.00** | 0.55 | 0.92 |
| Solo vectorial (Pinecone) | 1.00 | 0.57 | 1.00 |
| Solo léxico (BM25) | 0.75 | 0.38 | 0.69 |

### Lectura honesta de los resultados
- **El híbrido recupera el documento correcto en las 12 preguntas** (Recall@5 = 1.00) y
  **rescata las 3 que BM25 solo no encontraba**: las parafraseadas que no nombran el
  término técnico (limitar corrutinas con un semáforo, cancelar por timeout, agrupar
  elementos consecutivos).
- **Pero en este golden set no supera al vectorial solo:** `gemini-embedding-001` ya
  acierta las 12 en el primer puesto (MRR 1.00), y el híbrido baja a 0.92 porque en
  dos preguntas (`asyncio.locks` y `asyncio.timeouts`) otro documento quedó primero y el
  correcto en el segundo lugar. La ventaja del léxico (nombres propios e identificadores
  exactos) no se manifestó porque las preguntas, aun las técnicas, son fáciles para
  los embeddings. Con 12 preguntas la diferencia es de 2 posiciones: no es concluyente.
- **Precision@5 de ~0.55 no es una mala señal:** cada documento tiene pocos chunks
  (de 1 a 11), así que con un solo documento relevante el máximo posible por pregunta
  suele ser menor que 1.0 (p. ej. `heapq` tiene 2 chunks: máximo 0.4).
- **Límite de escala:** BM25 vive en memoria y se reconstruye al arrancar; para un
  corpus mucho mayor convendría pasar a vectores *sparse* de Pinecone.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

28 tests con Pinecone y embeddings falsos: tokenización, metadatos y chunking, huella,
ingesta idempotente y reanudable, reconstrucción por cambios, creación del índice y
aborto por dimensión incompatible, limitador de tokens y reintento ante `429`, fusión
híbrida (BM25 rescatando lo que el vectorial no ve), filtro por categoría, aborto por
modelo de embeddings distinto, y las métricas calculadas a mano.
