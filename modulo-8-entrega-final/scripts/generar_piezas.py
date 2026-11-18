"""Genera ``data/piezas.json``: el seguimiento SINTÉTICO de 20 piezas que usa el analista.

Los datos son inventados (ningún cliente ni pieza real). Las fechas se calculan hacia atrás desde
``HOY_SIMULADO`` para que cada pieza ilustre un caso concreto del negocio y el resultado sea
siempre el mismo.

    python scripts/generar_piezas.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.calendario import es_habil, sumar_dias_habiles  # noqa: E402

IMP, DIST, V1, V2, ENT, DEV = (
    "IMPUESTA", "EN_DISTRIBUCION", "VISITA_1_NEGATIVA", "VISITA_2_NEGATIVA", "ENTREGADA", "DEVUELTA",
)
# (id, servicio, cliente, provincia, zona, días hábiles desde la imposición, eventos, corporativo, acuse devuelto)
# eventos: (días hábiles después de la imposición, estado, detalle)
PIEZAS = [
    ("CD-100231", "carta_documento", "Estudio Ferraro & Asociados", "CABA", "AMBA", 5,
     [(0, IMP, "Impuesta en sucursal Centro"), (1, DIST, "Salió a reparto")], False, False),
    ("CD-100232", "carta_documento", "Marta Quiroga", "Buenos Aires", "AMBA", 2,
     [(0, IMP, "Impuesta en sucursal Norte"), (1, DIST, "Salió a reparto")], False, False),
    ("CD-100233", "carta_documento", "Estudio Ferraro & Asociados", "Mendoza", "Interior", 9,
     [(0, IMP, "Impuesta en sucursal Centro"), (2, DIST, "Salió a reparto"),
      (5, V1, "Ausente; se dejó aviso de visita"), (7, V2, "Ausente; pieza en sucursal a disposición del destinatario")],
     False, False),
    ("CD-100234", "carta_documento", "Banco del Litoral", "CABA", "AMBA", 12,
     [(0, IMP, "Impuesta en sucursal Centro"), (1, DIST, "Salió a reparto"), (3, ENT, "Recibió un tercero en el domicilio")],
     True, False),
    ("CD-100235", "carta_documento", "Banco del Litoral", "Córdoba", "Interior", 20,
     [(0, IMP, "Impuesta en sucursal Centro"), (2, DIST, "Salió a reparto"), (5, ENT, "Recibió el destinatario")],
     True, False),
    ("CD-100236", "carta_documento", "Constructora Andina SRL", "Neuquén", "Patagonia", 25,
     [(0, IMP, "Impuesta en sucursal Centro"), (2, DIST, "Salió a reparto")], False, False),
    ("EN-204518", "encomienda", "Tienda Aurora", "CABA", "AMBA", 1,
     [(0, IMP, "Impuesta en sucursal Centro")], False, False),
    ("EN-204519", "encomienda", "Tienda Aurora", "Tucumán", "Interior", 8,
     [(0, IMP, "Impuesta en sucursal Centro"), (2, DIST, "Salió a reparto")], False, False),
    ("EN-204520", "encomienda", "Laura Benítez", "CABA", "AMBA", 4,
     [(0, IMP, "Impuesta en sucursal Norte"), (1, DIST, "Salió a reparto"), (2, ENT, "Recibió el destinatario")],
     False, True),
    ("EN-204521", "encomienda", "Constructora Andina SRL", "Chubut", "Patagonia", 30,
     [(0, IMP, "Impuesta en sucursal Centro"), (4, DIST, "Salió a reparto")], False, False),
    ("EN-204522", "encomienda", "Tienda Aurora", "Buenos Aires", "AMBA", 6,
     [(0, IMP, "Impuesta en sucursal Norte"), (1, DIST, "Salió a reparto"),
      (2, V1, "Dirección inexistente"), (4, DEV, "Devuelta al remitente: dirección inexistente")], False, False),
    ("NT-310077", "notificacion", "Energía del Plata S.A.", "CABA", "AMBA", 6,
     [(0, IMP, "Impuesta en lote LT-5581"), (2, DIST, "Salió a reparto")], True, False),
    ("NT-310078", "notificacion", "Energía del Plata S.A.", "Córdoba", "Interior", 5,
     [(0, IMP, "Impuesta en lote LT-5581"), (2, DIST, "Salió a reparto")], True, False),
    ("NT-310079", "notificacion", "Energía del Plata S.A.", "Buenos Aires", "AMBA", 7,
     [(0, IMP, "Impuesta en lote LT-5580"), (1, DIST, "Salió a reparto"), (4, ENT, "Recibió el destinatario")],
     True, False),
    ("CD-100237", "carta_documento", "Estudio Ferraro & Asociados", "CABA", "AMBA", 4,
     [(0, IMP, "Impuesta en sucursal Centro"), (1, DIST, "Salió a reparto"),
      (3, V1, "Ausente; se dejó aviso de visita")], False, False),
    ("CD-100238", "carta_documento", "Marta Quiroga", "Mendoza", "Interior", 7,
     [(0, IMP, "Impuesta en sucursal Norte"), (2, DIST, "Salió a reparto")], False, False),
    ("EN-204523", "encomienda", "Laura Benítez", "Buenos Aires", "AMBA", 3,
     [(0, IMP, "Impuesta en sucursal Norte"), (1, DIST, "Salió a reparto")], False, False),
    ("CD-100239", "carta_documento", "Banco del Litoral", "CABA", "AMBA", 15,
     [(0, IMP, "Impuesta en sucursal Centro"), (1, DIST, "Salió a reparto"), (2, ENT, "Recibió el destinatario")],
     True, True),
    ("CD-100240", "carta_documento", "Estudio Ferraro & Asociados", "Mendoza", "Interior", 10,
     [(0, IMP, "Impuesta en sucursal Centro"), (2, DIST, "Salió a reparto"), (6, ENT, "Recibió el destinatario")],
     False, False),
    ("NT-310080", "notificacion", "Energía del Plata S.A.", "Neuquén", "Patagonia", 40,
     [(0, IMP, "Impuesta en lote LT-5502"), (3, DIST, "Salió a reparto"), (5, ENT, "Recibió el destinatario")],
     True, False),
]


def habil_n_antes(hoy: date, n: int) -> date:
    """El día hábil que está ``n`` días hábiles antes de ``hoy`` (n=0 → hoy si es hábil)."""
    d, cont = hoy, 0
    while cont < n or not es_habil(d):
        d -= timedelta(days=1)
        if es_habil(d):
            cont += 1
    return d


def construir() -> list[dict]:
    hoy = config.hoy()
    salida = []
    for pid, servicio, cliente, provincia, zona, trans, eventos, corp, acuse in PIEZAS:
        imp = habil_n_antes(hoy, trans)
        evs = [
            {"fecha": sumar_dias_habiles(imp, off).isoformat(), "estado": est, "detalle": det} for off, est, det in eventos
        ]
        entrega = next((e["fecha"] for e in evs if e["estado"] == ENT), None)
        salida.append({
            "pieza_id": pid, "servicio": servicio, "cliente": cliente, "provincia": provincia, "zona": zona,
            "cliente_corporativo": corp, "fecha_imposicion": imp.isoformat(), "eventos": evs,
            "estado": evs[-1]["estado"], "fecha_entrega": entrega, "acuse_devuelto": acuse,
        })
    return salida


if __name__ == "__main__":
    datos = construir()
    config.PIEZAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.PIEZAS_PATH.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(datos)} piezas escritas en {config.PIEZAS_PATH} (hoy simulado: {config.hoy()})")
