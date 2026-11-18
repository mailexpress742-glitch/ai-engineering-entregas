#!/usr/bin/env bash
# Levanta TODO el sistema sin Docker (Linux/Mac/Git Bash). Una sola instrucción:   ./run.sh
#
#   1. crea el entorno virtual e instala las dependencias (solo la primera vez)
#   2. Redis: usa el que ya esté en REDIS_URL; si no hay, levanta uno (redis-server, docker o fakeredis de desarrollo)
#   3. sube la base de conocimiento a Pinecone (idempotente)
#   4. Phoenix (si instalaste requirements-phoenix.txt en .venv-phoenix) y la API
#
# Requiere un .env con las keys (copiá .env.example). Con Docker, alcanza con:  docker compose up --build
set -euo pipefail
cd "$(dirname "$0")"
PUERTO="${PUERTO:-8000}"

paso() { printf '\n==> %s\n' "$1"; }
abierto() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

[ -f .env ] || { echo "Falta el archivo .env: copiá .env.example a .env y completá las keys." >&2; exit 1; }

paso "Entorno virtual y dependencias"
PYBIN="python3.12"; command -v "$PYBIN" >/dev/null || PYBIN="python3"; command -v "$PYBIN" >/dev/null || PYBIN="python"
[ -d .venv ] || "$PYBIN" -m venv .venv
if [ -x .venv/Scripts/python.exe ]; then PY=".venv/Scripts/python.exe"; else PY=".venv/bin/python"; fi
"$PY" -m pip install -q --disable-pip-version-check -r requirements.txt -r requirements-dev.txt

paso "Redis (estado de los reclamos, cola y checkpoints)"
if abierto 6379; then echo "Ya hay un Redis en el puerto 6379: se usa ese."
elif command -v redis-server >/dev/null; then redis-server --appendonly yes --daemonize yes >/dev/null; echo "redis-server iniciado."
elif command -v docker >/dev/null; then docker run -d --name mesa-reclamos-redis -p 6379:6379 redis:7-alpine redis-server --appendonly yes >/dev/null; echo "Redis (docker) iniciado."
else "$PY" dev/redis_local.py & echo "Sin Docker ni redis-server: Redis de DESARROLLO (fakeredis). No persiste; no es para producción."
fi
for _ in $(seq 1 20); do abierto 6379 && break; sleep 0.5; done

paso "Base de conocimiento en Pinecone"
if grep -q '^RAG_BACKEND=local' .env; then echo "RAG_BACKEND=local: se omite Pinecone."; else "$PY" scripts/ingestar.py; fi

paso "Phoenix (trazas)"
export PHOENIX_COLLECTOR_ENDPOINT=""
if abierto 6006; then echo "Phoenix ya está en http://localhost:6006"; export PHOENIX_COLLECTOR_ENDPOINT="http://localhost:6006"
elif [ -x .venv-phoenix/bin/python ] || [ -x .venv-phoenix/Scripts/python.exe ]; then
  PHX=".venv-phoenix/bin/python"; [ -x "$PHX" ] || PHX=".venv-phoenix/Scripts/python.exe"
  PHOENIX_WORKING_DIR="$PWD/.phoenix" "$PHX" -m phoenix.server.main serve >/dev/null 2>&1 &
  export PHOENIX_COLLECTOR_ENDPOINT="http://localhost:6006"; echo "Phoenix iniciado en http://localhost:6006"
else echo "Phoenix no está instalado: python -m venv .venv-phoenix && .venv-phoenix/bin/pip install -r requirements-phoenix.txt"; echo "La API arranca igual, pero sin enviar trazas."
fi

paso "API en http://localhost:${PUERTO}/docs"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PUERTO"
