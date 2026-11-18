"""Agente investigador: consulta la base de conocimiento con el **RAG híbrido** (BM25 + Pinecone).

Sus herramientas son de solo lectura, asíncronas y con esquemas Pydantic de entrada y de salida.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent  # sucesor de langgraph.prebuilt.create_react_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ValidationError

from app.rag.sistema import RAGSystem
from app.schemas import BusquedaIn

INVESTIGADOR_PROMPT = (
    "Sos el INVESTIGADOR de la mesa de reclamos de MailEx (correo y logística). Tu única tarea es encontrar "
    "en la base de conocimiento los procedimientos, plazos, políticas y plantillas que aplican al reclamo.\n"
    "- Buscá siempre con `buscar_conocimiento`; no respondas de memoria ni inventes datos.\n"
    "- Hacé como MÁXIMO 4 búsquedas, una por tema (por ejemplo: plazo de entrega del servicio y la zona; "
    "política según el caso; área a la que corresponde escalar; plantilla de respuesta). Usá los filtros "
    "`servicio` y `categoria` cuando sepas el servicio de la pieza (las siglas del número: CD = carta_documento, "
    "EN = encomienda, NT = notificacion).\n"
    "- Reportá los datos EXACTOS (cifras, plazos, nombres de áreas, texto de las plantillas) tal como figuran, y "
    "citá la fuente como `archivo#sección`.\n"
    "- NO calcules ni juzgues si un plazo está vencido: de eso se ocupa el analista. Si algo no está en los "
    "documentos, decilo explícitamente en vez de suponerlo.\n"
    "- Respondé en español, en formato claro (lista o tabla)."
)


def _a_dict(modelo: BaseModel) -> dict[str, Any]:
    return modelo.model_dump(mode="json")


def crear_herramientas_investigador(rag: RAGSystem) -> list[BaseTool]:
    """Las herramientas comparten el mismo ``RAGSystem`` (índice BM25 + Pinecone)."""

    async def buscar_conocimiento(
        consulta: str, categoria: str | None = None, servicio: str | None = None, max_resultados: int = 4
    ) -> dict[str, Any]:
        """Busca en la base de conocimiento de MailEx (RAG híbrido: léxico + semántico).

        Usala para obtener plazos de entrega, procedimientos, políticas de reclamos, áreas de escalamiento
        y plantillas de respuesta. Escribí la consulta con palabras clave ("plazo entrega carta documento
        interior", "escalar acuse pendiente"). `servicio` (carta_documento | encomienda | notificacion |
        acuse) y `categoria` (procedimiento | plazos | politica | escalamiento | plantilla) acotan la búsqueda;
        los documentos generales se incluyen siempre.

        Devuelve `{"resultados": [{"fuente", "seccion", "categoria", "servicio", "texto", "puntaje",
        "encontrado_por"}, ...]}` ordenados por relevancia. Si no hay coincidencias devuelve resultados
        vacíos: probá otras palabras clave.
        """
        try:
            entrada = BusquedaIn(
                consulta=consulta, categoria=categoria, servicio=servicio, max_resultados=max_resultados  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return {"error": "Argumentos inválidos", "detalle": exc.errors(include_url=False, include_context=False)}
        hallados = await rag.buscar(
            entrada.consulta, categoria=entrada.categoria, servicio=entrada.servicio, k=entrada.max_resultados
        )
        if not hallados:
            return {"resultados": [], "sugerencia": "Sin coincidencias: probá con otras palabras clave."}
        return {"resultados": [_a_dict(r) for r in hallados]}

    async def listar_documentos() -> dict[str, Any]:
        """Lista los documentos de la base de conocimiento, su categoría y las secciones de cada uno.

        Usala UNA vez al empezar si no sabés qué documentación existe. No devuelve contenido: para eso usá
        `buscar_conocimiento`.
        """
        docs: dict[str, dict[str, Any]] = {}
        for f in rag.fragmentos:
            d = docs.setdefault(f.fuente, {"fuente": f.fuente, "categoria": f.categoria, "servicio": f.servicio, "secciones": []})
            if f.seccion not in d["secciones"]:
                d["secciones"].append(f.seccion)
        return {"documentos": list(docs.values())}

    return [
        StructuredTool.from_function(coroutine=buscar_conocimiento, name="buscar_conocimiento", args_schema=BusquedaIn),
        StructuredTool.from_function(coroutine=listar_documentos, name="listar_documentos"),
    ]


def crear_investigador(llm: BaseChatModel, rag: RAGSystem):
    """Agente ReAct del investigador (herramientas acotadas a la búsqueda)."""
    return create_agent(llm, crear_herramientas_investigador(rag), system_prompt=INVESTIGADOR_PROMPT, name="investigador")
