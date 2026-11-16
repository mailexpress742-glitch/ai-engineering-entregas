# Módulo 7 — API de producción y monitoreo activo

API REST (FastAPI) que expone el **orquestador multi-agente del Módulo 6** sin bloquearse: recibe la tarea, la
encola y devuelve un `job_id`. El estado de los jobs, la cola y los checkpoints de LangGraph viven en **Redis**;
cada ejecución se traza en **Arize Phoenix**; y las acciones con efectos secundarios exigen **aprobación humana**
(human-in-the-loop).

```
Cliente ──POST /tasks──► FastAPI ──RPUSH──► Redis (cola jobs:queue)         Phoenix (trazas, costo, latencia)
   ▲                        │                    │ BLPOP                          ▲
   │                        │                    ▼                                │ OpenTelemetry
   └──GET /tasks/{id}───────┴──────────── Workers asyncio ──► Grafo LangGraph ────┘
   └──POST /tasks/{id}/approve                    │              (supervisor · investigador · analista
                                                  ▼               · aprobación humana · ejecutor · sintetizador)
                              Redis: job:{id} (estado) · lg:* (checkpoints del grafo) · outbox
```

## Dónde está cada requisito de la consigna

| Criterio | Dónde se cumple | Cómo comprobarlo |
|---|---|---|
| **API asíncrona (30 %)** | [`app/main.py`](app/main.py): `POST /tasks` solo escribe en Redis y responde `202` + `job_id`. Los workers ([`app/worker.py`](app/worker.py)) corren el grafo con `ainvoke` (async nativo: nada de llamadas síncronas en el event loop). | `tests/test_api.py::test_post_encola_y_responde_sin_esperar_al_agente` y `::test_cinco_peticiones_concurrentes_no_se_bloquean_entre_si` |
| **Redis (25 %)** | Estado del job en `job:{id}` y cola en `jobs:queue` ([`app/store.py`](app/store.py)); checkpoints de LangGraph en [`app/redis_checkpointer.py`](app/redis_checkpointer.py) (`thread_id` = `job_id`). Una excepción o un timeout dejan el job en `FAILED`. | `tests/test_redis_y_hitl.py`, `tests/test_api.py::test_una_excepcion_del_agente_deja_el_job_en_FAILED` |
| **Observabilidad (25 %)** | [`app/observability.py`](app/observability.py): Phoenix + OpenInference (un span por nodo, por llamada al LLM y por herramienta) y decorador `@observar`. Evidencia en [`screenshots/`](screenshots/). | Sección [Resultados de la prueba de carga](#resultados-de-la-prueba-de-carga-5-peticiones-concurrentes) |
| **Human-in-the-loop (15 %)** | [`app/hitl.py`](app/hitl.py): nodo `aprobacion` con `interrupt()` + `POST /tasks/{id}/approve`. | `scripts/demo_hitl.py`, `tests/test_redis_y_hitl.py` |
| **Documentación (5 %)** | Este README, `requirements*.txt`, `.env.example`, `Dockerfile` y `docker-compose.yml`. | — |

## Estructura

```
app/
  main.py               FastAPI: POST /tasks · GET /tasks/{id} · GET /outbox · GET /salud
  worker.py             worker: cola → grafo → estado en Redis (PENDING/RUNNING/AWAITING_APPROVAL/DONE/FAILED)
  graph.py              orquestador del Módulo 6 + nodos de aprobación/ejecutor + checkpointer de Redis
  hitl.py               nodo de aprobación humana (interrupt) y endpoint /approve
  redis_checkpointer.py checkpointer de LangGraph sobre Redis estándar
  store.py              estado de jobs y cola en Redis
  observability.py      Phoenix/OpenInference y decorador @observar
  state.py, supervisor.py, llm.py, agents/   del Módulo 6 (agents/action_agent.py es nuevo)
scripts/carga.py        prueba de carga: N peticiones concurrentes
scripts/demo_hitl.py    demo de la aprobación humana (aprobar / rechazar)
dev/redis_local.py      Redis de desarrollo sin Docker (fakeredis, solo para desarrollo)
screenshots/            capturas del dashboard de Phoenix
evidencia/              salidas reales de las corridas (carga.json, hitl_aprobado.json, hitl_rechazado.json)
tests/                  43 tests (sin red ni API keys)
```

## Cómo levantarlo

### Opción A — Docker Compose (recomendada: Redis real + Phoenix + API)

```bash
cp .env.example .env        # completá ANTHROPIC_API_KEY
docker compose up --build
```

API en http://localhost:8000/docs · Phoenix en http://localhost:6006 · Redis en `localhost:6379`.

### Opción B — sin Docker

Requiere Python 3.12+. Tres terminales:

```bash
# 0) entorno
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                     # completá ANTHROPIC_API_KEY

# 1) Redis: el de tu sistema (redis-server) o, si no podés instalar uno, el de desarrollo incluido:
redis-server                                             # …o:  python dev/redis_local.py

# 2) Phoenix (dashboard de trazas), en otro venv porque es pesado
python -m venv .venv-phoenix && .venv-phoenix/bin/pip install -r requirements-phoenix.txt
.venv-phoenix/bin/python -m phoenix.server.main serve    # http://localhost:6006

# 3) la API (con workers dentro del proceso)
uvicorn app.main:app --port 8000
```

Variables (ver `.env.example`): `REDIS_URL`, `WORKERS` (cuántos jobs corren a la vez, por defecto 5),
`JOB_TIMEOUT_S`, `PHOENIX_COLLECTOR_ENDPOINT` (vacío = sin trazas). Para correr los workers como procesos aparte:
`WORKERS=0 uvicorn app.main:app` y `python -m app.worker` (uno o más); todos comparten Redis.

> **Honestidad sobre Redis:** el desarrollo y la prueba de carga de este repo se hicieron en una máquina Windows sin
> Docker ni WSL, así que corrieron contra `dev/redis_local.py` (un servidor del protocolo Redis hecho con `fakeredis`),
> no contra un `redis-server` real. El código solo usa comandos estándar (hashes, listas, `WATCH`, `BLPOP`), y el
> `docker-compose.yml` levanta `redis:7`, pero **no ejecuté la suite contra un Redis real**. Si lo hacés, el único
> cambio es `REDIS_URL`.

## Uso de la API

```bash
# 1) encolar: responde al instante con el job_id
curl -X POST localhost:8000/tasks -H "Content-Type: application/json" \
  -d '{"consulta": "¿Cada cuánto se actualiza el estado en un SEV1 y cuál es el RTO de las bases de producción? Calculá cuántas actualizaciones hay."}'
# → {"job_id": "5a2d…", "status": "PENDING"}

# 2) consultar el estado (PENDING → RUNNING → DONE | FAILED | AWAITING_APPROVAL)
curl localhost:8000/tasks/5a2d…
```

El resultado trae `respuesta_final`, el `flujo` de decisiones del supervisor, qué agente aportó qué (herramientas
y fuentes) y las advertencias. Si el agente falla, el job queda en `FAILED` con el campo `error`.

### Human-in-the-loop

El supervisor puede decidir el agente **ejecutor**, cuya herramienta (`enviar_comunicado`) tiene efectos secundarios.
Ese camino **no existe sin pasar por el nodo `aprobacion`**: no hay arista directa supervisor → ejecutor (lo verifica
`test_el_ejecutor_no_se_alcanza_sin_pasar_por_la_aprobacion`).

```bash
python scripts/demo_hitl.py              # pide la acción, comprueba que se pausa, aprueba y muestra el resultado
python scripts/demo_hitl.py --rechazar   # igual, pero rechaza: el comunicado NO se envía
```

A mano: el job queda en `AWAITING_APPROVAL` con `aprobacion_pendiente` (acción propuesta y datos de respaldo) y se
reanuda con:

```bash
curl -X POST localhost:8000/tasks/<job_id>/approve -H "Content-Type: application/json" \
  -d '{"aprobado": true, "comentario": "ok"}'      # false para rechazar
```

Detalles que importan: la pausa es un `interrupt()` de LangGraph, cuyo checkpoint queda **en Redis**, así que el
worker queda libre mientras se espera y el job sobrevive a un reinicio. Aprobar dos veces el mismo job reanuda una
sola vez (la segunda recibe `409`; `WATCH` en Redis). Si un humano rechaza, la regla R5 impide que el supervisor
insista y el sintetizador informa que la acción **no** se realizó. Salida real de ambos caminos en
[`evidencia/`](evidencia/).

## Prueba de carga: 5 peticiones concurrentes

Con la API y Phoenix levantados:

```bash
python scripts/carga.py --n 5 --salida evidencia/carga.json
```

Lanza las 5 consultas **a la vez**, mide cuánto tarda cada `POST` en devolver el `job_id` y la latencia de punta a
punta hasta `DONE`. Después abrí Phoenix → proyecto `orquestador-m7` → pestaña **Traces**: las columnas *latency*,
*total tokens* y *total cost* (se activan en *Columns*) dan cada ejecución, y el gráfico *Trace latency* muestra
p50/p90/**p95**/p99 al pasar el mouse.

### Resultados de la prueba de carga (5 peticiones concurrentes)

Modelo `claude-haiku-4-5`, 5 workers, corrida real (`evidencia/carga.json`):

| Métrica | Valor | Fuente |
|---|---|---|
| Peticiones OK | 5 de 5 (`DONE`) | `carga.json` |
| `POST /tasks` (máximo) | 0,52 s | cliente |
| **Latencia p95** | **46,77 s** (p50 22,35 s · p90 46,18 s) | Phoenix, gráfico *Trace latency* |
| Tiempo total de las 5 en paralelo | 48,3 s (≈ el job más lento: corren en paralelo, no en serie) | cliente |
| **Costo por ejecución** | $0,10 · $0,05 · $0,03 · $0,02 · $0,02 | Phoenix, columna *total cost* |
| Costo total de la corrida | $0,22 (168.874 tokens) | Phoenix |

Capturas en [`screenshots/`](screenshots/):

| Archivo | Qué muestra |
|---|---|
| `01_proyecto_5_trazas.jpg` | El proyecto en Phoenix: 5 trazas, 5 sesiones (una por job), latencia P50 |
| `02_costo_y_latencia_por_ejecucion.jpg` | **Costo por ejecución**, tokens y latencia de cada una de las 5 trazas |
| `03_latencia_p50_p95.jpg` | **Latencia p95** (y p50/p75/p90) de la corrida |
| `04_traza_del_grafo_por_nodo.jpg` | Una traza abierta: `job → orquestador → supervisor → investigador → tools → …` |

> Phoenix calcula el costo solo, a partir de los tokens de entrada y salida y de su tabla de precios por modelo.
> En su cabecera muestra P50 y P99; el **p95** está en el gráfico *Trace latency* de la pestaña *Traces*.
> El p95 que imprime `scripts/carga.py` (48,2 s) es del lado del cliente y por eso es algo mayor (incluye el
> `POST` y el intervalo de polling). Con solo 5 muestras, el p95 es prácticamente el máximo: sirve para leer la
> corrida, no para sacar estadística.

### Lectura del dashboard

- **Dónde está la latencia:** la ejecución del **investigador** acumula 119 s de tiempo en las 5 corridas, frente a
  55 s del supervisor, 43 s del analista y 17 s del sintetizador. Es el cuello de botella: es un agente ReAct que
  hace varias búsquedas, y cada una es una vuelta más al LLM.
- **Qué nodo consume más tokens:** el investigador, con el 54 % (91.892 de 168.874): cada llamada reenvía el
  historial con los resultados de búsqueda. Después el supervisor (23 %, 16 llamadas), el analista (18 %) y el
  sintetizador (5 %).
- **La dispersión de costo es grande** ($0,02 a $0,10, 5×): la traza más cara (80.613 tokens) es un job donde el
  investigador buscó varias veces. El costo por consulta depende más de cuántas veces busca el investigador que de
  la longitud de la pregunta; si hubiera que bajar el costo, ahí está la palanca (acotar el número de búsquedas).
- **Un error visible en el dashboard:** en una corrida, Phoenix marcó 1 traza con error. Fue el LLM del supervisor,
  que devolvió una salida estructurada mal formada (puso `siguiente` dentro del texto de `razon`). El sistema no
  falló: la regla R0 del supervisor (heredada del Módulo 6) tomó la ruta de emergencia y el job terminó en `DONE`.
  Es el tipo de cosa que sin trazas pasaría desapercibida.

### Dos problemas que aparecieron al medir (y cómo se resolvieron)

1. **Trazas de polling.** FastAPI reciente emite un span OpenTelemetry por request; con el `GET /tasks/{id}` del
   polling, Phoenix se llenó de cientos de trazas de 10 ms y la latencia mediana mostraba 11 ms. Se desactivaron
   (`telemetry={"tracing": False}` en `create_app`): ahora cada traza es un job.
2. **Costo y tokens duplicados.** El SDK de Anthropic reciente emite además su propio span por llamada, y Phoenix
   sumaba los tokens de ambos: el primer cálculo daba $0,43 y 312.050 tokens para la misma corrida que en realidad
   costó $0,22. Se apagó con `ANTHROPIC_OPEN_TELEMETRY=false` (se fija en `init_observability`); el span del LLM
   sigue estando, lo emite la instrumentación de LangChain. **Las capturas de este repo son de la corrida ya corregida.**

## Decisiones de diseño

- **Checkpointer propio sobre Redis estándar.** El `RedisSaver` oficial (`langgraph-checkpoint-redis`) requiere
  Redis Stack (módulos RediSearch/RedisJSON); `AsyncRedisCheckpointer` implementa el mismo contrato
  (`BaseCheckpointSaver`) con hashes comunes, así que funciona con `redis:7`, con Redis gestionado y con fakeredis
  en los tests. Contrapartida: no es el paquete oficial, y lo escribí contra la API de LangGraph 1.x
  (`tests/test_redis_y_hitl.py` cubre el viaje de ida y vuelta, el historial, el aislamiento por hilo y la
  reanudación tras "reiniciar" con otro cliente).
- **Workers dentro del proceso o aparte.** Tareas asyncio con `BLPOP` sobre la misma cola Redis; el mismo código sirve
  para `python -m app.worker`. Es la opción simple de la consigna; Celery/Arq darían reintentos y prioridades.
- **Jobs huérfanos.** Si el proceso muere con un job `RUNNING`, al reiniciar se reencola y continúa desde su último
  checkpoint (`recuperar_huerfanos`). Supuesto: hay un solo proceso que recupera (con varias réplicas haría falta
  un lock; se puede desactivar con `RECUPERAR_AL_INICIAR=0`).
- **Qué es "crítico".** Hoy, toda acción con efectos secundarios: el único agente que las hace es el ejecutor y su
  herramienta está en `HERRAMIENTAS_CRITICAS`. Quedó afuera el criterio de "costo muy alto" (por ejemplo pedir
  aprobación al superar un presupuesto de tokens); el nodo `aprobacion` ya sirve de punto de enganche.
- **Contexto aislado.** Se mantiene el diseño del Módulo 6: cada especialista recibe solo su instrucción y los datos
  que necesita, no el historial.
- **El envío es simulado.** `enviar_comunicado` registra el mensaje en `outbox` (Redis) y no sale ningún mail. Sirve
  para demostrar que, sin aprobación, el efecto no ocurre (`GET /outbox`).

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q          # 43 tests, sin red ni API keys (Redis simulado con fakeredis)
```

Cubren: el grafo del Módulo 6 (26), el checkpointer, la pausa/aprobación/rechazo del HITL, la reanudación con un
grafo "nuevo" (reinicio), que el POST no espera al agente, el paso a `FAILED` ante excepción y timeout, la
aprobación concurrente (una sola reanudación), 5 jobs en paralelo sin bloquear la API y la recuperación de huérfanos.

## Limitaciones conocidas

- Probado contra `fakeredis`, no contra un `redis-server` real (ver arriba).
- Solo Anthropic y OpenAI como proveedor del LLM (Gemini 3 falla en llamadas a herramientas encadenadas).
- La API no tiene autenticación; `/approve` debería estar protegido en producción (la aprobación es, por definición,
  un permiso).
- El supervisor basado en LLM a veces devuelve salida mal formada (ver el error visible arriba): está cubierto por
  la ruta de emergencia, pero cuesta una llamada extra.
