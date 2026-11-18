"""Agente analista: consulta el estado real de la pieza y hace cómputo verificable.

Sus herramientas hacen que los hechos (estado, días hábiles transcurridos) salgan del sistema de
seguimiento y de un cálculo ejecutado, no de la "mente" del modelo:
``consultar_pieza``, ``dias_habiles_entre`` y ``calcular``. Todas con esquemas Pydantic.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from langchain.agents import create_agent  # sucesor de langgraph.prebuilt.create_react_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool

from app.schemas import CalculoIn, DiasHabilesIn, PiezaIn
from app.tracking import PiezaInexistente, RepositorioPiezas

ANALISTA_PROMPT = (
    "Sos el ANALISTA de la mesa de reclamos de MailEx. Recibís la normativa ya investigada (plazos, políticas) "
    "y tu tarea es verificar el caso concreto de la pieza.\n"
    "- Consultá SIEMPRE la pieza con `consultar_pieza`: el estado y los días hábiles transcurridos salen de esa "
    "herramienta, nunca los supongas ni los cuentes de cabeza.\n"
    "- Para cualquier cuenta usá `calcular` (por ejemplo `8 - 5` para los días de atraso) o `dias_habiles_entre`.\n"
    "- Comparás los datos de la pieza contra los plazos que figuran en los datos del investigador y concluís: "
    "¿está dentro del plazo o vencida? ¿cuántos días hábiles de atraso? ¿fue entregada y falta el acuse (y hace "
    "cuánto)? ¿hay visitas negativas? ¿se cumple la presunción de extravío (sin movimientos por el plazo que fija "
    "la política)? ¿qué prioridad y qué área corresponden según la política?\n"
    "- Si en el reclamo el cliente menciona un vencimiento legal próximo o una intimación, concluí que la "
    "prioridad es `urgente` y que corresponde escalar también a `legales` (según la política de reclamos).\n"
    "- Las prioridades válidas son baja, media, alta, urgente; las áreas válidas son distribucion, "
    "coordinacion_interior, siniestros, atencion_corporativa, legales.\n"
    "- Usá únicamente los datos que te pasaron; si falta uno (por ejemplo el plazo del servicio), indicá cuál "
    "falta en vez de inventarlo.\n"
    "- Mostrá cada cálculo: datos de entrada, expresión y resultado, con unidades.\n"
    "- Respondé en español, breve y ordenado."
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
def crear_herramientas_analista(repo: RepositorioPiezas) -> list[BaseTool]:
    async def consultar_pieza(pieza_id: str) -> dict[str, Any]:
        """Consulta el estado actual de una pieza en el sistema de seguimiento.

        Devuelve servicio, zona, cliente, estado, historial de eventos y los días hábiles YA calculados:
        `dias_habiles_desde_imposicion`, `dias_habiles_sin_movimiento`, `visitas_negativas`, `fecha_entrega`,
        `dias_habiles_desde_entrega` y si el acuse fue devuelto. Si la pieza no existe devuelve `{"error": ...}`.
        """
        entrada = PiezaIn(pieza_id=pieza_id)
        try:
            return (await repo.consultar(entrada.pieza_id)).model_dump(mode="json")
        except PiezaInexistente:
            return {"error": f"La pieza {entrada.pieza_id} no existe en el seguimiento."}

    async def dias_habiles_entre(desde: str, hasta: str) -> dict[str, Any]:
        """Cuenta los días hábiles (lunes a viernes, sin feriados nacionales) entre dos fechas AAAA-MM-DD.

        No cuenta la fecha `desde` y sí la fecha `hasta`. Usala para fechas que no vienen ya calculadas en
        `consultar_pieza`.
        """
        entrada = DiasHabilesIn(desde=desde, hasta=hasta)  # type: ignore[arg-type]
        return repo.dias_habiles(entrada.desde, entrada.hasta).model_dump(mode="json")

    async def calcular(expresion: str) -> dict[str, Any]:
        """Calcula una expresión aritmética y devuelve el resultado exacto.

        Usala para CUALQUIER operación numérica (restas de días, comparaciones de plazos, sumas). Admite
        `+ - * / // % **`, paréntesis y `min`, `max`, `sum`, `round`, `abs`. Ejemplos: `"8 - 5"`, `"sum([3, 2])"`.
        Devuelve `{"expresion", "resultado"}` o `{"error": ...}` si la expresión no es válida.
        """
        entrada = CalculoIn(expresion=expresion)
        try:
            return {"expresion": entrada.expresion, "resultado": evaluar(entrada.expresion)}
        except ErrorDeCalculo as exc:
            return {"error": str(exc), "sugerencia": "Reescribí la expresión solo con números y operadores."}

    return [
        StructuredTool.from_function(coroutine=consultar_pieza, name="consultar_pieza", args_schema=PiezaIn),
        StructuredTool.from_function(coroutine=dias_habiles_entre, name="dias_habiles_entre", args_schema=DiasHabilesIn),
        StructuredTool.from_function(coroutine=calcular, name="calcular", args_schema=CalculoIn),
    ]


def crear_analista(llm: BaseChatModel, repo: RepositorioPiezas):
    """Agente ReAct del analista (herramientas acotadas al seguimiento y al cómputo)."""
    return create_agent(llm, crear_herramientas_analista(repo), system_prompt=ANALISTA_PROMPT, name="analista")
