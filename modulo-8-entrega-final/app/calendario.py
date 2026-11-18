"""Cálculo de días hábiles (lunes a viernes, sin feriados nacionales)."""

from __future__ import annotations

from datetime import date, timedelta

from app import config


def es_habil(d: date, feriados: frozenset[date] | None = None) -> bool:
    feriados = config.FERIADOS_NACIONALES if feriados is None else feriados
    return d.weekday() < 5 and d not in feriados


def dias_habiles_entre(desde: date, hasta: date, feriados: frozenset[date] | None = None) -> int:
    """Días hábiles en el intervalo ``(desde, hasta]``: el día de ``desde`` no cuenta, el de ``hasta`` sí.

    Es la convención del negocio: los plazos se cuentan desde el día hábil SIGUIENTE a la imposición.
    Si ``hasta <= desde`` devuelve 0.
    """
    n, d = 0, desde
    while d < hasta:
        d += timedelta(days=1)
        if es_habil(d, feriados):
            n += 1
    return n


def sumar_dias_habiles(desde: date, dias: int, feriados: frozenset[date] | None = None) -> date:
    """Fecha en que se cumplen ``dias`` días hábiles después de ``desde`` (inversa de ``dias_habiles_entre``)."""
    d, n = desde, 0
    while n < dias:
        d += timedelta(days=1)
        if es_habil(d, feriados):
            n += 1
    return d
