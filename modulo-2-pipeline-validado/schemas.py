"""Contrato de salida del pipeline: qué debe devolver el LLM, ya validado."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Relleno típico cuando el modelo "tiene que" devolver algo y no hay tecnologías reales.
_PLACEHOLDER = re.compile(
    r"\bunknown\b|\bn/?a\b|no especificad|sin especificar|desconocid|\bninguna\b|\bnone\b|\bnull\b",
    re.IGNORECASE,
)
_GENERICAS = {"sistema", "system", "software", "aplicación", "aplicacion", "servidor"}


class Criticidad(str, Enum):
    baja = "baja"
    media = "media"
    alta = "alta"


class EntidadesTecnicas(BaseModel):
    """Entidades técnicas extraídas de un texto (arquitectura, log de error, etc.)."""

    model_config = ConfigDict(extra="forbid")

    tecnologias: list[str] = Field(
        min_length=1,
        description=(
            "Tecnologías, frameworks, bases de datos o herramientas mencionadas "
            "explícitamente en el texto. Sin duplicados."
        ),
    )
    nivel_de_criticidad: Criticidad = Field(
        description=(
            "Gravedad para el negocio: 'baja' (informativo), 'media' (degradación "
            "parcial) o 'alta' (caída, pérdida de datos o riesgo de seguridad)."
        ),
    )
    resumen_tecnico: str = Field(
        min_length=15,
        max_length=400,
        description="Resumen técnico de 1 o 2 oraciones en español.",
    )

    @field_validator("tecnologias")
    @classmethod
    def _limpiar_tecnologias(cls, value: list[str]) -> list[str]:
        """Quita espacios, descarta vacíos y elimina duplicados (sin distinguir mayúsculas)."""
        vistas: set[str] = set()
        limpias: list[str] = []
        for tech in value:
            tech = tech.strip()
            if _PLACEHOLDER.search(tech) or tech.lower() in _GENERICAS:
                raise ValueError(
                    f"'{tech}' no es una tecnología real; no inventes relleno, usá solo "
                    "tecnologías mencionadas en el texto"
                )
            if tech and tech.lower() not in vistas:
                vistas.add(tech.lower())
                limpias.append(tech)
        if not limpias:
            raise ValueError("la lista de tecnologías no puede quedar vacía")
        return limpias
