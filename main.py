import os
import json
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, ValidationError

# Importamos los modelos
from models import SourceURL, RawPosting, FilteredPosting, AgeClassification

# Importamos los agentes
from agent_1 import agent_1_discover
# Ajusta este import según cómo llamaste a la función principal en tu agent_2.py
from agent_2 import run_scraper 
from agent_3 import process_postings

# --- 1. CONTRATO DE ESTADO DEL PIPELINE ---
class OSINTPipelineState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    company_name: str
    discovered_urls: List[SourceURL] = []
    raw_postings: List[RawPosting] = []
    filtered_postings: List[FilteredPosting] = []
    
    # Metadatos de ejecución
    status: str = "INITIALIZED"
    error_log: Optional[str] = None

# --- 2. MOTOR DE ORQUESTACIÓN ---
def run_osint_pipeline(company_name: str) -> OSINTPipelineState:
    print(f"🚀 Iniciando Pipeline OSINT para: {company_name}")
    state = OSINTPipelineState(company_name=company_name)
    
    try:
        # ---------------------------------------------------------
        # FASE 1: Descubrimiento de URLs (Agente 1)
        # ---------------------------------------------------------
        print("\n--- FASE 1: Agente de Descubrimiento ---")
        state.discovered_urls = agent_1_discover(company_name)
        print(f"✅ Encontradas {len(state.discovered_urls)} fuentes potenciales.")

        # ---------------------------------------------------------
        # FASE 2: Scraping y Extracción (Agente 2 - Firecrawl)
        # ---------------------------------------------------------
        print("\n--- FASE 2: Agente Scraper (Firecrawl) ---")
        # Filtramos solo las URLs que están marcadas como FOUND
        valid_urls = [url for url in state.discovered_urls if url.status == "found"]
        
        # Asumimos que run_scraper toma la lista de SourceURL y devuelve List[RawPosting]
        # o un diccionario que convertimos a objetos Pydantic.
        raw_data_output = run_scraper(valid_urls) 
        
        # Validación estricta en la frontera del Agente 2
        if isinstance(raw_data_output, dict) and "postings" in raw_data_output:
            state.raw_postings = [RawPosting.model_validate(p) for p in raw_data_output["postings"]]
        else:
            state.raw_postings = [RawPosting.model_validate(p) for p in raw_data_output]
            
        print(f"✅ Extraídas {len(state.raw_postings)} vacantes crudas.")

        # ---------------------------------------------------------
        # FASE 3: Filtro y Clasificación (Agente 3)
        # ---------------------------------------------------------
        print("\n--- FASE 3: Agente de Clasificación (Híbrido) ---")
        state.filtered_postings = process_postings(state.raw_postings)
        print(f"✅ Curación finalizada. {len(state.filtered_postings)} vacantes procesadas.")

        state.status = "COMPLETED"

    except ValidationError as e:
        state.status = "FAILED_VALIDATION"
        state.error_log = f"Error de contrato Pydantic entre agentes: {str(e)}"
        print(f"\n❌ Pipeline abortado por violación de contrato: {e}")
        
    except Exception as e:
        state.status = "FAILED_EXECUTION"
        state.error_log = f"Error crítico: {str(e)}"
        print(f"\n❌ Pipeline abortado por error de ejecución: {e}")

    finally:
        # ---------------------------------------------------------
        # FASE 4: Persistencia del Estado (Guardado)
        # ---------------------------------------------------------
        save_pipeline_state(state)
        
    return state

# --- 3. PERSISTENCIA ---
def save_pipeline_state(state: OSINTPipelineState):
    os.makedirs("data", exist_ok=True)
    filename = f"data/{state.company_name.lower()}_pipeline_run.json"
    
    with open(filename, "w", encoding="utf-8") as f:
        # Volcamos todo el estado del pipeline en un solo JSON estructurado
        f.write(state.model_dump_json(indent=4))
        
    print(f"\n💾 Estado del pipeline guardado en: {filename}")
    print(f"Status final: {state.status}")


if __name__ == "__main__":
    target = "Akamai"
    
    # Ejecutamos el pipeline y obtenemos el estado final
    final_state = run_osint_pipeline(target)
    
    # --- CHECKPOINT 1 (CP1) PREVIEW ---
    if final_state.status == "COMPLETED" and final_state.filtered_postings:
        print("\n📊 --- RESUMEN DE CLASIFICACIÓN (CP1 PREVIEW) ---")
        
        # Filtramos y contamos usando list comprehensions para mayor claridad
        active = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.ACTIVE]
        borderline = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.BORDERLINE]
        stale = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.STALE]
        date_unknown = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.DATE_UNKNOWN]
        
        print(f"🟢 ACTIVE:     {len(active)}")
        print(f"🟡 BORDERLINE: {len(borderline)}")
        print(f"🔴 STALE:      {len(stale)} (Archivadas / Basura)")
        print(f"⚪ DATE_UNKNOWN: {len(date_unknown)} (Requiere revisión CP1 o de un analista)")
        
        print("\nDetalle de DATE_UNKNOWN:")
        if not date_unknown:
            print("  └ Ninguna. Claude logró clasificar todo.")
        else:
            for job in date_unknown:
                # Mostramos un pequeño log para saber cuáles fallaron la clasificación
                print(f"  └ [Job ID: {job.posting.job_id or 'N/A'}] {job.posting.title[:40]}... (Fuente: {job.posting.source_type.value})")
                
    elif final_state.status != "COMPLETED":
        print(f"\n⚠️ El pipeline no completó satisfactoriamente. Estado final: {final_state.status}")