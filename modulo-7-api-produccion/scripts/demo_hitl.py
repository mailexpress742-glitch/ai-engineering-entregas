"""Demo del human-in-the-loop contra la API en marcha: pide una acción crítica, verifica que el job se
pausa SIN ejecutar nada, aprueba (o rechaza) y muestra el resultado.

    python scripts/demo_hitl.py            # aprueba
    python scripts/demo_hitl.py --rechazar # rechaza: el comunicado NO se envía
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

CONSULTA = (
    "Según la documentación de respuesta a incidentes, ¿cada cuánto hay que actualizar el estado en un SEV1 y cuál es "
    "el RTO de las bases de datos de producción? Calculá cuántas actualizaciones hay en un SEV1 de esa duración y "
    "después enviá un comunicado al equipo de guardia con el resultado."
)


def esperar(http: httpx.Client, job_id: str, estados: set[str], timeout: float = 180) -> dict:
    fin = time.time() + timeout
    while time.time() < fin:
        job = http.get(f"/tasks/{job_id}").json()
        if job["status"] in estados:
            return job
        time.sleep(1)
    raise TimeoutError(f"el job no llegó a {estados}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--rechazar", action="store_true")
    ap.add_argument("--salida", type=Path, default=None)
    args = ap.parse_args()
    with httpx.Client(base_url=args.url, timeout=30) as http:
        enviados_antes = len(http.get("/outbox").json())
        job_id = http.post("/tasks", json={"consulta": CONSULTA}).json()["job_id"]
        job = esperar(http, job_id, {"AWAITING_APPROVAL", "DONE", "FAILED"})
        print(f"1) estado: {job['status']}  (el job se pausó esperando aprobación)")
        print("   acción propuesta:", job["aprobacion_pendiente"]["accion_propuesta"][:200], "...")
        print(f"   comunicados enviados hasta ahora: {len(http.get('/outbox').json()) - enviados_antes}  <- debe ser 0")

        decision = {"aprobado": not args.rechazar, "comentario": "rechazado en la demo" if args.rechazar else "aprobado en la demo"}
        print("2) POST /approve:", decision, http.post(f"/tasks/{job_id}/approve", json=decision).status_code)
        job = esperar(http, job_id, {"DONE", "FAILED"})
        enviados = len(http.get("/outbox").json()) - enviados_antes
        print(f"3) estado final: {job['status']}  flujo: {job['resultado']['flujo']}")
        print(f"   comunicados enviados: {enviados}  <- {'1 si se aprobó' if not args.rechazar else '0 si se rechazó'}")
        print("   advertencias:", job["resultado"]["advertencias"])
        if args.salida:
            args.salida.parent.mkdir(parents=True, exist_ok=True)
            args.salida.write_text(json.dumps({"job": job, "comunicados_enviados": enviados}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
