# Módulo 5 — Agente de razonamiento cíclico con memoria persistente

Pre-entrega 5 del curso **AI Engineering**. Un agente **ReAct** construido con **LangGraph**:
decide por sí mismo cuándo llamar herramientas, se recupera de errores reintentando o pidiendo
aclaraciones, y recuerda la conversación por `thread_id` gracias a un checkpointer SQLite.
Todo asíncrono (`asyncio`), con type hints y Python 3.12.

El dominio es una "base de datos" de clientes y pedidos simulada (`tools.py`).

## Verificación rápida (30 segundos, sin API key)

```bash
pip install -r requirements-dev.txt
python verificar_entrega.py      # comprueba los 12 puntos del checklist contra el código y las trazas
python memoria.py                # lista, con SqliteSaver, lo que quedó guardado por cada thread_id
pytest                           # 20 tests
```

Salida de `python verificar_entrega.py` (12/12):

```
[PASS] Python 3.12+
[PASS] Estado hereda de MessagesState             graph.py: class EstadoAgente(MessagesState)
[PASS] StateGraph: nodo modelo + nodo herramientas + arista condicional
[PASS] tools_condition y llm.bind_tools()
[PASS] Al menos 1 herramienta @tool con docstring tools.py: buscar_cliente, buscar_pedidos, detalle_pedido
[PASS] Persistencia con SqliteSaver               trazas/memoria_demo.sqlite guarda 3 hilos
[PASS] thread_id recuerda la sesión               demo-multipaso conserva 2 turnos (10 mensajes)
[PASS] recursion_limit definido                   RECURSION_LIMIT = 10
[PASS] Prueba multi-paso (herramienta >= 2 veces) 4 llamadas: buscar_cliente, buscar_pedidos, detalle_pedido x2
[PASS] Ciclo de retorno: reintento tras un error
[PASS] Traza de ejemplo en .json y .log
[PASS] Sin API keys en el repositorio
12/12 puntos verificados
```

## Mapa: consigna y rúbrica → evidencia

| Requisito de la consigna / rúbrica | Dónde está | Cómo verificarlo |
|---|---|---|
| `StateGraph` que **hereda de `MessagesState`** (rúbrica: Arquitectura del grafo, 30 %) | `graph.py`: `class EstadoAgente(MessagesState)` + `StateGraph(EstadoAgente)` | `verificar_entrega.py` · `tests/test_agente.py::test_el_estado_hereda_de_messagesstate_con_reducer_propio` |
| Reducer (`operator.add`) y estado inmutable | `graph.py`: `llamadas_a_herramientas: Annotated[int, operator.add]`; `messages` usa `add_messages` | `test_reducer_operator_add_acumula_las_llamadas_a_herramientas` |
| Nodo del modelo + nodo de herramientas + arista condicional `tools_condition` | `graph.py`: `add_node("agente")`, `add_node("tools", ToolNode)`, `add_conditional_edges("agente", tools_condition)`, `add_edge("tools", "agente")` | `test_estructura_del_grafo` |
| LLM vinculado a las herramientas `llm.bind_tools()` | `graph.py`: `llm.bind_tools(TOOLS)` | `verificar_entrega.py` |
| **Autonomía:** el agente decide cuándo llamar una herramienta, sin `if/else` | No hay ruteo manual; solo `tools_condition` | `test_responde_sin_herramientas_si_no_hacen_falta` (no llama herramientas si no hacen falta) |
| ≥ 1 herramienta propia con `@tool` y docstring descriptivo (rúbrica: Integración de herramientas, 35 %) | `tools.py`: 3 herramientas `async`, docstrings con cuándo usarlas, qué devuelven y cómo se corrigen los errores | `test_docstrings_descriptivos_para_el_llm` |
| **Razonamiento multi-paso** (herramienta invocada ≥ 2 veces) | `trazas/traza_ejemplo.json` y `.log`: 3 y 4 llamadas encadenadas | `verificar_entrega.py` |
| **Ciclo de retorno:** ante un error, segundo intento o aclaración | `detalle_pedido("P-1019")` falla una vez y el agente reintenta; ante «Lucía» (2 clientes) pide aclaración; cliente 999 → pide el dato | `trazas/traza_ejemplo.log` · `test_ciclo_de_retorno_reintenta_tras_un_error` |
| Persistencia con **`SqliteSaver`** (rúbrica: Persistencia, 20 %) | Escritura: `main.py` con `AsyncSqliteSaver` (la variante asíncrona del `SqliteSaver`: la síncrona no soporta `ainvoke`/`astream`). Lectura: `memoria.py` con `SqliteSaver` | `python memoria.py --thread demo-multipaso` · `test_la_memoria_se_lee_con_el_sqlitesaver_sincrono` |
| **Resiliencia de estado:** con el mismo `thread_id` recuerda la sesión | `runner.py`: `config = {"configurable": {"thread_id": ...}}` | `trazas/traza_persistencia.log` (procesos distintos) · `test_la_memoria_sobrevive_a_reiniciar_el_proceso` · `test_otro_thread_id_no_comparte_memoria` |
| `recursion_limit` definido (evitar bucles infinitos) | `graph.py`: `RECURSION_LIMIT = 10`, pasado en cada invocación; al excederlo se devuelve un mensaje controlado | `test_recursion_limit_corta_un_bucle_infinito` |
| "Estado sucio": no acumular contexto sin límite | `graph.py`: `recortar_contexto` (`trim_messages`, 24 mensajes) | `test_recortar_contexto_limita_y_no_separa_herramienta_de_resultado` |
| Código limpio: Python 3.12, type hints, `asyncio` | Todo el código; `pyproject.toml` (`requires-python >= 3.12`) | `python verificar_entrega.py` |
| Traza de ejecución `.json` / `.log` | `trazas/traza_ejemplo.json`, `trazas/traza_ejemplo.log`, `trazas/traza_persistencia.log` | abrir los archivos |
| README de cómo levantar el entorno (rúbrica: Calidad del repositorio, 15 %) | este archivo + `requirements.txt` + `pyproject.toml` + `.env.example` | — |
| Sin API keys (variables de entorno) | `.env` ignorado por git; solo `.env.example` | `verificar_entrega.py` (escanea el repo y `git ls-files`) |

## Estructura

```
modulo-5-agente-langgraph/
├── graph.py              # EstadoAgente(MessagesState) + StateGraph: agente, tools, tools_condition
├── tools.py              # 3 herramientas @tool async + datos simulados
├── runner.py             # ejecutar_turno(): astream + traza ReAct + manejo de recursion_limit
├── main.py               # CLI: --demo, --thread/--pregunta, modo interactivo (AsyncSqliteSaver)
├── memoria.py            # lee la memoria con SqliteSaver (sync) para inspeccionarla
├── verificar_entrega.py  # verificador automático del checklist (12 puntos)
├── llm.py                # fábrica del LLM (Anthropic / OpenAI)
├── trazas/               # traza_ejemplo.json/.log, traza_persistencia.log, memoria_demo.sqlite
├── tests/                # 20 tests sin red ni API keys
├── pyproject.toml · requirements.txt · requirements-dev.txt · .env.example
```

## Cómo levantar el entorno

Requiere **Python 3.12**.

```bash
cd modulo-5-agente-langgraph
py -3.12 -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt # alternativa: pip install -e ".[dev]"
copy .env.example .env          # Linux/Mac: cp .env.example .env
# editá .env: LLM_PROVIDER y la API key del proveedor elegido

python main.py --demo                                   # corre los escenarios y regenera trazas/
python main.py --thread ana --pregunta "¿Cuántos pedidos tuvo el cliente 102?"
python main.py --thread ana --pregunta "¿y el último?"  # mismo thread_id: recuerda el contexto
python main.py --thread ana                             # modo interactivo
```

| Variable | Descripción |
|---|---|
| `LLM_PROVIDER` | `anthropic` (por defecto) u `openai` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | key del proveedor elegido |
| `CHECKPOINT_DB` | archivo SQLite de la memoria (por defecto `agente_memoria.sqlite`) |
| `RECURSION_LIMIT` | techo de pasos por invocación (por defecto 10) |

> **Gemini no es compatible con este agente.** Los modelos Gemini 3 exigen conservar la
> `thought_signature` en las llamadas a herramientas y el endpoint compatible con OpenAI no la
> propaga: falla con HTTP 400 en el segundo paso del ciclo.

## Cómo funciona

```
START ─► agente ──(tools_condition)──► tools
           ▲                             │
           └─────────────────────────────┘      (si no pide herramientas ─► END)
```

- **Nodo `agente`:** llama al LLM con las herramientas enlazadas (`llm.bind_tools()`).
- **Nodo `tools`:** `ToolNode` ejecuta lo que el modelo pidió y devuelve los resultados.
- **Arista condicional `tools_condition`:** si el último mensaje trae `tool_calls` va a `tools`;
  si no, termina. **No hay `if/else` manuales:** el modelo decide solo.
- **Herramientas:** `buscar_cliente(nombre)`, `buscar_pedidos(cliente_id)` y
  `detalle_pedido(pedido_id)`. Nunca lanzan excepciones: devuelven `{"error", "sugerencia"}`
  para que el agente corrija el rumbo. `detalle_pedido("P-1019")` simula una base inestable:
  falla la primera vez (`"reintentable": true`) y responde en el reintento.
- **Persistencia:** cada `thread_id` tiene su propio historial en el archivo SQLite, que sobrevive
  a reiniciar el proceso.
- **Límites:** `recursion_limit` corta bucles; `trim_messages` limita lo que ve el modelo (el
  historial completo sigue en el checkpointer).

## Traza de ejecución

Salida real del demo (`python main.py --demo`, `claude-haiku-4-5`); el detalle completo está en
[`trazas/traza_ejemplo.log`](trazas/traza_ejemplo.log) y
[`trazas/traza_ejemplo.json`](trazas/traza_ejemplo.json).

**1. Razonamiento multi-paso + memoria** (`thread_id = demo-multipaso`)

```
[01] Usuario      ¿Cuántos pedidos tuvo el cliente 102, cuál fue el total y qué productos incluyó su último pedido?
[02] Acción       buscar_pedidos(cliente_id=102)
[03] Observación  buscar_pedidos -> {"pedidos": 3, "total": 14500, "ids_pedidos": [P-1001, P-1007, P-1013], ...}
[04] Pensamiento  Ahora obtengo el detalle del último pedido:
[05] Acción       detalle_pedido(pedido_id='P-1013')
[06] Observación  detalle_pedido -> {"total": 5000, "estado": "en camino", "items": ["Monitor 24 pulgadas (seña)"], ...}
[07] Respuesta    Martín Acosta (cliente 102): 3 pedidos, total $14.500. Último pedido P-1013: Monitor 24 pulgadas (seña), $5.000, en camino.
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
[05] Respuesta    Encontré dos clientes con el nombre Lucía... ¿Cuál de ellas es?     <- pide aclaración
[06] Usuario      Lucía Fernández
[07] Acción       buscar_pedidos(cliente_id=103)
[10] Acción       detalle_pedido(pedido_id='P-1019')
[11] Observación  {"error": "Timeout de la base de datos.", "reintentable": true}
[12] Pensamiento  Deja que reintente:
[13] Acción       detalle_pedido(pedido_id='P-1019')                                  <- segundo intento
[14] Observación  {"items": ["Auriculares", "Webcam HD"], ...}
[15] Respuesta    En su último pedido (P-1019) Lucía Fernández compró Auriculares y Webcam HD, $8.300.
```

**3. Error sin salida** (`demo-error_cliente_inexistente`): `buscar_pedidos(999)` devuelve un error y
el agente lo informa y **pide el dato correcto** en vez de inventar.

**4. Persistencia entre procesos** ([`trazas/traza_persistencia.log`](trazas/traza_persistencia.log)):
en un proceso nuevo, con `--thread demo-multipaso`, el agente respondió «Veníamos hablando de
Martín Acosta (cliente 102), quien había gastado un total de $14.500» sin llamar herramientas; con
`--thread otro-hilo` no recordó nada (las sesiones están aisladas).

| Escenario | Llamadas a herramientas |
|---|---|
| multipaso (2 turnos) | 3 (`buscar_pedidos`, `detalle_pedido`, `detalle_pedido`) |
| aclaración y reintento (2 turnos) | 4 (incluye el reintento) |
| cliente inexistente | 1 |

La base de memoria del demo se incluye en [`trazas/memoria_demo.sqlite`](trazas/memoria_demo.sqlite):
`python memoria.py --db trazas/memoria_demo.sqlite --thread demo-multipaso` muestra el historial
guardado, leído con `SqliteSaver`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

20 tests con un modelo falso con guion y un SQLite temporal real: herramientas (total, cancelados,
errores, falla simulada), estructura del grafo, estado heredado de `MessagesState` con reducer
`operator.add`, el agente no llama herramientas si no hacen falta, razonamiento multi-paso,
reintento tras un error, memoria por `thread_id`, aislamiento entre hilos, memoria que sobrevive a
un "reinicio", lectura con `SqliteSaver`, corte por `recursion_limit` y recorte de contexto.
