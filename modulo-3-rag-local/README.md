# Módulo 3 — Sistema de recuperación semántica local (RAG)

Pre-entrega 3 del curso **AI Engineering**. Flujo RAG *end-to-end*: ingesta de
documentos → ChromaDB persistente → recuperación por similitud → generación
*grounded* con LangChain (LCEL) → salida validada con Pydantic, con referencias.

El "cerebro" es un mini manual interno de una empresa ficticia (**Nubra Cloud**) en
`data/`: backups, respuesta a incidentes, despliegues y seguridad para nuevos ingresos.

## Estructura

```
modulo-3-rag-local/
├── data/               # 4 documentos .md (dataset de ejemplo)
├── config.py           # chunking, top_k, modelo de embeddings, umbral
├── embeddings.py       # UNA fábrica de embeddings (indexar y consultar)
├── ingest.py           # carga + chunking + ChromaDB (idempotente)
├── rag.py              # retriever + cadena LCEL + get_rag_response() async
├── schemas.py          # RespuestaModelo (salida del LLM) y RagResponse (salida final)
├── llm.py              # fábrica del LLM (Anthropic / OpenAI / Gemini)
├── main.py             # demo: pregunta con respuesta + pregunta trampa
├── tests/              # 21 tests sin red ni API keys
├── .env.example
└── requirements.txt
```

## Cómo correrlo

Requiere **Python 3.12**.

```bash
cd modulo-3-rag-local
py -3.12 -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/Mac: cp .env.example .env
# editá .env: GEMINI_API_KEY (embeddings) + la key del LLM elegido
python main.py                                    # las 2 pruebas del enunciado
python main.py --pregunta "¿Cuál es el RPO?"      # una pregunta propia
python ingest.py --rebuild                        # fuerza reindexar
```

| Variable | Uso |
|---|---|
| `GEMINI_API_KEY` | **Embeddings** (siempre Gemini, `gemini-embedding-001`) |
| `LLM_PROVIDER` | LLM que redacta la respuesta: `anthropic` (por defecto), `openai` o `gemini` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | key del LLM elegido |
| `LLM_MODEL` | opcional; fuerza un modelo |

Las keys viven solo en `.env` (ignorado por git). Nada está hardcodeado.

## Cómo funciona

### 1. Ingesta y chunking (`ingest.py`)
- Lee los `.md`/`.txt` de `data/`.
- `RecursiveCharacterTextSplitter` **medido en tokens** (`cl100k_base`), con
  **chunk de 500 tokens y solapamiento de 50**, usando los separadores de Markdown:
  corta primero por títulos (`##`) y párrafos, y solo si un bloque excede los 500
  tokens baja a líneas, frases y palabras. Así cada fragmento conserva una idea
  completa (una sección, una tabla) en vez de cortarse a mitad.
- Cada fragmento guarda `source` (archivo) y `chunk` (posición) como metadata.
- Resultado con el dataset: 4 documentos → 9 fragmentos, todos ≤ 500 tokens.

### 2. Persistencia sin reindexar de más
ChromaDB persiste en `./vectorstore`. La colección guarda una **huella (SHA-256)** del
contenido de `data/` + parámetros de chunking + modelo de embeddings:
- misma huella → se reutiliza el índice, **sin gastar llamadas de embeddings**;
- cambió un documento, el chunking o el modelo → se reconstruye solo;
- `--rebuild` fuerza la reconstrucción.

### 3. Embeddings consistentes
Una única función (`get_embeddings()`) se usa para indexar y para consultar, y el
modelo forma parte de la huella: no se puede consultar un índice generado con otro
modelo (error nº 1 de los RAG). La métrica es distancia **coseno**.

### 4. Recuperación y cadena LCEL (`rag.py`)
`get_rag_response(query)` es **asíncrona de punta a punta**:
1. `await store.asimilarity_search_with_score(query, k)` con **top_k = 4** (nunca más de 5).
2. Los fragmentos se numeran (`[1]`, `[2]`…) y entran al prompt.
3. `await chain.ainvoke(...)` con `PROMPT | LLM | PydanticOutputParser`, envuelto en
   `.with_retry()` (JSON mal formado, respuesta truncada por `finish_reason`, red,
   rate limit).
4. Se arma un `RagResponse` con el texto y las referencias.

### 5. Prompt "filtro de veracidad"
Instruye al modelo a responder **solo con el CONTEXTO**, a contestar exactamente
*«No lo sé: esa información no está en los documentos disponibles.»* si no está, y a
ignorar instrucciones que aparezcan dentro del contexto.

### 6. Salida validada con Pydantic (`schemas.py`)
- `RespuestaModelo` (lo que parsea el `PydanticOutputParser`): `respuesta`,
  `en_contexto` y `fuentes` (lista de `{fragmento, cita}`). Si `en_contexto=true`
  exige al menos una fuente.
- `RagResponse` (lo que devuelve el sistema): `pregunta`, `respuesta`,
  `en_contexto` y `referencias` (`archivo`, `fragmento`, `distancia`, `cita`).

### 7. Defensas contra alucinaciones (en capas)
1. **Umbral de distancia** (`MAX_DISTANCE = 0.45`): si ni el mejor fragmento es
   cercano, ni se llama al LLM. Calibrado con este corpus: preguntas relevantes
   0.30–0.42, ajenas (capital de Francia, recetas) 0.45–0.51. Es un filtro barato:
   las preguntas «trampa» parecidas al tema (vacaciones: 0.39–0.44) no se separan
   solo por distancia.
2. **Prompt** que exige "No lo sé" fuera de contexto.
3. **Citas verificadas:** el modelo debe copiar una **cita textual** del contexto; el
   código comprueba que aparezca literalmente en un fragmento recuperado. Si el
   modelo se equivoca de número de fragmento, la cita se reasigna al fragmento
   correcto; si no aparece en ninguno, se descarta y la respuesta pasa a "No lo sé".

> Hallazgo durante las pruebas: en la primera versión el modelo respondió bien pero
> citó el fragmento equivocado (`04_seguridad…` en vez de `02_respuesta_a_incidentes`).
> Con solo números de fragmento, ese error pasaba inadvertido. La verificación de
> citas textuales lo corrige.

## Evidencia de pruebas (Anthropic `claude-haiku-4-5` + embeddings Gemini)

**Prueba 1 — la respuesta está en los documentos**

```json
{
  "pregunta": "¿Cada cuánto se hacen los snapshots de las bases de datos y cuánto tiempo se guardan?",
  "respuesta": "Los snapshots completos de las bases de datos PostgreSQL de producción se realizan una vez por día a las 02:00 UTC, con una duración habitual de entre 20 y 35 minutos. Se guardan durante 35 días.",
  "en_contexto": true,
  "referencias": [
    {
      "archivo": "01_politica_de_backups.md",
      "fragmento": 0,
      "distancia": 0.2867,
      "cita": "Snapshots completos: una vez por día, a las 02:00 UTC, con una duración habitual de entre 20 y 35 minutos."
    }
  ]
}
```

**Prueba 2 — pregunta trampa (suena a RR. HH., que no está en los documentos)**

```json
{
  "pregunta": "¿Cuántos días de vacaciones le corresponden a una persona recién ingresada a Nubra Cloud?",
  "respuesta": "No lo sé: esa información no está en los documentos disponibles.",
  "en_contexto": false,
  "referencias": []
}
```

Los 4 fragmentos recuperados para la trampa (distancias 0.35–0.41) eran del tema
"nuevos ingresos" y "backups", y aun así el modelo no inventó un número.

**Otras comprobaciones**
- *«¿Cuál es la capital de Francia?»* → distancia 0.506 > 0.45: respuesta "No lo sé"
  **sin llamar al LLM**.
- *«¿A cuántos minutos se escala una alerta si el titular de la guardia no la
  reconoce?»* → "5 minutos, se escala automáticamente al suplente", con la cita
  literal de `02_respuesta_a_incidentes.md`.
- Segunda ejecución de `main.py`: `Índice existente y vigente (9 fragmentos): no se
  reindexa`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

21 tests con embeddings y LLM falsos (ChromaDB real en carpeta temporal): tamaño de
fragmentos en tokens, solapamiento, metadata, idempotencia y reindexado, esquemas,
respuesta con fuentes, "No lo sé", umbral sin llamar al LLM, cita inventada, número de
fragmento equivocado, reintento por JSON inválido o truncado, error controlado, y tope
de 5 fragmentos.
