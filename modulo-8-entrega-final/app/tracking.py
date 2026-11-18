"""Seguimiento de piezas (simulado): repositorio asíncrono sobre ``data/piezas.json``.

La interfaz es la de una base de datos real (``await repo.obtener(id)``): el archivo se lee en un
hilo (``asyncio.to_thread``) para no bloquear el event loop. Cambiar a SQL/API es reemplazar esta clase.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter

from app import config
from app.calendario import dias_habiles_entre
from app.schemas import DiasHabilesOut, Pieza, PiezaConsultada


class PiezaInexistente(LookupError):
    """La pieza no existe en el seguimiento."""


class RepositorioPiezas:
    def __init__(self, ruta: Path | None = None, hoy: date | None = None) -> None:
        self.ruta = Path(ruta or config.PIEZAS_PATH)
        self._hoy = hoy
        self._piezas: dict[str, Pieza] | None = None
        self._lock = asyncio.Lock()

    @property
    def hoy(self) -> date:
        return self._hoy or config.hoy()

    async def _cargar(self) -> dict[str, Pieza]:
        if self._piezas is None:
            async with self._lock:
                if self._piezas is None:
                    crudo = await asyncio.to_thread(self.ruta.read_text, encoding="utf-8")
                    piezas = TypeAdapter(list[Pieza]).validate_python(json.loads(crudo))  # valida TODO el archivo
                    self._piezas = {p.pieza_id: p for p in piezas}
        return self._piezas

    async def obtener(self, pieza_id: str) -> Pieza:
        piezas = await self._cargar()
        if pieza_id not in piezas:
            raise PiezaInexistente(pieza_id)
        return piezas[pieza_id]

    async def consultar(self, pieza_id: str) -> PiezaConsultada:
        """La pieza con los días hábiles ya calculados (lo que ve el analista)."""
        p = await self.obtener(pieza_id)
        hoy = self.hoy
        ultimo = p.eventos[-1]
        return PiezaConsultada(
            pieza_id=p.pieza_id, servicio=p.servicio, cliente=p.cliente, zona=p.zona, provincia=p.provincia,
            cliente_corporativo=p.cliente_corporativo, estado=p.estado, fecha_imposicion=p.fecha_imposicion,
            fecha_consulta=hoy,
            dias_habiles_desde_imposicion=dias_habiles_entre(p.fecha_imposicion, hoy),
            ultimo_evento=ultimo,
            dias_habiles_sin_movimiento=dias_habiles_entre(ultimo.fecha, hoy),
            visitas_negativas=sum(e.estado in ("VISITA_1_NEGATIVA", "VISITA_2_NEGATIVA") for e in p.eventos),
            fecha_entrega=p.fecha_entrega,
            dias_habiles_desde_entrega=dias_habiles_entre(p.fecha_entrega, hoy) if p.fecha_entrega else None,
            acuse_devuelto=p.acuse_devuelto,
            historial=p.eventos,
        )

    @staticmethod
    def dias_habiles(desde: date, hasta: date) -> DiasHabilesOut:
        return DiasHabilesOut(desde=desde, hasta=hasta, dias_habiles=dias_habiles_entre(desde, hasta))
