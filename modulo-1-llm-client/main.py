"""Script de validación: una pregunta en modo normal y en streaming.

Uso:
    python main.py                      # usa LLM_PROVIDER del .env
    python main.py --provider anthropic
"""

from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from llm_client import AsyncLLMManager, ChatMessage

PREGUNTA = "¿Qué es la entropía?"

MESSAGES = [
    ChatMessage(role="system", content="Respondé en español, en máximo 3 oraciones."),
    ChatMessage(role="user", content=PREGUNTA),
]


async def main(provider: str | None) -> int:
    load_dotenv()
    # El proveedor sale de LLM_PROVIDER (.env) o se pisa con --provider.
    overrides = {"provider": provider} if provider else {}
    async with AsyncLLMManager.from_env(**overrides) as llm:
        cfg = llm.config
        print(f"Proveedor: {cfg.provider} | Modelo: {cfg.model}\n")
        failed = False

        print(f"=== Modo normal: {PREGUNTA}")
        resp = await llm.generate(MESSAGES)
        if resp.ok:
            print(resp.content)
            print(
                f"\n[tokens in/out: {resp.usage.input_tokens}/{resp.usage.output_tokens}"
                f" | fin: {resp.finish_reason}]"
            )
        else:
            failed = True
            print(f"ERROR controlado [{resp.error.kind}]: {resp.error.message}")

        print(f"\n=== Streaming: {PREGUNTA}")
        async for chunk in llm.stream(MESSAGES):
            if chunk.error:
                failed = True
                print(f"\nERROR controlado [{chunk.error.kind}]: {chunk.error.message}")
            else:
                print(chunk.text, end="", flush=True)
        print()
        return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["openai", "anthropic", "gemini"])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.provider)))
