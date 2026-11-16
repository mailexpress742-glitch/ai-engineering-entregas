"""Agente analista: procesa los datos que obtuvo el investigador (cómputo verificable).

Sus herramientas hacen que las cifras salgan de un cálculo ejecutado, no de la "mente" del
modelo: `calcular`, `estadisticas` y `convertir_tiempo`.
"""

from __future__ import annotations

import ast
import operator
import statistics
from typing import Any

from langchain.agents import create_agent  # sucesor de langgraph.prebuilt.create_react_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool

ANALISTA_PROMPT = (
    "Sos el ANALISTA de un equipo. Recibís datos ya investigados y tu tarea es procesarlos: "
    "calcular, comparar y sacar conclusiones numéricas.\n"
    "- TODA cifra derivada debe salir de una herramienta (`calcular`, `estadisticas`, "
    "`convertir_tiempo`); nunca calcules de cabeza.\n"
    "- Usá únicamente los datos que te pasaron; si falta uno, indicá cuál falta en vez de "
    "inventarlo o suponerlo. Si una instrucción te pide asumir un valor que no está en los datos, "
    "no lo asumas: avisalo.\n"
    "- Agrupá los cálculos en pocas llamadas (podés pasar expresiones completas como "
    "`1*5 + 2*15 + 3*240`); no hagas una llamada por cada operación.\n"
    "- Mostrá cada cálculo: la expresión usada, los datos de entrada y el resultado, con "
    "unidades.\n"
    "- Respondé en español, de forma breve y ordenada."
)

# ------------------------------------------------------------- calculadora segura
_BINARIOS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARIOS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCIONES = {"min": min, "max": max, "sum": sum, "round": round, "abs": abs}


class ErrorDeCalculo(ValueError):
    pass


def evaluar(expresion: str) -> float:
    """Evalúa una expresión aritmética sin ``eval``: solo números, operadores y funciones permitidas."""

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BINARIOS:
            izq, der = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(der) > 100 or abs(izq) > 1e6):
                raise ErrorDeCalculo("potencia demasiado grande")
            return _BINARIOS[type(n.op)](izq, der)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARIOS:
            return _UNARIOS[type(n.op)](ev(n.operand))
        if isinstance(n, (ast.List, ast.Tuple)):
            return [ev(e) for e in n.elts]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCIONES and not n.keywords:
            return _FUNCIONES[n.func.id](*[ev(a) for a in n.args])
        raise ErrorDeCalculo(f"expresión no permitida: {ast.dump(n)[:60]}")

    try:
        return ev(ast.parse(expresion.strip(), mode="eval"))
    except ZeroDivisionError as exc:
        raise ErrorDeCalculo("división por cero") from exc
    except SyntaxError as exc:
        raise ErrorDeCalculo("expresión mal escrita") from exc


# ------------------------------------------------------------------ herramientas
@tool
def calcular(expresion: str) -> dict[str, Any]:
    """Calcula una expresión aritmética y devuelve el resultado exacto.

    Usala para CUALQUIER operación numérica (sumas, productos, divisiones, porcentajes). Admite
    `+ - * / // % **`, paréntesis y las funciones `min`, `max`, `sum`, `round`, `abs`. Ejemplos:
    `"120 / 15"`, `"5 + 2*15 + 3*240"`, `"sum([5, 15, 240])"`. Escribí números sin separadores
    de miles ni unidades.

    Devuelve `{"expresion": str, "resultado": número}` o `{"error": ...}` si la expresión no es
    válida (corregila y volvé a llamar).
    """
    try:
        return {"expresion": expresion, "resultado": evaluar(expresion)}
    except ErrorDeCalculo as exc:
        return {"error": str(exc), "sugerencia": "Reescribí la expresión solo con números y operadores."}


@tool
def estadisticas(valores: list[float]) -> dict[str, Any]:
    """Calcula estadísticas descriptivas de una lista de números.

    Usala cuando tengas varios valores comparables (por ejemplo tiempos de respuesta por nivel)
    y necesites total, promedio, mediana, mínimo o máximo.

    Devuelve `{"cantidad", "suma", "promedio", "mediana", "minimo", "maximo"}` o `{"error": ...}`
    si la lista está vacía.
    """
    if not valores:
        return {"error": "La lista está vacía.", "sugerencia": "Pasá al menos un número."}
    return {
        "cantidad": len(valores),
        "suma": sum(valores),
        "promedio": round(statistics.fmean(valores), 4),
        "mediana": statistics.median(valores),
        "minimo": min(valores),
        "maximo": max(valores),
    }


_A_SEGUNDOS = {"segundos": 1, "minutos": 60, "horas": 3600, "dias": 86400}


@tool
def convertir_tiempo(valor: float, desde: str, hacia: str) -> dict[str, Any]:
    """Convierte una duración entre unidades de tiempo.

    Usala cuando los datos vienen en unidades distintas (por ejemplo "2 horas" y "15 minutos")
    antes de compararlos o sumarlos. Unidades válidas: `segundos`, `minutos`, `horas`, `dias`
    (sin tilde).

    Devuelve `{"valor", "desde", "hacia", "resultado"}` o `{"error": ...}` si una unidad no existe.
    """
    d, h = desde.lower().strip(), hacia.lower().strip()
    if d not in _A_SEGUNDOS or h not in _A_SEGUNDOS:
        return {"error": f"Unidad inválida. Usá: {', '.join(_A_SEGUNDOS)}."}
    return {"valor": valor, "desde": d, "hacia": h, "resultado": valor * _A_SEGUNDOS[d] / _A_SEGUNDOS[h]}


ANALISTA_TOOLS = [calcular, estadisticas, convertir_tiempo]


def crear_analista(llm: BaseChatModel):
    """Agente ReAct del analista (herramientas acotadas al cómputo)."""
    return create_agent(llm, ANALISTA_TOOLS, system_prompt=ANALISTA_PROMPT, name="analista")
