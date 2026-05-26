"""
Contratos de Datos del Sistema Multi-Agente v1.0
Entregable: models.py
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# Search sources
class SourceType(str, Enum):
    CAREERS_PAGE = "careers_page"
    LINKEDIN = "linkedin"
    INDEED_CR = "indeed_cr"
    GLASSDOOR = "glassdoor"
    BUILTIN = "builtin"
    BEBEE = "bebee"

# Control states
class SourceStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    REQUIRES_LOGIN = "requires_login"


class AgeClassification(str, Enum):
    ACTIVE = "ACTIVE"
    BORDERLINE = "BORDERLINE"
    STALE = "STALE"
    DATE_UNKNOWN = "DATE_UNKNOWN"


class StaleSignal(str, Enum):
    DATE = "date"
    JOB_ID_SEQUENCE = "job_id_sequence"
    NONE = "none"


class SourceURL(BaseModel):
    source_type: SourceType
    url: HttpUrl  # Validación estricta de URLs malformadas
    status: SourceStatus

# Input Container
class RawPosting(BaseModel):
    model_config = ConfigDict(extra='allow')
    title: str = Field(..., description="Título de la vacante")
    department: Optional[str] = Field(None, description="Departamento o área técnica")
    location: str = Field(..., description="Ubicación geográfica del puesto")
    posted_date: Optional[str] = Field(None, description="Fecha de publicación en formato ISO8601 o None")
    job_id: Optional[str] = Field(None, description="Identificador único del job board si existe")
    url: HttpUrl
    description_snippet: str = Field(..., description="Extracto de la descripción obtenido en el scraping inicial")
    source_type: SourceType

# Decision Container (Output)
class FilteredPosting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posting: RawPosting
    age_classification: AgeClassification
    stale_signal: StaleSignal
    archive_flag: bool = Field(
        ..., 
        description="Flag booleano. True si la vacante es obsoleta y debe archivarse."
    )