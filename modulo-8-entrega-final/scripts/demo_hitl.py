"""Demo de la aprobación humana: un reclamo, la pausa, la decisión y la prueba de que la acción solo ocurre si se aprueba.

    python scripts/demo_hitl.py                  # el aprobador APRUEBA
    python scripts/demo_hitl.py --rechazar       # el aprobador RECHAZA: no se envía ni escala nada
    python scripts/demo_hitl.py --escenario 2    # otro reclamo de scripts/escenarios.py (0..5)
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
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--rechazar", action="store_true")
    ap.add_argument("--escenario", type=int, default=0)
    args = ap.parse_args()
    esc = ESCENARIOS[args.escenario]

    with httpx.Client(base_url=args.url, timeout=30) as http:
        antes = len(http.get("/bandeja").json())
        print(f"1) Reclamo: {esc['nombre']} → {esc['reclamo']['pieza_id']}")
        t0 = time.perf_counter()
        job_id = http.post("/reclamos", json=esc["reclamo"]).json()["job_id"]
        print(f"   job_id = {job_id}  (la API respondió en {time.perf_counter() - t0:.2f} s; los agentes trabajan en segundo plano)")

        job = esperar(http, job_id, {"AWAITING_APPROVAL", "DONE", "FAILED"})
        if job["status"] != "AWAITING_APPROVAL":
            raise SystemExit(f"El reclamo terminó sin pedir aprobación: {job['status']} {job.get('error')}")
        print("\n2) El grafo se PAUSÓ pidiendo aprobación. Propuesta del sistema:")
        print("   " + job["aprobacion_pendiente"]["accion_propuesta"][:900])
        acciones = len(http.get("/bandeja").json()) - antes
        print(f"\n   Acciones realizadas hasta ahora: {acciones}  ← la respuesta al cliente NO salió")

        decision = {"aprobado": not args.rechazar, "comentario": "demo " + ("rechazo" if args.rechazar else "aprobación")}
        print(f"\n3) Decisión humana: {json.dumps(decision, ensure_ascii=False)}")
        http.post(f"/reclamos/{job_id}/aprobar", json=decision)
        job = esperar(http, job_id, {"DONE", "FAILED"})

        nuevas = http.get("/bandeja").json()[antes:]
        print(f"\n4) Estado final: {job['status']} · acciones realizadas: {len(nuevas)}")
        for e in nuevas:
            print(f"   - {e['tipo']} ({e['pieza_id']}): {json.dumps(e['detalle'], ensure_ascii=False)[:300]}")
        print("\nInforme final:\n" + job["resultado"]["respuesta_final"])


if __name__ == "__main__":
    main()
