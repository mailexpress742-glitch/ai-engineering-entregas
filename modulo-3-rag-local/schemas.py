"""Modelos Pydantic: lo que devuelve el LLM y la respuesta final con fuentes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

NO_LO_SE = "No lo sé: esa información no está en los documentos disponibles."


class Cita(BaseModel):
    """Respaldo de una afirmación: número de fragmento y texto copiado del contexto."""

    fragmento: int = Field(ge=1, description="Número del fragmento ([1], [2]...) que contiene la cita.")
    cita: str = Field(
        min_length=8,
        description="Texto copiado TAL CUAL del fragmento (máximo 200 caracteres) que respalda la respuesta.",
    )


class RespuestaModelo(BaseModel):
    """Salida que el LLM debe producir (la parsea ``PydanticOutputParser``)."""

    model_config = ConfigDict(extra="forbid")

    respuesta: str = Field(min_length=1, description="Respuesta en español, basada solo en el contexto.")
    en_contexto: bool = Field(
        description="true solo si la respuesta se sostiene con el CONTEXTO; false si no está."
    )
    fuentes: list[Cita] = Field(
        default_factory=list,
        description="Citas textuales que respaldan la respuesta (vacío si en_contexto es false).",
    )

    @model_validator(mode="after")
    def _coherencia(self) -> RespuestaModelo:
        if self.en_contexto and not self.fuentes:
            raise ValueError("si en_contexto es true, fuentes no puede estar vacío")
        if not self.en_contexto:
            self.fuentes = []  # sin respaldo no se citan fuentes
        return self


class Referencia(BaseModel):
    """Un fragmento recuperado en el que se apoya la respuesta."""

    archivo: str
    fragmento: int = Field(description="Número del fragmento dentro del archivo (desde 0).")
    distancia: float = Field(description="Distancia coseno al texto de la pregunta (menor = más cercano).")
    cita: str = Field(description="Cita textual verificada: aparece literalmente en ese fragmento.")


class RagResponse(BaseModel):
    """Respuesta final de ``get_rag_response``: texto + referencias."""

    pregunta: str
    respuesta: str
    en_contexto: bool
    referencias: list[Referencia] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sin_respuesta_sin_fuentes(self) -> RagResponse:
        if self.en_contexto and not self.referencias:
            raise ValueError("una respuesta fundamentada debe traer referencias")
        return self
