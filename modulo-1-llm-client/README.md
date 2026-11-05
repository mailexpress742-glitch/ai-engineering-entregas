# Módulo 1 — Cliente de LLM robusto y asíncrono

Pre-entrega 1 del curso **AI Engineering** (Coderhouse). Un *Unified Async LLM
Client* en Python 3.12 que permite usar **OpenAI** o **Anthropic** detrás de la
misma interfaz, con llamadas `async/await`, streaming y errores controlados.

## Estructura

```
modulo-1-llm-client/
├── llm_client/
│   ├── schemas.py          # Pydantic: ChatMessage, ModelConfig, ModelResponse, StreamChunk, LLMError
│   ├── base.py             # BaseLLMClient (ABC) con generate() y stream()
│   ├── openai_client.py    # OpenAIClient  -> AsyncOpenAI
│   ├── anthropic_client.py # AnthropicClient -> AsyncAnthropic
│   ├── errors.py           # excepciones de los SDKs -> LLMError estructurado
│   └── manager.py          # AsyncLLMManager: factory + reintentos + errores controlados
├── main.py                 # script de validación (modo normal + streaming)
├── tests/                  # 18 tests sin red ni API keys
├── .env.example
└── requirements.txt
```

## Cómo correrlo

Requiere **Python 3.12**.

```bash
cd modulo-1-llm-client
py -3.12 -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # Linux/Mac: cp .env.example .env
# editá .env y pegá tu API key
python main.py
python main.py --provider anthropic   # cambiar de proveedor sin tocar código
```

`main.py` le hace la pregunta «¿Qué es la entropía?» al modelo, primero en modo
normal y después en streaming (los tokens se imprimen a medida que llegan).

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `LLM_PROVIDER` | no (`openai`) | `openai` o `anthropic` |
| `OPENAI_API_KEY` | si usás OpenAI | API key de OpenAI |
| `ANTHROPIC_API_KEY` | si usás Anthropic | API key de Anthropic |
| `LLM_MODEL` | no | por defecto `gpt-4o-mini` / `claude-haiku-4-5` |
| `LLM_TEMPERATURE` | no (`0.7`) | entre 0 y 2 (validado con Pydantic) |
| `LLM_MAX_TOKENS` | no (`1024`) | mayor a 0 |
| `LLM_TIMEOUT` | no (`60`) | segundos por llamada |
| `LLM_MAX_RETRIES` | no (`3`) | reintentos ante rate limit / red / timeout |

## Uso como librería

```python
import asyncio
from llm_client import AsyncLLMManager, ChatMessage, ModelConfig

async def demo():
    config = ModelConfig(provider="anthropic", model="claude-haiku-4-5", temperature=0.2)
    async with AsyncLLMManager(config) as llm:      # o AsyncLLMManager.from_env()
        msgs = [ChatMessage(role="user", content="Hola")]

        resp = await llm.generate(msgs)
        print(resp.content if resp.ok else resp.error)

        async for chunk in llm.stream(msgs):
            print(chunk.error or chunk.text, end="", flush=True)

asyncio.run(demo())
```

## Decisiones de diseño

- **Intercambiabilidad:** `BaseLLMClient` define `generate()` y `stream()`; cada
  proveedor absorbe sus diferencias (en Anthropic el `system` va aparte y el
  texto está en `content[0].text`; en OpenAI en `choices[0].message.content`).
  `AsyncLLMManager` elige la clase según `provider` (patrón Factory).
- **Asincronía:** solo se usan `AsyncOpenAI` y `AsyncAnthropic` con `await`; el
  streaming es un generador asíncrono (`async for` + `yield`). Nada bloquea el
  event loop.
- **Validación:** `ModelConfig` valida temperatura (0–2), `max_tokens > 0`,
  `top_p`, timeout y reintentos. La API key es `SecretStr`: no aparece en logs.
- **Errores controlados, sin crash:** el manager captura las excepciones de los
  SDKs y devuelve un `LLMError` con `kind` (`auth`, `rate_limit`, `network`,
  `timeout`, `bad_request`, `api_error`, `unknown`). Rate limit, red, timeout y
  5xx se **reintentan** con backoff exponencial + jitter; una key inválida no.
  En streaming solo se reintenta si el fallo ocurre antes del primer token (así
  no se duplica texto); un error se informa con un último `StreamChunk(error=…)`.
  Una key faltante también se informa como error `auth`, no como excepción.
- **Retries propios:** los SDKs se crean con `max_retries=0` para que la política
  de reintentos esté en un solo lugar.
- **Nota sobre parámetros de muestreo:** Anthropic admite temperatura de 0 a 1
  (se recorta) y las versiones más recientes de su SDK ya no aceptan
  `temperature`/`top_p`; el cliente solo los envía si el SDK instalado los admite.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Los tests usan clientes falsos: cubren validación, factory, mapeo de errores,
reintentos y streaming sin gastar tokens.
