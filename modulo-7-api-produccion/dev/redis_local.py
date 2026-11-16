"""Servidor Redis de DESARROLLO para equipos sin Docker (ej. Windows sin WSL).

Levanta un servidor TCP que habla el protocolo de Redis (RESP) usando ``fakeredis``. La API, el
worker y el checkpointer se conectan igual que a un Redis real (``REDIS_URL=redis://localhost:6379/0``).

NO es para producción: no persiste a disco y vive en un solo proceso. Con Docker usá
``docker compose up`` (Redis oficial). El código de la app no cambia entre uno y otro.

    python dev/redis_local.py [puerto]
"""

from __future__ import annotations

import sys

from fakeredis import TcpFakeServer

if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 6379
    servidor = TcpFakeServer(("127.0.0.1", puerto), server_type="redis")
    print(f"Redis de desarrollo (fakeredis) escuchando en redis://127.0.0.1:{puerto}/0", flush=True)
    servidor.serve_forever()
