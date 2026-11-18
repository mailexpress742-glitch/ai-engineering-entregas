"""Reclamos de ejemplo (uno por caso del negocio) para las demos y la prueba de carga.

Los datos de cada pieza están en ``data/piezas.json`` (sintéticos, fecha de referencia 2026-11-18).
``esperado`` es lo que debería concluir un buen sistema; ``scripts/carga.py`` lo contrasta con lo que
el ejecutor realmente propuso.
"""

from __future__ import annotations

ESCENARIOS: list[dict] = [
    {
        "nombre": "Carta documento demorada en AMBA",
        "reclamo": {
            "texto": "Hace una semana impusimos esta carta documento y el destinatario dice que no la recibió. "
            "¿Dónde está? Tenemos un vencimiento próximo.",
            "pieza_id": "CD-100231", "cliente": "Estudio Ferraro & Asociados", "canal": "email",
        },
        "esperado": {"escala_a": {"distribucion", "legales"}, "plantilla": "demora"},
    },
    {
        "nombre": "Acuse pendiente de una pieza entregada (AMBA)",
        "reclamo": {
            "texto": "La carta documento figura entregada pero todavía no nos llegó el acuse de recibo.",
            "pieza_id": "CD-100234", "cliente": "Banco del Litoral", "canal": "web",
        },
        "esperado": {"escala_a": {"distribucion"}, "plantilla": "acuse pendiente"},
    },
    {
        "nombre": "Presunto extravío en Patagonia",
        "reclamo": {
            "texto": "Esta carta documento a Neuquén no registra movimientos hace semanas. ¿Se perdió?",
            "pieza_id": "CD-100236", "cliente": "Constructora Andina SRL", "canal": "telefono",
        },
        "esperado": {"escala_a": {"siniestros"}, "plantilla": "extravio"},
    },
    {
        "nombre": "Encomienda demorada en el interior",
        "reclamo": {
            "texto": "Mi encomienda a Tucumán debía llegar ya y sigue en distribución. ¿Cuándo llega?",
            "pieza_id": "EN-204519", "cliente": "Tienda Aurora", "canal": "web",
        },
        "esperado": {"escala_a": {"coordinacion_interior"}, "plantilla": "demora"},
    },
    {
        "nombre": "Notificación de cliente corporativo demorada",
        "reclamo": {
            "texto": "Las notificaciones del lote LT-5581 tienen penalidad por demora. La NT-310077 todavía no se entregó.",
            "pieza_id": "NT-310077", "cliente": "Energía del Plata S.A.", "canal": "email",
        },
        "esperado": {"escala_a": {"atencion_corporativa", "distribucion"}, "plantilla": "demora"},
    },
    {
        "nombre": "Consulta de una pieza dentro del plazo",
        "reclamo": {
            "texto": "Impusimos esta encomienda ayer, ¿en qué estado está?",
            "pieza_id": "EN-204518", "cliente": "Tienda Aurora", "canal": "web",
        },
        "esperado": {"escala_a": set(), "plantilla": "dentro del plazo"},
    },
]
