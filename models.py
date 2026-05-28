"""
Contratos de Datos del Sistema Multi-Agente v1.0
Entregable: models.py
"""

from enum import Enum
from typing import List, Optional
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

# Decision Container (Output) — Agent 3
class FilteredPosting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posting: RawPosting
    age_classification: AgeClassification
    stale_signal: StaleSignal
    archive_flag: bool = Field(
        ...,
        description="Flag booleano. True si la vacante es obsoleta y debe archivarse."
    )


# ── AGENT 4: CR Culture Intel ──────────────────────────────────────────────────

class SourceQuality(str, Enum):
    PRIMARY  = "primary"
    DEGRADED = "degraded"
    MINIMAL  = "minimal"

class SentimentValue(str, Enum):
    POSITIVE  = "positive"
    MIXED     = "mixed"
    NEGATIVE  = "negative"
    NO_SIGNAL = "no_signal"

class GrowthCeilingValue(str, Enum):
    HIGH      = "high"
    MEDIUM    = "medium"
    LOW       = "low"
    NO_SIGNAL = "no_signal"

class LayoffRecency(str, Enum):
    RECENT_12MO = "recent_12mo"
    OLDER       = "older"
    NONE        = "none"

class DisambiguationConfidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"

class DeltaDirection(str, Enum):
    CR_HIGHER = "cr_higher"
    CR_LOWER  = "cr_lower"
    PARITY    = "parity"
    UNKNOWN   = "unknown"

class CROriginConfidence(str, Enum):
    VERIFIED   = "verified"
    PROBABLE   = "probable"
    UNVERIFIED = "unverified"

class SentimentCategory(str, Enum):
    MANAGEMENT = "management"
    COMP       = "comp"
    GROWTH     = "growth"
    LAYOFF     = "layoff"
    WLB        = "wlb"


class GlobalVsCRDelta(BaseModel):
    direction: DeltaDirection
    magnitude: Optional[float] = None
    note: str

class CRSentimentSignals(BaseModel):
    management_quality: SentimentValue
    comp_satisfaction:  SentimentValue
    growth_ceiling:     GrowthCeilingValue
    wlb:                SentimentValue
    layoff_mentions:    bool
    layoff_recency:     LayoffRecency

class RepresentativeQuote(BaseModel):
    paraphrase:          str
    sentiment_category:  SentimentCategory
    cr_origin_confidence: CROriginConfidence

class CRCultureIntelOutput(BaseModel):
    source_quality:              SourceQuality
    sources_accessed:            List[str]
    cr_review_count:             Optional[int]   = None
    overall_cr_rating:           Optional[float] = None
    global_rating:               Optional[float] = None
    global_vs_cr_delta:          GlobalVsCRDelta
    cr_disambiguation_confidence: DisambiguationConfidence
    sentiment_signals:           CRSentimentSignals
    representative_quotes:       List[RepresentativeQuote]
    flags:                       List[str] = Field(default_factory=list)


# ── AGENT 5: Inside Scoop for Job Seekers ──────────────────────────────────────

class SignalConfidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"

class OrgFocus(str, Enum):
    ENGINEERING_HUB  = "engineering_hub"
    OPS_SERVICES_HUB = "ops_services_hub"
    SALES_HUB        = "sales_hub"
    MIXED            = "mixed"

class CareerCeiling(str, Enum):
    PRODUCT_ENGINEERING_PRESENT = "product_engineering_present"
    SERVICES_OPS_ONLY           = "services_ops_only"
    AMBIGUOUS                   = "ambiguous"

class SenioritySkew(str, Enum):
    SENIOR = "senior"
    MID    = "mid"
    JUNIOR = "junior"
    MIXED  = "mixed"

class PayTransparency(str, Enum):
    PRESENT = "present"
    ABSENT  = "absent"
    PARTIAL = "partial"

class HiringVelocity(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"
    STALE  = "stale"


class GrowthCue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal:     str
    evidence:   str
    confidence: SignalConfidence

class AmbiguousCue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal:           str
    evidence:         str
    confidence:       SignalConfidence
    ambiguity_reason: str

class StabilityCue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal:     str
    evidence:   str
    confidence: SignalConfidence

class RedFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal:     str
    evidence:   str
    confidence: SignalConfidence

class RoleCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cluster_name:   str
    posting_count:  int
    seniority_skew: SenioritySkew

class InsideScoopOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    growth_cues:              List[GrowthCue]
    ambiguous_cues:           List[AmbiguousCue]
    stability_cues:           List[StabilityCue]
    red_flags:                List[RedFlag]
    red_flags_note:           Optional[str]
    org_focus:                OrgFocus
    org_focus_justification:  str
    career_ceiling:           CareerCeiling
    role_clusters:            List[RoleCluster]
    pay_transparency_signal:  PayTransparency
    hiring_velocity:          HiringVelocity