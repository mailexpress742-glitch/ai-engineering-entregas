# Módulo 5 — Agente de razonamiento cíclico con memoria persistente

Pre-entrega 5 del curso **AI Engineering**. Un agente **ReAct** construido con
**LangGraph**: decide por sí mismo cuándo llamar herramientas, se recupera de errores
volviendo a intentar o pidiendo aclaraciones, y recuerda la conversación por `thread_id`
gracias a un checkpointer SQLite. Todo asíncrono (`asyncio`) y con type hints.

El dominio es una "base de datos" de clientes y pedidos simulada (`tools.py`).

## Estructura

```
modulo-5-agente-langgraph/
├── graph.py      # StateGraph(MessagesState): nodo agente + nodo tools + tools_condition
├── tools.py      # 3 herramientas @tool async con docstrings descriptivos + datos simulados
├── runner.py     # ejecutar_turno(): astream + traza ReAct + manejo de recursion_limit
├── main.py       # CLI: --demo, --thread/--pregunta, modo interactivo (AsyncSqliteSaver)
├── llm.py        # fábrica del LLM (Anthropic / OpenAI / Gemini)
├── trazas/       # evidencia: traza_ejemplo.json / .log y traza_persistencia.log
├── tests/        # 17 tests sin red ni API keys
├── .env.example
└── requirements.txt
```

## Cómo levantar el entorno

Requiere **Python 3.12**.

```bash
cd modulo-5-agente-langgraph
py -3.12 -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/Mac: cp .env.example .env
# editá .env: LLM_PROVIDER y la API key del proveedor elegido

python main.py --demo                                   # corre los escenarios y regenera trazas/
python main.py --thread ana --pregunta "¿Cuántos pedidos tuvo el cliente 102?"
python main.py --thread ana --pregunta "¿y el último?"  # mismo thread_id: recuerda el contexto
python main.py --thread ana                             # modo interactivo
```

| Variable | Descripción |
|---|---|
| `LLM_PROVIDER` | `anthropic` (por defecto), `openai` o `gemini` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | key del proveedor elegido |
| `CHECKPOINT_DB` | archivo SQLite de la memoria (por defecto `agente_memoria.sqlite`) |
| `RECURSION_LIMIT` | techo de pasos por invocación (por defecto 10) |

Las keys viven solo en `.env` (ignorado por git).

## Cómo funciona

```
START ─► agente ──(tools_condition)──► tools
           ▲                             │
           └─────────────────────────────┘      (si no pide herramientas ─► END)
```

- **`StateGraph(MessagesState)`** (`graph.py`): el estado es la lista de mensajes; el
  reducer de `MessagesState` (`add_messages`) los agrega sin pisar los anteriores.
- **Nodo `agente`:** llama al LLM con las herramientas enlazadas (`llm.bind_tools()`).
- **Nodo `tools`:** `ToolNode` ejecuta lo que el modelo pidió y devuelve los resultados.
- **Arista condicional `tools_condition`:** si el último mensaje trae `tool_calls` va a
  `tools`; si no, termina. **No hay `if/else` manuales:** el modelo decide solo.
- **Ciclo de retorno:** `tools -> agente`. El resultado (o el error) vuelve al modelo.
- **Herramientas** (`tools.py`), todas `@tool` y `async`, con docstrings que explican qué
  hacen, cuándo usarlas y qué devuelven (incluidos los errores):
  `buscar_cliente(nombre)`, `buscar_pedidos(cliente_id)` y `detalle_pedido(pedido_id)`.
  Nunca lanzan excepciones: devuelven `{"error", "sugerencia"}` para que el agente
  corrija el rumbo. `detalle_pedido("P-1019")` simula una base inestable: falla la primera
  vez (`"reintentable": true`) y responde en el reintento.
- **Persistencia:** `AsyncSqliteSaver` (la variante asíncrona del `SqliteSaver`: el
  síncrono no soporta `ainvoke`/`astream`). Cada `thread_id` tiene su propio historial en
  el archivo SQLite, que sobrevive a reiniciar el proceso.
- **Límites:** `recursion_limit` (10 por defecto) corta bucles de herramientas: al
  excederlo, `ejecutar_turno` devuelve un mensaje controlado en lugar de fallar. Contra
  el "estado sucio", al modelo solo le llegan los últimos 24 mensajes
  (`trim_messages`, sin separar una llamada de su resultado); el historial completo sigue
  en el checkpointer.

## Traza de ejecución

Salida real del demo (`python main.py --demo`, `claude-haiku-4-5`); el detalle completo
está en [`trazas/traza_ejemplo.log`](trazas/traza_ejemplo.log) y
[`trazas/traza_ejemplo.json`](trazas/traza_ejemplo.json).

**1. Razonamiento multi-paso + memoria** (`thread_id = demo-multipaso`)

```
[01] Usuario      ¿Cuántos pedidos tuvo el cliente 102, cuál fue el total y qué productos incluyó su último pedido?
[02] Acción       buscar_pedidos(cliente_id=102)
[03] Observación  buscar_pedidos -> {"pedidos": 3, "total": 14500, "ids_pedidos": [P-1001, P-1007, P-1013], ...}
[04] Pensamiento  Ahora obtengo el detalle del último pedido:
[05] Acción       detalle_pedido(pedido_id='P-1013')
[06] Observación  detalle_pedido -> {"total": 5000, "estado": "en camino", "items": ["Monitor 24 pulgadas (seña)"], ...}
[07] Respuesta    Cliente 102 (Martín Acosta): 3 pedidos, total $14.500. Último pedido (P-1013): Monitor 24 pulgadas (seña), $5.000, en camino.
[08] Usuario      ¿y el pedido anterior a ese, cuánto costó?          <- mismo thread_id, sin repetir el cliente
[09] Acción       detalle_pedido(pedido_id='P-1007')                  <- usó el contexto: sabía cuál era "el anterior"
[10] Observación  detalle_pedido -> {"total": 5500, "items": ["Mouse inalámbrico", "Alfombrilla"], ...}
[11] Respuesta    El pedido anterior (P-1007) costó $5.500 e incluía un Mouse inalámbrico y una Alfombrilla.
```

**2. Aclaración y reintento ante un error** (`demo-aclaracion_y_reintento`)

```
[01] Usuario      ¿Qué compró Lucía en su último pedido?
[03] Acción       buscar_cliente(nombre='Lucía')
[04] Observación  {"coincidencias": [103 Lucía Fernández, 104 Lucía Ferrero]}
[05] Respuesta    Tengo dos coincidencias. ¿Cuál es Lucía? ¿Fernández o Ferrero?     <- pide aclaración
[06] Usuario      Lucía Fernández
[08] Acción       buscar_pedidos(cliente_id=103)
[11] Acción       detalle_pedido(pedido_id='P-1019')
[12] Observación  {"error": "Timeout de la base de datos.", "reintentable": true}
[13] Pensamiento  Dejame reintentar:
[14] Acción       detalle_pedido(pedido_id='P-1019')                                  <- segundo intento
[15] Observación  {"items": ["Auriculares", "Webcam HD"], ...}
[16] Respuesta    En su último pedido (P-1019) Lucía Fernández compró Auriculares y Webcam HD, $8.300.
```

**3. Error sin salida** (`demo-error_cliente_inexistente`): `buscar_pedidos(999)` devuelve
un error y el agente lo informa y **pide el dato correcto** en vez de inventar.

**4. Persistencia entre procesos** ([`trazas/traza_persistencia.log`](trazas/traza_persistencia.log)):
en un proceso nuevo, con `--thread demo-multipaso`, el agente respondió «Veníamos hablando
de Martín Acosta (ID 102), $14.500 en 3 pedidos» sin llamar herramientas; con
`--thread otro-hilo` no recordó nada (las sesiones están aisladas).

| Escenario | Llamadas a herramientas |
|---|---|
| multipaso (2 turnos) | 3 (`buscar_pedidos`, `detalle_pedido`, `detalle_pedido`) |
| aclaración y reintento (2 turnos) | 4 (incluye el reintento) |
| cliente inexistente | 1 |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

17 tests con un modelo falso con guion y un SQLite temporal real: las herramientas (total,
cancelados, errores, falla simulada), la estructura del grafo (arista condicional y ciclo),
que el agente no llama herramientas si no hacen falta, el razonamiento multi-paso, el
reintento tras un error, memoria por `thread_id`, aislamiento entre hilos, memoria que
sobrevive a un "reinicio", corte por `recursion_limit` y el recorte de contexto.
