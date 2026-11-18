"""Prueba de carga y de punta a punta: N reclamos CONCURRENTES contra la API.

    python scripts/carga.py                       # 5 reclamos contra http://127.0.0.1:8000
    python scripts/carga.py --n 6 --salida evidencia/carga.json

Para cada reclamo: (1) POST /reclamos (debe devolver el job_id al instante), (2) espera a que el grafo
se pause pidiendo aprobación, (3) lo aprueba como lo haría una persona (``--rechazar`` lo rechaza) y
(4) espera el informe final. Mide, del lado del cliente, p50/p95 de cada tramo; el costo por ejecución y
la latencia p95 "oficiales" se leen en el dashboard de Phoenix (ver README).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from escenarios import ESCENARIOS  # noqa: E402


def percentil(valores: list[float], p: float) -> float:
    """Percentil por rango más cercano (con 5 muestras, p95 = el máximo)."""
    orden = sorted(valores)
    return orden[max(0, math.ceil(p / 100 * len(orden)) - 1)]


async def esperar_estado(http: httpx.AsyncClient, job_id: str, estados: set[str], t0: float, timeout_s: float) -> dict:
    while time.perf_counter() - t0 < timeout_s:
        job = (await http.get(f"/reclamos/{job_id}")).json()
        if job["status"] in estados:
            return job
        await asyncio.sleep(0.5)
    return {"status": "TIMEOUT"}


async def una(http: httpx.AsyncClient, esc: dict, aprobar: bool, timeout_s: float) -> dict:
    t0 = time.perf_counter()
    r = await http.post("/reclamos", json=esc["reclamo"])
    r.raise_for_status()
    t_post = time.perf_counter() - t0
    job_id = r.json()["job_id"]
    base = {"nombre": esc["nombre"], "pieza_id": esc["reclamo"]["pieza_id"], "job_id": job_id, "post_s": round(t_post, 3)}

    job = await esperar_estado(http, job_id, {"AWAITING_APPROVAL", "DONE", "FAILED"}, t0, timeout_s)
    t_pausa = time.perf_counter() - t0
    if job["status"] != "AWAITING_APPROVAL":
        return {**base, "status": job["status"], "total_s": round(t_pausa, 2), "error": job.get("error")}
    propuesta = job["aprobacion_pendiente"]["accion_propuesta"]
    await http.post(f"/reclamos/{job_id}/aprobar", json={"aprobado": aprobar, "comentario": "prueba de carga"})

    job = await esperar_estado(http, job_id, {"DONE", "FAILED"}, t0, timeout_s)
    total = time.perf_counter() - t0
    res = job.get("resultado") or {}
    return {
        **base, "status": job["status"], "hasta_aprobacion_s": round(t_pausa, 2), "total_s": round(total, 2),
        "accion_propuesta": propuesta, "flujo": res.get("flujo"), "pasos": res.get("pasos_del_supervisor"),
        "advertencias": res.get("advertencias"), "error": job.get("error"),
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--rechazar", action="store_true", help="el aprobador rechaza cada acción")
    ap.add_argument("--salida", type=Path, default=None, help="guarda el resumen en este JSON")
    args = ap.parse_args()

    escenarios = [ESCENARIOS[i % len(ESCENARIOS)] for i in range(args.n)]
    async with httpx.AsyncClient(base_url=args.url, timeout=30) as http:
        t0 = time.perf_counter()
        res = await asyncio.gather(*(una(http, e, not args.rechazar, args.timeout) for e in escenarios))  # todos a la vez
        pared = time.perf_counter() - t0
        bandeja = (await http.get("/bandeja")).json()

    totales = [r["total_s"] for r in res if r["status"] == "DONE"]
    resumen = {
        "reclamos": args.n,
        "ok": len(totales),
        "tiempo_total_pared_s": round(pared, 1),
        "post_max_s": max(r["post_s"] for r in res),
        "latencia_s": {
            "p50": round(percentil(totales, 50), 2) if totales else None,
            "p95": round(percentil(totales, 95), 2) if totales else None,
            "max": round(max(totales), 2) if totales else None,
        },
        "acciones_en_la_bandeja": len(bandeja),
        "jobs": res,
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
