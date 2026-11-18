"""API FastAPI + worker + Redis (fakeredis), con el grafo real y piezas de guion."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.main import create_app
from app.store import AWAITING_APPROVAL, DONE, FAILED, ColaTrabajos, JobStore
from app.worker import Worker, recuperar_huerfanos
from tests.conftest import analista, grafo_con_redis, investigador, sintetizar

RECLAMO = {"texto": "No me llegó la carta documento que envié hace una semana.", "pieza_id": "CD-100231", "cliente": "Estudio Ferraro"}
FLUJO = [("investigador", "buscá"), ("analista", "calculá"), ("sintetizador", "")]
FLUJO_CON_ACCION = [("investigador", ""), ("analista", ""), ("ejecutor", "avisá a la guardia"), ("sintetizador", "")]


class Cliente:
    """Cliente HTTP sobre la app ASGI (con su lifespan: workers y Redis incluidos)."""

    def __init__(self, app):
        self.app = app

    async def __aenter__(self):
        self._ctx = self.app.router.lifespan_context(self.app)
        await self._ctx.__aenter__()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")
        return self.http

    async def __aexit__(self, *exc):
        await self.http.aclose()
        await self._ctx.__aexit__(*exc)


async def esperar(http, job_id, estados, timeout=10.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        job = (await http.get(f"/reclamos/{job_id}")).json()
        if job["status"] in estados:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"el job no llegó a {estados}: último estado {job['status']}")


async def test_post_encola_y_responde_sin_esperar_al_agente(redis_factory):
    async def investigador_lento(entrada):
        await asyncio.sleep(0.6)
        return await investigador(entrada)

    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO, investigador=investigador_lento), redis_factory=redis_factory, workers=1)
    async with Cliente(app) as http:
        t0 = time.monotonic()
        r = await http.post("/reclamos", json=RECLAMO)
        assert time.monotonic() - t0 < 0.3  # respondió mucho antes de que termine el agente
        assert r.status_code == 202 and r.json()["status"] == "PENDING"
        job_id = r.json()["job_id"]

        job = await esperar(http, job_id, {DONE})
        assert job["resultado"]["respuesta_final"] == "Respuesta final de prueba."
        assert job["resultado"]["flujo"] == ["investigador", "analista", "sintetizador"]
        assert {c["agente"] for c in job["resultado"]["contribuciones"]} == {"investigador", "analista"}
        assert job["finished_at"] >= job["started_at"] >= job["created_at"]


async def test_job_inexistente_y_validacion(redis_factory):
    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO), redis_factory=redis_factory, workers=0)
    async with Cliente(app) as http:
        assert (await http.get("/reclamos/nope")).status_code == 404
        for malo in (
            {**RECLAMO, "pieza_id": "XX-1"},  # formato de pieza inválido
            {**RECLAMO, "texto": "corto"},  # texto demasiado corto
            {**RECLAMO, "canal": "paloma"},  # canal fuera del enumerado
            {**RECLAMO, "extra": "no permitido"},  # campos desconocidos prohibidos
            {"texto": RECLAMO["texto"]},  # faltan campos obligatorios
        ):
            assert (await http.post("/reclamos", json=malo)).status_code == 422, malo
        assert (await http.post("/reclamos/nope/aprobar", json={"aprobado": "quizás"})).status_code == 422
        assert (await http.post("/reclamos/nope/aprobar", json={"aprobado": True})).status_code == 404
        assert (await http.get("/salud")).json() == {"redis": "ok", "rag": "no iniciado", "workers": 0, "cola": 0}


async def test_sin_workers_el_job_queda_pendiente_en_la_cola(redis_factory):
    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO), redis_factory=redis_factory, workers=0)
    async with Cliente(app) as http:
        job_id = (await http.post("/reclamos", json=RECLAMO)).json()["job_id"]
        assert (await http.get(f"/reclamos/{job_id}")).json()["status"] == "PENDING"
        assert (await http.get("/salud")).json()["cola"] == 1


async def test_una_excepcion_del_agente_deja_el_job_en_FAILED(redis_factory):
    class GrafoRoto:
        async def ainvoke(self, *a, **k):
            raise RuntimeError("el proveedor de LLM devolvió 500")

    app = create_app(graph=GrafoRoto(), redis_factory=redis_factory, workers=1)
    async with Cliente(app) as http:
        job_id = (await http.post("/reclamos", json=RECLAMO)).json()["job_id"]
        job = await esperar(http, job_id, {FAILED})
        assert "RuntimeError" in job["error"] and "500" in job["error"]
        assert job["finished_at"]  # el cliente deja de hacer polling


async def test_timeout_deja_el_job_en_FAILED(redis_factory):
    async def colgado(entrada):
        await asyncio.sleep(30)

    store = JobStore(redis_factory(True))
    cola = ColaTrabajos(store)
    worker = Worker(grafo_con_redis(redis_factory, *FLUJO, investigador=colgado), store, cola, timeout_s=0.3)
    job_id = await store.crear("consulta de prueba")
    await worker.procesar({"job_id": job_id, "tipo": "run"})
    job = await store.obtener(job_id)
    assert job["status"] == FAILED and "Timeout" in job["error"]


async def test_flujo_hitl_completo_por_la_api(redis_factory):
    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO_CON_ACCION), redis_factory=redis_factory, workers=1)
    async with Cliente(app) as http:
        job_id = (await http.post("/reclamos", json=RECLAMO)).json()["job_id"]
        job = await esperar(http, job_id, {AWAITING_APPROVAL})
        assert job["aprobacion_pendiente"]["tipo"] == "aprobacion_requerida"
        assert (await http.get("/bandeja")).json() == []  # nada se envió todavía

        r = await http.post(f"/reclamos/{job_id}/aprobar", json={"aprobado": True, "comentario": "adelante"})
        assert r.status_code == 202
        job = await esperar(http, job_id, {DONE})
        assert job["resultado"]["aprobacion"] == {"aprobado": True, "comentario": "adelante"}
        assert len((await http.get("/bandeja")).json()) == 1

        assert (await http.post(f"/reclamos/{job_id}/aprobar", json={"aprobado": True})).status_code == 409  # ya resuelto


async def test_rechazo_por_la_api_no_envia_nada(redis_factory):
    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO_CON_ACCION), redis_factory=redis_factory, workers=1)
    async with Cliente(app) as http:
        job_id = (await http.post("/reclamos", json=RECLAMO)).json()["job_id"]
        await esperar(http, job_id, {AWAITING_APPROVAL})
        await http.post(f"/reclamos/{job_id}/aprobar", json={"aprobado": False, "comentario": "no"})
        job = await esperar(http, job_id, {DONE})
        assert job["resultado"]["aprobacion"]["aprobado"] is False
        assert (await http.get("/bandeja")).json() == []
        assert any("RECHAZÓ" in a for a in job["resultado"]["advertencias"])


async def test_la_aprobacion_concurrente_reanuda_una_sola_vez(redis_factory):
    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO_CON_ACCION), redis_factory=redis_factory, workers=1)
    async with Cliente(app) as http:
        job_id = (await http.post("/reclamos", json=RECLAMO)).json()["job_id"]
        await esperar(http, job_id, {AWAITING_APPROVAL})
        codigos = [r.status_code for r in await asyncio.gather(*[http.post(f"/reclamos/{job_id}/aprobar", json={"aprobado": True}) for _ in range(4)])]
        assert codigos.count(202) == 1 and codigos.count(409) == 3
        await esperar(http, job_id, {DONE})
        assert len((await http.get("/bandeja")).json()) == 1


async def test_cinco_peticiones_concurrentes_no_se_bloquean_entre_si(redis_factory):
    async def lento(entrada):
        await asyncio.sleep(0.5)
        return await investigador(entrada)

    app = create_app(graph=grafo_con_redis(redis_factory, *FLUJO, investigador=lento), redis_factory=redis_factory, workers=5)
    async with Cliente(app) as http:
        t0 = time.monotonic()
        ids = [r.json()["job_id"] for r in await asyncio.gather(*[http.post("/reclamos", json=RECLAMO) for i in range(5)])]
        # Mientras los 5 corren, la API sigue respondiendo al instante (el event loop no está bloqueado).
        t1 = time.monotonic()
        assert (await http.get("/salud")).status_code == 200
        assert time.monotonic() - t1 < 0.2
        jobs = await asyncio.gather(*[esperar(http, i, {DONE}) for i in ids])
        assert all(j["status"] == DONE for j in jobs)
        assert time.monotonic() - t0 < 2.0  # en paralelo: ~0.5 s, no 5 × 0.5 s


async def test_los_jobs_huerfanos_se_reencolan_al_reiniciar(redis_factory):
    store = JobStore(redis_factory(True))
    cola = ColaTrabajos(store)
    job_id = await store.crear("consulta de prueba")
    await store.actualizar(job_id, status="RUNNING")  # el proceso murió con el job en curso
    assert await recuperar_huerfanos(store, cola) == 1
    assert await cola.tomar(timeout_s=1) == {"job_id": job_id, "tipo": "continue"}
