import os
import json
import urllib.parse
import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List
from models import SourceURL, SourceType, SourceStatus

load_dotenv()

# 1. GENERACIÓN DETERMINISTA (Para URLs predecibles)
def get_deterministic_urls(company_name: str) -> List[SourceURL]:
    encoded_name = urllib.parse.quote(company_name)
    return [
        SourceURL(
            source_type=SourceType.LINKEDIN,
            url=f"https://www.linkedin.com/jobs/search/?keywords={encoded_name}&location=Costa%20Rica",
            status=SourceStatus.FOUND
        ),
        SourceURL(
            source_type=SourceType.INDEED_CR,
            url=f"https://cr.indeed.com/jobs?q={encoded_name}",
            status=SourceStatus.FOUND
        ),
        SourceURL(
            source_type=SourceType.BUILTIN,
            url=f"https://builtin.com/jobs?search={encoded_name}&country=CRI&allLocations=true",
            status=SourceStatus.FOUND
        ),
        SourceURL(
            source_type=SourceType.GLASSDOOR,
            url=f"https://www.google.com/search?q=site:glassdoor.com+%22{encoded_name}%22+jobs+Costa+Rica",
            status=SourceStatus.REQUIRES_LOGIN
        )
    ]

# 2. GENERACIÓN ESTOCÁSTICA (Solo para lo que requiere búsqueda real)
class AI_AgentOutput(BaseModel):
    sources: List[SourceURL]

def get_ai_urls(company_name: str) -> List[SourceURL]:
    client = anthropic.Anthropic()

    record_tool = {
        "name": "record_urls",
        "description": "Registra las URLs de careers_page y bebee encontradas en la investigación.",
        "input_schema": AI_AgentOutput.model_json_schema()
    }

    system_prompt = """Eres un investigador OSINT experto en búsquedas avanzadas.

        REGLAS:
        1. careers_page: Encuentra el portal oficial de vacantes real (ej. jobs.empresa.com). NO asumas "careers.empresa.com". Si no lo hallas con certeza, status: 'not_found'.
        2. bebee: Haz una búsqueda estricta. Busca el perfil de empresa. La URL SIEMPRE tiene el formato 'https://www.bebee.com/company/nombre-empresa'. Si no lo encuentras, status: 'not_found'.
        """

    user_content = (
        f"Investiga y encuentra careers_page y el perfil de bebee para: {company_name}. "
        f"Tip para beBee: Busca con 'site:bebee.com/company {company_name}'."
    )

    # Step 1: Search — model searches freely, devuelve texto con hallazgos
    search_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}]
    )
    print(f"  [agent_1] step1 stop_reason={search_response.stop_reason}")

    research_findings = "\n".join(
        block.text for block in search_response.content
        if hasattr(block, "text") and block.text
    )

    # Step 2: Record — fuerza record_urls con el contexto de búsqueda como grounding
    record_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        tools=[record_tool],
        tool_choice={"type": "tool", "name": "record_urls"},
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": research_findings or "No se encontraron resultados definitivos."},
            {"role": "user", "content": "Basándote en tu investigación, registra ahora las URLs con record_urls."}
        ]
    )

    for block in record_response.content:
        if block.type == "tool_use" and block.name == "record_urls":
            return AI_AgentOutput(**block.input).sources

    raise ValueError("El agente no devolvió la estructura esperada de record_urls.")

# 3. ORQUESTACIÓN
def agent_1_discover(company_name: str) -> List[SourceURL]:
    print(f"Generando URLs deterministas para: {company_name}...")
    deterministic_urls = get_deterministic_urls(company_name)
    
    print(f"Iniciando Agente OSINT para dominios variables de {company_name}...")
    ai_urls = get_ai_urls(company_name)
    
    # Combinamos ambas listas
    return deterministic_urls + ai_urls

if __name__ == "__main__":
    target_company = "Akamai"
    
    urls_found = agent_1_discover(target_company)
    
    os.makedirs("data", exist_ok=True)
    output_file = "data/akamai_urls.json"
    
    final_output = {
        "company": target_company,
        "sources": [url.model_dump(mode="json") for url in urls_found]
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4)
        
    print(f"✅ Agente 1 completado. Resultados guardados en {output_file}")