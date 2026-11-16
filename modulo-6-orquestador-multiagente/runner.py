"""Ejecución del orquestador con traza del flujo de delegación (log legible + JSON)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from graph import RECURSION_LIMIT

logger = logging.getLogger("orquestador")


@dataclass
class TrazaDelegacion:
    """Qué nodo actuó, en qué orden, y qué aportó (procedencia de cada pieza de información)."""

    consulta: str
    eventos: list[dict[str, Any]] = field(default_factory=list)
    respuesta_final: str = ""
    duracion_s: float = 0.0

    def agregar(self, **evento: Any) -> None:
        self.eventos.append({"orden": len(self.eventos) + 1, **evento})

    def flujo(self) -> list[str]:
        """Secuencia de nodos que intervinieron, p. ej. ['supervisor', 'investigador', ...]."""
        return [e["nodo"] for e in self.eventos]

    def a_dict(self) -> dict[str, Any]:
        return {
            "consulta": self.consulta,
            "flujo": self.flujo(),
            "duracion_s": round(self.duracion_s, 1),
            "eventos": self.eventos,
            "respuesta_final": self.respuesta_final,
        }

    def guardar(self, carpeta: Path, nombre: str) -> None:
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{nombre}.json").write_text(json.dumps(self.a_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (carpeta / f"{nombre}.log").write_text(self.formato_log() + "\n", encoding="utf-8")

    def formato_log(self) -> str:
        lineas = [f"CONSULTA: {self.consulta}", f"FLUJO: {' -> '.join(self.flujo())}", ""]
        for e in self.eventos:
            n = f"[{e['orden']:02d}]"
            if e["nodo"] == "supervisor":
                regla = f"  (regla {e['regla_aplicada']})" if e["regla_aplicada"] else ""
                lineas.append(f"{n} SUPERVISOR   -> {e['siguiente']}{regla}")
                lineas.append(f"       razón: {e['razon']}")
                if e["instruccion"]:
                    lineas.append(f"       instrucción: {e['instruccion']}")
            elif e["nodo"] in ("investigador", "analista"):
                lineas.append(f"{n} {e['nodo'].upper():<12} v{e['version']}  herramientas={e['herramientas_usadas']}  fuentes={e['fuentes']}")
                lineas.append("       " + " ".join(e["contenido"].split())[:500])
            elif e["nodo"] == "sintetizador":
                lineas.append(f"{n} SINTETIZADOR  respuesta final:")
                lineas.append(e["contenido"])
            else:
                lineas.append(f"{n} {e['nodo'].upper()}: {e.get('contenido', '')}")
        return "\n".join(lineas)


async def ejecutar(
    graph: CompiledStateGraph, consulta: str, *, recursion_limit: int = RECURSION_LIMIT
) -> tuple[dict[str, Any], TrazaDelegacion]:
    """Corre una solicitud completa. Devuelve (estado final, traza). Nunca lanza por un bucle."""
    traza = TrazaDelegacion(consulta)
    inicio = time.perf_counter()
    estado: dict[str, Any] = {}
    try:
        # "updates" da lo que produjo cada nodo (para la traza); "values" da el estado COMPLETO ya
        # reducido (los campos acumulativos no se pueden reconstruir sumando updates a mano).
        async for modo, datos in graph.astream(
            {"messages": [HumanMessage(consulta)]},
            {"recursion_limit": recursion_limit},
            stream_mode=["updates", "values"],
        ):
            if modo == "values":
                estado = datos
            else:
                for nodo, salida in datos.items():
                    _registrar(traza, nodo, salida)
    except GraphRecursionError:
        logger.error("Límite de recursión (%d) alcanzado", recursion_limit)
        traza.agregar(nodo="error", contenido=f"límite de recursión de {recursion_limit} pasos alcanzado")
    traza.duracion_s = time.perf_counter() - inicio
    traza.respuesta_final = estado.get("respuesta_final", "")
    return estado, traza


def _registrar(traza: TrazaDelegacion, nodo: str, salida: dict[str, Any]) -> None:
    if nodo == "supervisor":
        d = salida["decisiones"][-1]
        traza.agregar(nodo="supervisor", siguiente=d["siguiente"], razon=d["razon"], instruccion=d["instruccion"],
                      regla_aplicada=d["regla_aplicada"], paso=d["paso"])
    elif nodo in ("investigador", "analista"):
        c = salida["contribuciones"][-1]
        traza.agregar(nodo=nodo, version=c["version"], instruccion=c["instruccion"], contenido=c["contenido"],
                      herramientas_usadas=c["herramientas_usadas"], fuentes=c["fuentes"])
    elif nodo == "sintetizador":
        traza.agregar(nodo="sintetizador", contenido=salida["respuesta_final"])
