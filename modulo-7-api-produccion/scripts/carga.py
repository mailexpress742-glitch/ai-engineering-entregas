"""Prueba de carga: N peticiones CONCURRENTES contra la API y medición de latencias.

    python scripts/carga.py                      # 5 peticiones contra http://localhost:8000
    python scripts/carga.py --n 5 --url http://localhost:8000 --salida evidencia/carga.json

Mide, del lado del cliente, (a) el tiempo que tarda el POST en devolver el job_id (la API no se
bloquea) y (b) la latencia de punta a punta de cada job hasta DONE. El costo por ejecución y la
latencia p95 "oficiales" se leen del dashboard de Phoenix (ver README); acá se calcula también p95
para contrastarlo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

import httpx

CONSULTAS = [
    "Según la documentación de respuesta a incidentes, ¿cuál es el tiempo de respuesta de un SEV1? "
    "Calculá cuántos minutos suman 3 incidentes SEV1 y 2 SEV2 si cada uno se responde en su tiempo máximo.",
    "¿Cada cuánto se debe actualizar el estado durante un SEV1 y cuál es el RTO de las bases de datos de producción? "
    "Con eso calculá cuántas actualizaciones habría en un SEV1 que dura lo mismo que el RTO.",
    "¿Cuál es la política de retención de los backups diarios y semanales? Calculá cuántos días suman 4 semanas de "
    "backups semanales más la retención de los diarios.",
    "¿Qué pasos hay que seguir para un despliegue a producción y cuánto dura la ventana de despliegue? "
    "Calculá cuántas horas hay en 5 ventanas de despliegue.",
    "¿Qué requisitos de seguridad tiene un nuevo ingreso en su primera semana? Contá cuántos requisitos son y "
    "calculá qué porcentaje representan 3 de ellos.",
]


def percentil(valores: list[float], p: float) -> float:
    """Percentil por rango más cercano (con 5 muestras, p95 = el máximo)."""
    orden = sorted(valores)
    return orden[max(0, math.ceil(p / 100 * len(orden)) - 1)]


async def una(http: httpx.AsyncClient, consulta: str, timeout_s: float) -> dict:
    t0 = time.perf_counter()
    r = await http.post("/tasks", json={"consulta": consulta})
    r.raise_for_status()
    t_post = time.perf_counter() - t0
    job_id = r.json()["job_id"]
    while time.perf_counter() - t0 < timeout_s:
        job = (await http.get(f"/tasks/{job_id}")).json()
        if job["status"] in ("DONE", "FAILED", "AWAITING_APPROVAL"):
            return {
                "job_id": job_id,
                "status": job["status"],
                "post_s": round(t_post, 3),
                "total_s": round(time.perf_counter() - t0, 2),
                "pasos": job.get("resultado", {}).get("pasos_del_supervisor"),
                "error": job.get("error"),
            }
        await asyncio.sleep(0.5)
    return {"job_id": job_id, "status": "TIMEOUT", "post_s": round(t_post, 3), "total_s": timeout_s}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--salida", type=Path, default=None, help="guarda el resumen en este JSON")
    args = ap.parse_args()

    consultas = [CONSULTAS[i % len(CONSULTAS)] for i in range(args.n)]
    async with httpx.AsyncClient(base_url=args.url, timeout=30) as http:
        t0 = time.perf_counter()
        res = await asyncio.gather(*(una(http, q, args.timeout) for q in consultas))  # todas a la vez
        pared = time.perf_counter() - t0

    totales = [r["total_s"] for r in res if r["status"] == "DONE"]
    resumen = {
        "peticiones": args.n,
        "ok": len(totales),
        "tiempo_total_pared_s": round(pared, 1),
        "post_max_s": max(r["post_s"] for r in res),
        "latencia_s": {
            "p50": round(percentil(totales, 50), 2) if totales else None,
            "p95": round(percentil(totales, 95), 2) if totales else None,
            "max": round(max(totales), 2) if totales else None,
        },
        "jobs": res,
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
