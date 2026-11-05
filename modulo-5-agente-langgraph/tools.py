"""Herramientas del agente: una "base de datos" de pedidos simulada.

El LLM decide qué herramienta usar leyendo SOLO el nombre, los parámetros y el docstring,
por eso cada docstring explica qué hace, cuándo usarla y qué devuelve (incluidos los errores).
Las herramientas nunca lanzan excepciones: devuelven un diccionario con la clave ``error``
y una ``sugerencia``, para que el agente pueda corregir el rumbo en el siguiente paso.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

from langchain_core.tools import tool

# ------------------------------------------------------------ datos simulados
CLIENTES: dict[int, str] = {
    101: "Valeria Gómez",
    102: "Martín Acosta",
    103: "Lucía Fernández",
    104: "Lucía Ferrero",
    105: "Tomás Benítez",
}

# id_pedido -> (cliente_id, fecha ISO, total en pesos, estado, items)
PEDIDOS: dict[str, tuple[int, str, int, str, list[str]]] = {
    "P-1001": (102, "2025-03-10", 4000, "entregado", ["Teclado mecánico"]),
    "P-1007": (102, "2025-05-22", 5500, "entregado", ["Mouse inalámbrico", "Alfombrilla"]),
    "P-1013": (102, "2025-08-14", 5000, "en camino", ["Monitor 24 pulgadas (seña)"]),
    "P-1002": (101, "2025-04-02", 12000, "entregado", ["Silla ergonómica"]),
    "P-1019": (103, "2025-09-01", 8300, "entregado", ["Auriculares", "Webcam HD"]),
    "P-1020": (103, "2025-10-05", 2100, "cancelado", ["Hub USB"]),
    "P-1025": (104, "2025-07-19", 15900, "entregado", ["Notebook 14 pulgadas"]),
}

# P-1019 simula una base de datos inestable: falla la primera vez y responde en el reintento.
_PEDIDOS_INESTABLES = {"P-1019"}
_intentos: dict[str, int] = {}


def reset_fallos() -> None:
    """Reinicia el contador de fallos simulados (útil entre pruebas)."""
    _intentos.clear()


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c)).strip()


def _error(mensaje: str, sugerencia: str, **extra: Any) -> dict[str, Any]:
    return {"error": mensaje, "sugerencia": sugerencia, **extra}


# ----------------------------------------------------------------- herramientas
@tool
async def buscar_cliente(nombre: str) -> dict[str, Any]:
    """Busca clientes por NOMBRE o APELLIDO (total o parcial, sin distinguir mayúsculas ni tildes).

    Usala cuando el usuario menciona a un cliente por su nombre y NO conocés su `cliente_id`;
    las demás herramientas necesitan ese número.

    Devuelve `{"coincidencias": [{"cliente_id": int, "nombre": str}, ...]}`.
    - Si hay UNA coincidencia, ya tenés el cliente_id.
    - Si hay VARIAS, la consulta es ambigua: pedile al usuario que aclare cuál de ellas.
    - Si no hay ninguna, devuelve `{"error": ...}`: probá otra escritura o pedí más datos.
    """
    await asyncio.sleep(0)  # punto de cesión: aquí iría la consulta real a la base de datos
    buscado = _normalizar(nombre)
    if not buscado:
        return _error("El nombre está vacío.", "Pedile al usuario el nombre del cliente.")
    hallados = [
        {"cliente_id": cid, "nombre": nom}
        for cid, nom in CLIENTES.items()
        if buscado in _normalizar(nom)
    ]
    if not hallados:
        return _error(f"No hay clientes que coincidan con '{nombre}'.", "Probá con otro nombre o apellido.")
    return {"coincidencias": hallados}


@tool
async def buscar_pedidos(cliente_id: int) -> dict[str, Any]:
    """Devuelve el RESUMEN de pedidos de un cliente a partir de su `cliente_id` numérico.

    Usala para saber cuántos pedidos hizo un cliente, cuánto gastó en total o cuáles son sus
    ids de pedido. NO da los productos: para eso usá `detalle_pedido` con uno de los ids.
    Los pedidos cancelados no suman al total.

    Devuelve `{"cliente_id", "cliente", "pedidos": int, "total": int (pesos),
    "ids_pedidos": [{"id": "P-xxxx", "fecha": "AAAA-MM-DD"}, ...]}` ordenados del más antiguo
    al más reciente (el último de la lista es el pedido más reciente).
    Si el cliente_id no existe devuelve `{"error": ...}`: buscá al cliente por nombre con
    `buscar_cliente` o pedile al usuario el dato correcto.
    """
    await asyncio.sleep(0)
    if cliente_id not in CLIENTES:
        return _error(
            f"No existe el cliente con id {cliente_id}.",
            "Verificá el id con el usuario o buscá al cliente por nombre con buscar_cliente.",
        )
    propios = sorted(
        ((pid, datos) for pid, datos in PEDIDOS.items() if datos[0] == cliente_id),
        key=lambda x: x[1][1],
    )
    validos = [(pid, d) for pid, d in propios if d[3] != "cancelado"]
    return {
        "cliente_id": cliente_id,
        "cliente": CLIENTES[cliente_id],
        "pedidos": len(validos),
        "total": sum(d[2] for _, d in validos),
        "ids_pedidos": [{"id": pid, "fecha": d[1]} for pid, d in validos],
    }


@tool
async def detalle_pedido(pedido_id: str) -> dict[str, Any]:
    """Devuelve el DETALLE de un pedido puntual: fecha, total, estado y productos.

    Usala cuando el usuario pregunta qué incluía un pedido, su estado o su monto, y ya tenés
    el `pedido_id` (formato 'P-1234', lo obtenés con `buscar_pedidos`).

    Devuelve `{"pedido_id", "cliente", "fecha", "total", "estado", "items": [str]}`.
    Si devuelve `{"error": ..., "reintentable": true}` es una falla momentánea de la base de
    datos: volvé a llamar a esta misma herramienta con los mismos argumentos.
    Si el pedido no existe, devuelve `{"error": ...}` sin `reintentable`.
    """
    await asyncio.sleep(0)
    pid = pedido_id.strip().upper()
    if not re.fullmatch(r"P-\d{4}", pid):
        return _error(f"'{pedido_id}' no tiene el formato de un id de pedido.", "Usá el formato P-1234.")
    if pid in _PEDIDOS_INESTABLES:
        _intentos[pid] = _intentos.get(pid, 0) + 1
        if _intentos[pid] == 1:
            return _error(
                "Timeout de la base de datos.", "Reintentá la misma consulta.", reintentable=True
            )
    if pid not in PEDIDOS:
        return _error(f"No existe el pedido {pid}.", "Revisá el id con buscar_pedidos.")
    cliente_id, fecha, total, estado, items = PEDIDOS[pid]
    return {
        "pedido_id": pid,
        "cliente": CLIENTES[cliente_id],
        "fecha": fecha,
        "total": total,
        "estado": estado,
        "items": items,
    }


TOOLS = [buscar_cliente, buscar_pedidos, detalle_pedido]
