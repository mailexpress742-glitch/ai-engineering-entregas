"""Demo de persistencia: un reclamo pausado sobrevive al reinicio de la API (el estado vive en Redis).

Se usa en dos pasos, con el reinicio de la API en el medio:

    python scripts/demo_reinicio.py crear              # envía un reclamo y espera la pausa; imprime el job_id
    #   ... detené la API (Ctrl+C) y volvé a levantarla ...
    python scripts/demo_reinicio.py continuar <job_id> # el reclamo sigue pendiente: lo aprueba y espera el resultado
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from escenarios import ESCENARIOS  # noqa: E402


def esperar(http: httpx.Client, job_id: str, estados: set[str], timeout_s: float = 240) -> dict:
    fin = time.time() + timeout_s
    while time.time() < fin:
        job = http.get(f"/reclamos/{job_id}").json()
        if job["status"] in estados:
            return job
        time.sleep(0.5)
    raise SystemExit(f"Timeout esperando {estados}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paso", choices=["crear", "continuar"])
    ap.add_argument("job_id", nargs="?")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--escenario", type=int, default=5)
    a = ap.parse_args()
    with httpx.Client(base_url=a.url, timeout=30) as http:
        if a.paso == "crear":
            job_id = http.post("/reclamos", json=ESCENARIOS[a.escenario]["reclamo"]).json()["job_id"]
            job = esperar(http, job_id, {"AWAITING_APPROVAL", "DONE", "FAILED"})
            print(f"job_id = {job_id}\nestado = {job['status']}  (pausado esperando aprobación)")
            print("Ahora reiniciá la API y corré:  python scripts/demo_reinicio.py continuar " + job_id)
            return
        job = http.get(f"/reclamos/{a.job_id}").json()
        print(f"Tras el reinicio, el reclamo sigue en estado: {job['status']}")
        if job["status"] != "AWAITING_APPROVAL":
            raise SystemExit("El reclamo no sobrevivió al reinicio")
        print("Aprobación pendiente recuperada de Redis:", job["aprobacion_pendiente"]["accion_propuesta"][:200].replace("\n", " "))
        http.post(f"/reclamos/{a.job_id}/aprobar", json={"aprobado": True, "comentario": "tras el reinicio"})
        job = esperar(http, a.job_id, {"DONE", "FAILED"})
        print(f"Estado final: {job['status']} · flujo: {job['resultado']['flujo']}")
        acciones = [e for e in http.get("/bandeja").json() if e["pieza_id"] == ESCENARIOS[a.escenario]["reclamo"]["pieza_id"]]
        print(f"Acciones en la bandeja para la pieza: {json.dumps([e['tipo'] for e in acciones])}")


if __name__ == "__main__":
    main()
