import json
import os
import re
import unicodedata
import anthropic
from dotenv import load_dotenv
from datetime import datetime
from statistics import median
from typing import List, Dict, Optional
from pydantic import BaseModel, ValidationError

# Importamos los contratos desde tu models.py
from models import (
    RawPosting, FilteredPosting, AgeClassification,
    StaleSignal, SourceType
)

load_dotenv()

# --- 1. CONTRATO DE SALIDA PARA EL LLM ---
class LLMFreshnessOutput(BaseModel):
    age_classification: AgeClassification
    stale_signal: StaleSignal
    archive_flag: bool

# --- 2. DEDUPLICACIÓN DETERMINISTA ---
def _normalize_key(text: str) -> str:
    """Lowercase + elimina diacríticos. 'San José' == 'San Jose'."""
    nfkd = unicodedata.normalize('NFKD', text.strip().lower())
    return ''.join(c for c in nfkd if not unicodedata.combining(c))

_SOURCE_PRIORITY = {
    SourceType.CAREERS_PAGE: 0,
    SourceType.BUILTIN:      1,
    SourceType.INDEED_CR:    2,
    SourceType.LINKEDIN:     3,
    SourceType.BEBEE:        4,
}

def deduplicate_jobs(raw_postings: List[RawPosting]) -> List[RawPosting]:
    print(f"Buscando duplicados en {len(raw_postings)} vacantes...")
    unique_map: Dict[str, RawPosting] = {}

    for posting in raw_postings:
        key = _normalize_key(posting.title)

        if key not in unique_map:
            unique_map[key] = posting
        else:
            current_priority  = _SOURCE_PRIORITY.get(unique_map[key].source_type, 99)
            incoming_priority = _SOURCE_PRIORITY.get(posting.source_type, 99)
            if incoming_priority < current_priority:
                unique_map[key] = posting

    deduplicated = list(unique_map.values())
    print(f"Deduplicación completada. Vacantes únicas: {len(deduplicated)}")
    return deduplicated

# --- 3. EVALUACIÓN ESTOCÁSTICA (LLM) ---
def evaluate_job_freshness_with_llm(posting: RawPosting) -> LLMFreshnessOutput:
    client = anthropic.Anthropic()
    
    record_tool = {
        "name": "record_classification",
        "description": "Registra la clasificación de la vacante basada en el análisis semántico del snippet.",
        "input_schema": LLMFreshnessOutput.model_json_schema()
    }

    prompt_content = f"""
    Analiza este extracto de una vacante y determina su 'frescura' u obsolescencia.
    Título: {posting.title}
    Snippet: {posting.description_snippet}
    
    Busca señales implícitas: fechas antiguas, menciones a años pasados, o lenguaje de urgencia.
    Si encuentras evidencia de que el puesto es muy viejo, clasifícalo como STALE y archívalo.
    Si no hay nada obvio, asume ACTIVE o BORDERLINE según el contexto.
    """

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        tools=[record_tool],
        tool_choice={"type": "tool", "name": "record_classification"},
        system="Eres un experto en HR Tech y parsing de vacantes. Tu objetivo es detectar vacantes fantasma o expiradas basándote en el texto.",
        messages=[{"role": "user", "content": prompt_content}]
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_classification":
            try:
                result = LLMFreshnessOutput(**block.input)
                print(f"[LLM_DECISION] '{posting.title}' → {result.age_classification.value}")
                return result
            except ValidationError as e:
                print(
                    f"[PYDANTIC_FALLBACK] '{posting.title}' — LLM devolvió esquema inválido, "
                    f"forzando DATE_UNKNOWN.\n"
                    f"  raw_input={block.input}\n"
                    f"  validation_error={e}"
                )
                return LLMFreshnessOutput(
                    age_classification=AgeClassification.DATE_UNKNOWN,
                    stale_signal=StaleSignal.NONE,
                    archive_flag=False
                )
                
    raise ValueError("El LLM no devolvió la estructura requerida.")

# --- 4. PARSER DE FECHAS RELATIVAS ---
_RELATIVE_PATTERNS = [
    (re.compile(r'hace\s+(\d+)\s+hora[s]?', re.IGNORECASE), 'hours'),
    (re.compile(r'hace\s+(\d+)\s+d[ií]a[s]?', re.IGNORECASE), 'days'),
    (re.compile(r'hace\s+(\d+)\s+semana[s]?', re.IGNORECASE), 'weeks'),
    (re.compile(r'hace\s+(\d+)\s+mes(?:es)?', re.IGNORECASE), 'months'),
    (re.compile(r'(\d+)\s+hour[s]?\s+ago', re.IGNORECASE), 'hours'),
    (re.compile(r'(\d+)\s+day[s]?\s+ago', re.IGNORECASE), 'days'),
    (re.compile(r'(\d+)\s+week[s]?\s+ago', re.IGNORECASE), 'weeks'),
    (re.compile(r'(\d+)\s+month[s]?\s+ago', re.IGNORECASE), 'months'),
    (re.compile(r'just\s+now|moments?\s+ago|ahora\s*(?:mismo)?|recién', re.IGNORECASE), 'now'),
]

def _parse_relative_date(text: str) -> Optional[int]:
    """Retorna antigüedad en días si el texto es una fecha relativa, None si no aplica."""
    for pattern, unit in _RELATIVE_PATTERNS:
        match = pattern.search(text)
        if match:
            if unit == 'now':
                return 0
            n = int(match.group(1))
            if unit == 'hours':
                return 0
            if unit == 'days':
                return n
            if unit == 'weeks':
                return n * 7
            if unit == 'months':
                return n * 30
    return None

# --- 5. ORQUESTADOR (HÍBRIDO) ---
def process_postings(raw_postings: List[RawPosting]) -> List[FilteredPosting]:
    today = datetime.now()
    
    # 1. Deduplicar
    unique_postings = deduplicate_jobs(raw_postings)
    
    # 2. Calcular medianas de job_id de forma segura
    valid_job_ids = []
    for p in unique_postings:
        if p.job_id and p.job_id.isdigit():
            valid_job_ids.append(int(p.job_id))
            
    median_job_id = median(valid_job_ids) if valid_job_ids else None
    
    filtered_results = []
    
    for posting in unique_postings:
        try:
            classification_val = None
            stale_signal_val = None
            
            # --- FASE A: Evaluación Determinista ---
            if posting.posted_date:
                try:
                    posted_dt = datetime.fromisoformat(posting.posted_date.replace("Z", "+00:00"))
                    # Descartamos información de timezone para comparación simple si es necesario
                    age = today.date() - posted_dt.date()
                    
                    if age.days < 90:
                        classification_val = AgeClassification.ACTIVE
                    elif age.days < 120:
                        classification_val = AgeClassification.BORDERLINE
                    else:
                        classification_val = AgeClassification.STALE
                    stale_signal_val = StaleSignal.DATE
                    
                except ValueError:
                    relative_days = _parse_relative_date(posting.posted_date)
                    if relative_days is not None:
                        print(f"  [RELATIVE_DATE] '{posting.title}' → '{posting.posted_date}' = {relative_days}d")
                        if relative_days < 90:
                            classification_val = AgeClassification.ACTIVE
                        elif relative_days < 120:
                            classification_val = AgeClassification.BORDERLINE
                        else:
                            classification_val = AgeClassification.STALE
                        stale_signal_val = StaleSignal.DATE
            
            elif posting.job_id and posting.job_id.isdigit() and median_job_id:
                if int(posting.job_id) < median_job_id * 0.85:
                    classification_val = AgeClassification.STALE
                    stale_signal_val = StaleSignal.JOB_ID_SEQUENCE
            
            # --- FASE B: Evaluación Estocástica (Fallback) ---
            # Si las matemáticas no pudieron resolverlo (falta de fecha y job_id no concluyente)
            if classification_val is None:
                llm_decision = evaluate_job_freshness_with_llm(posting)
                classification_val = llm_decision.age_classification
                stale_signal_val = llm_decision.stale_signal
            
            # --- FASE C: Ensamblaje Estricto Pydantic ---
            filtered_posting = FilteredPosting(
                posting=posting,
                age_classification=classification_val,
                stale_signal=stale_signal_val,
                archive_flag=(classification_val == AgeClassification.STALE)
            )
            filtered_results.append(filtered_posting)
            
        except ValidationError as e:
            # Protegemos la frontera. Si un posting es corrompido, lo logueamos y omitimos.
            print(f"Saltando posting inválido debido a error de validación: {e}")
            continue

    return filtered_results

if __name__ == "__main__":
    try:
        with open("data/akamai_postings_raw.json", "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            
            # Extracción adaptativa: si es un dict, buscamos la lista en las llaves probables
            if isinstance(raw_data, dict):
                # Extraemos la lista bajo la llave 'postings', 'jobs', o 'sources'
                postings_list = raw_data.get("postings", raw_data.get("jobs", raw_data.get("sources", [])))
            else:
                postings_list = raw_data

            # Deserialización Pydantic
            raw_postings = [RawPosting.model_validate(p) for p in postings_list]
            
            print("Iniciando Agente 3: Filtro y Clasificación...")
            final_data = process_postings(raw_postings)
            
            output_file = "data/akamai_postings_filtered.json"
            
            # Serialización Pydantic
            with open(output_file, "w", encoding="utf-8") as out_f:
                # Mantenemos la estructura envolvente para consistencia
                final_output = {
                    "company": raw_data.get("company", "Unknown") if isinstance(raw_data, dict) else "Unknown",
                    "postings": [fp.model_dump(mode="json") for fp in final_data]
                }
                json.dump(final_output, out_f, indent=4)
                
            print(f"✅ Agente 3 completado. {len(final_data)} vacantes curadas guardadas en {output_file}")
            
    except FileNotFoundError:
        print("Error: No se encontró 'data/akamai_postings_raw.json'. Ejecuta el Agente 2 primero.")