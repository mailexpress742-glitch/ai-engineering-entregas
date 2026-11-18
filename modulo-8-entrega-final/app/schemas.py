"""Esquemas Pydantic de TODAS las fronteras del sistema.

- API: entrada del reclamo, estado del job, decisión del aprobador, bandeja de salida.
- Herramientas de los agentes: argumentos de entrada y resultados (validados antes de llegar al LLM
  y antes de volver a él).
- Datos: pieza de seguimiento, fragmento de conocimiento.

Un dato mal formado se rechaza en el borde (422 en la API, error de validación en la herramienta)
y nunca llega a la lógica del negocio.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PIEZA_REGEX = r"^(CD|EN|NT)-\d{6}$"  # carta documento / encomienda / notificación + 6 dígitos

Servicio = Literal["carta_documento", "encomienda", "notificacion"]
Zona = Literal["AMBA", "Interior", "Patagonia"]
EstadoPieza = Literal["IMPUESTA", "EN_DISTRIBUCION", "VISITA_1_NEGATIVA", "VISITA_2_NEGATIVA", "ENTREGADA", "DEVUELTA"]
Categoria = Literal["procedimiento", "plazos", "politica", "escalamiento", "plantilla"]
ServicioFiltro = Literal["carta_documento", "encomienda", "notificacion", "acuse"]
Area = Literal["distribucion", "coordinacion_interior", "siniestros", "atencion_corporativa", "legales"]
Prioridad = Literal["baja", "media", "alta", "urgente"]
EstadoJob = Literal["PENDING", "RUNNING", "AWAITING_APPROVAL", "DONE", "FAILED"]


class Estricto(BaseModel):
    """Base: rechaza campos desconocidos (un typo en el cliente es un 422, no un dato ignorado)."""

    model_config = ConfigDict(extra="forbid")


# ============================================================================ datos
class EventoPieza(Estricto):
    fecha: date
    estado: EstadoPieza
    detalle: str


class Pieza(Estricto):
    """Una pieza del seguimiento (fuente: ``data/piezas.json``)."""

    pieza_id: str = Field(pattern=PIEZA_REGEX)
    servicio: Servicio
    cliente: str
    provincia: str
    zona: Zona
    cliente_corporativo: bool
    fecha_imposicion: date
    eventos: list[EventoPieza] = Field(min_length=1)
    estado: EstadoPieza
    fecha_entrega: date | None = None
    acuse_devuelto: bool = False


class Fragmento(Estricto):
    """Un fragmento (chunk) de la base de conocimiento, con sus metadatos."""

    chunk_id: str
    fuente: str  # archivo .md
    seccion: str  # título de la sección ``##``
    categoria: Categoria
    servicio: str  # carta_documento | encomienda | notificacion | acuse | general
    etiquetas: list[str] = Field(default_factory=list)
    texto: str
    embedding_model: str = ""


class ResultadoBusqueda(Estricto):
    fuente: str
    seccion: str
    categoria: str
    servicio: str
    texto: str
    puntaje: float
    encontrado_por: list[Literal["bm25", "vectorial"]]


# ================================================================ herramientas: entradas
class BusquedaIn(Estricto):
    consulta: str = Field(min_length=3, max_length=300, description="Palabras clave del tema a buscar.")
    categoria: Categoria | None = Field(default=None, description="Filtra por tipo de documento.")
    servicio: ServicioFiltro | None = Field(
        default=None, description="Filtra por servicio (incluye siempre los documentos generales)."
    )
    max_resultados: int = Field(default=4, ge=1, le=6)


class PiezaIn(Estricto):
    pieza_id: str = Field(pattern=PIEZA_REGEX, description="Número de pieza, por ejemplo CD-100231.")


class DiasHabilesIn(Estricto):
    desde: date = Field(description="Fecha inicial (AAAA-MM-DD). No se cuenta.")
    hasta: date = Field(description="Fecha final (AAAA-MM-DD). Se cuenta.")


class CalculoIn(Estricto):
    expresion: str = Field(min_length=1, max_length=200, description="Expresión aritmética, p. ej. '5 - 3'.")


class RespuestaClienteIn(Estricto):
    pieza_id: str = Field(pattern=PIEZA_REGEX)
    destinatario: str = Field(min_length=2, max_length=120, description="Nombre del cliente que reclamó.")
    asunto: str = Field(min_length=5, max_length=150)
    mensaje: str = Field(min_length=30, max_length=3000)


class EscalamientoIn(Estricto):
    pieza_id: str = Field(pattern=PIEZA_REGEX)
    area: Area
    prioridad: Prioridad
    resumen: str = Field(min_length=30, max_length=1500, description="Qué pasó y qué se necesita del área.")


# ================================================================ herramientas: salidas
class PiezaConsultada(Estricto):
    """Estado de una pieza más los días hábiles ya calculados (el LLM no cuenta días)."""

    pieza_id: str
    servicio: Servicio
    cliente: str
    zona: Zona
    provincia: str
    cliente_corporativo: bool
    estado: EstadoPieza
    fecha_imposicion: date
    fecha_consulta: date
    dias_habiles_desde_imposicion: int
    ultimo_evento: EventoPieza
    dias_habiles_sin_movimiento: int
    visitas_negativas: int
    fecha_entrega: date | None
    dias_habiles_desde_entrega: int | None
    acuse_devuelto: bool
    historial: list[EventoPieza]


class DiasHabilesOut(Estricto):
    desde: date
    hasta: date
    dias_habiles: int


class EnvioRegistrado(Estricto):
    """Constancia de una acción del ejecutor (respuesta al cliente o escalamiento)."""

    tipo: Literal["respuesta_cliente", "escalamiento"]
    pieza_id: str
    detalle: dict[str, Any]
    ts: float


# ====================================================================== API
class NuevoReclamo(Estricto):
    texto: str = Field(min_length=10, max_length=4000, description="Lo que escribió el cliente.")
    pieza_id: str = Field(pattern=PIEZA_REGEX, description="Pieza sobre la que reclama, p. ej. CD-100231.")
    cliente: str = Field(min_length=2, max_length=120)
    canal: Literal["email", "telefono", "web"] = "web"

    def como_consulta(self) -> str:
        """Texto que recibe el orquestador (el supervisor y los agentes no ven el JSON, solo esto)."""
        return (
            f"RECLAMO de un cliente (canal: {self.canal}).\n"
            f"Cliente: {self.cliente}\nPieza: {self.pieza_id}\nMensaje del cliente: {self.texto}"
        )


class ReclamoCreado(Estricto):
    job_id: str
    status: Literal["PENDING"] = "PENDING"


class AporteAgente(Estricto):
    agente: str
    version: int
    herramientas: list[str]
    fuentes: list[str]


class ResultadoReclamo(Estricto):
    respuesta_final: str
    task_completed: bool
    pasos_del_supervisor: int
    flujo: list[str]
    contribuciones: list[AporteAgente]
    advertencias: list[str]
    aprobacion: dict[str, Any] | None = None


class ReclamoEstado(BaseModel):
    """Estado de un reclamo (job). Permite campos extra (marcas de tiempo) pero valida los clave."""

    model_config = ConfigDict(extra="allow")

    job_id: str
    status: EstadoJob
    consulta: str
    resultado: ResultadoReclamo | None = None
    aprobacion_pendiente: dict[str, Any] | None = None
    error: str | None = None


class DecisionHumana(Estricto):
    aprobado: bool = Field(description="true para autorizar la acción, false para rechazarla.")
    comentario: str = Field(default="", max_length=500)


class AprobacionRecibida(Estricto):
    job_id: str
    status: Literal["RUNNING"] = "RUNNING"
    aprobado: bool


class BusquedaConocimientoIn(BusquedaIn):
    pass


class Salud(Estricto):
    redis: str
    rag: str
    workers: int
    cola: int
