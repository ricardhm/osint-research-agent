import argparse
import os
import json
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, ValidationError

from models import (
    SourceURL, RawPosting, FilteredPosting, AgeClassification,
    CRCultureIntelOutput, InsideScoopOutput,
)

from agents.agent_1_url_discovery import agent_1_discover
from agents.agent_2_posting_fetch import run_scraper
from agents.agent_3_dedup_filter import process_postings
from agents.agent_4_culture_intel import run_agent_4
from agents.agent_5_signals import run_agent_5


# --- 1. CONTRATO DE ESTADO DEL PIPELINE ---

class OSINTPipelineState(BaseModel):
    model_config = ConfigDict(extra='forbid')

    company_name:       str
    discovered_urls:    List[SourceURL]       = []
    raw_postings:       List[RawPosting]      = []
    filtered_postings:  List[FilteredPosting] = []
    culture_intel:      Optional[CRCultureIntelOutput] = None
    inside_scoop:       Optional[InsideScoopOutput]    = None

    status:    str           = "INITIALIZED"
    error_log: Optional[str] = None


# --- 2. HELPERS ---

def _url_for(discovered_urls: List[SourceURL], source_type: str) -> Optional[str]:
    for src in discovered_urls:
        if src.source_type.value == source_type:
            return str(src.url)
    return None


# --- 3. MOTOR DE ORQUESTACIÓN ---

def run_osint_pipeline(company_name: str) -> OSINTPipelineState:
    print(f"🚀 Iniciando Pipeline OSINT para: {company_name}")
    state = OSINTPipelineState(company_name=company_name)

    try:
        # ── FASE 1: Descubrimiento de URLs (Agent 1) ──────────────────────────
        print("\n--- FASE 1: Agente de Descubrimiento ---")
        state.discovered_urls = agent_1_discover(company_name)
        print(f"✅ Encontradas {len(state.discovered_urls)} fuentes potenciales.")

        # ── FASE 2: Scraping y Extracción (Agent 2) ───────────────────────────
        print("\n--- FASE 2: Agente Scraper ---")
        valid_urls = [url for url in state.discovered_urls if url.status == "found"]
        raw_data_output = run_scraper(valid_urls)

        if isinstance(raw_data_output, dict) and "postings" in raw_data_output:
            state.raw_postings = [RawPosting.model_validate(p) for p in raw_data_output["postings"]]
        else:
            state.raw_postings = [RawPosting.model_validate(p) for p in raw_data_output]

        print(f"✅ Extraídas {len(state.raw_postings)} vacantes crudas.")

        # ── FASE 3: Filtro y Clasificación (Agent 3) ──────────────────────────
        print("\n--- FASE 3: Agente de Clasificación ---")
        state.filtered_postings = process_postings(state.raw_postings)
        print(f"✅ Curación finalizada. {len(state.filtered_postings)} vacantes procesadas.")

        # ── FASE 4: CR Culture Intel (Agent 4) ────────────────────────────────
        print("\n--- FASE 4: Agente CR Culture Intel ---")
        glassdoor_url = _url_for(state.discovered_urls, "glassdoor")
        indeed_cr_url = _url_for(state.discovered_urls, "indeed_cr")
        state.culture_intel = run_agent_4(
            company_name=company_name,
            glassdoor_url=glassdoor_url,
            indeed_cr_url=indeed_cr_url,
        )
        print(
            f"✅ Culture intel completado. "
            f"source_quality={state.culture_intel.source_quality.value} "
            f"flags={state.culture_intel.flags}"
        )

        # ── FASE 5: Inside Scoop — Signal Extraction (Agent 5) ────────────────
        print("\n--- FASE 5: Agente Inside Scoop ---")
        state.inside_scoop = run_agent_5(
            filtered_postings=state.filtered_postings,
            culture_intel=state.culture_intel,
            company_name=company_name,
        )
        print(
            f"✅ Inside Scoop completado. "
            f"org_focus={state.inside_scoop.org_focus.value} "
            f"hiring_velocity={state.inside_scoop.hiring_velocity.value}"
        )

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
        save_pipeline_state(state)

    return state


# --- 4. PERSISTENCIA ---

def save_pipeline_state(state: OSINTPipelineState):
    os.makedirs("data", exist_ok=True)
    filename = f"data/{state.company_name.lower()}_pipeline_run.json"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=4))
    print(f"\n💾 Estado del pipeline guardado en: {filename}")
    print(f"Status final: {state.status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inside Scoop OSINT Pipeline")
    parser.add_argument("--company", required=True, help="Company name to analyze")
    parser.add_argument("--location", default="Costa Rica", help="Location filter (default: Costa Rica)")
    args = parser.parse_args()

    target = args.company
    final_state = run_osint_pipeline(target)

    if final_state.status == "COMPLETED":

        # ── CP1: Clasificación de postings ────────────────────────────────────
        print("\n📊 --- RESUMEN DE CLASIFICACIÓN (CP1) ---")
        active       = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.ACTIVE]
        borderline   = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.BORDERLINE]
        stale        = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.STALE]
        date_unknown = [p for p in final_state.filtered_postings if p.age_classification == AgeClassification.DATE_UNKNOWN]

        print(f"🟢 ACTIVE:       {len(active)}")
        print(f"🟡 BORDERLINE:   {len(borderline)}")
        print(f"🔴 STALE:        {len(stale)}")
        print(f"⚪ DATE_UNKNOWN: {len(date_unknown)}")

        if date_unknown:
            print("\nDetalle DATE_UNKNOWN:")
            for job in date_unknown:
                print(f"  └ [{job.posting.source_type.value}] {job.posting.title[:50]}")

        # ── CP0: Culture Intel ────────────────────────────────────────────────
        if final_state.culture_intel:
            ci = final_state.culture_intel
            ss = ci.sentiment_signals
            print("\n🌐 --- CULTURE INTEL (CP0) ---")
            print(f"   source_quality={ci.source_quality.value}  cr_reviews={ci.cr_review_count}  rating={ci.overall_cr_rating}")
            print(f"   management={ss.management_quality.value}  comp={ss.comp_satisfaction.value}  wlb={ss.wlb.value}  growth={ss.growth_ceiling.value}")
            print(f"   layoffs={ss.layoff_mentions}  recency={ss.layoff_recency.value}")
            if ci.flags:
                print(f"   flags={ci.flags}")

        # ── Inside Scoop summary ──────────────────────────────────────────────
        if final_state.inside_scoop:
            sc = final_state.inside_scoop
            print("\n🔍 --- INSIDE SCOOP (Agent 5) ---")
            print(f"   org_focus={sc.org_focus.value}  career_ceiling={sc.career_ceiling.value}")
            print(f"   hiring_velocity={sc.hiring_velocity.value}  pay_transparency={sc.pay_transparency_signal.value}")
            print(f"   growth_cues={len(sc.growth_cues)}  ambiguous={len(sc.ambiguous_cues)}  stability={len(sc.stability_cues)}  red_flags={len(sc.red_flags)}")

            high_flags = [f for f in sc.red_flags if f.confidence.value == "high"]
            if high_flags:
                print("\n   🚨 High-confidence red flags:")
                for flag in high_flags:
                    print(f"      · {flag.signal}")

            if sc.red_flags_note:
                print(f"\n   📝 {sc.red_flags_note}")

    elif final_state.status != "COMPLETED":
        print(f"\n⚠️ Pipeline no completó satisfactoriamente. Status: {final_state.status}")
