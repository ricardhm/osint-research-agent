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
        "description": "Registra las URLs de careers_page y bebee.",
        "input_schema": AI_AgentOutput.model_json_schema()
    }

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        tools=[
            {"type": "web_search_20250305", "name": "web_search"},
            record_tool
        ],
        tool_choice={"type": "tool", "name": "record_urls"}, 
        system="""Eres un investigador OSINT experto en búsquedas avanzadas.
        
        REGLAS:
        1. careers_page: Encuentra el portal oficial de vacantes real (ej. jobs.empresa.com). NO asumas "careers.empresa.com". Si no lo hallas con certeza, status: 'not_found'.
        2. bebee: Haz una búsqueda estricta. Busca el perfil de empresa. La URL SIEMPRE tiene el formato 'https://www.bebee.com/company/nombre-empresa'. Si no lo encuentras, status: 'not_found'.
        """,
        messages=[{
            "role": "user",
            "content": f"""Encuentra careers_page y el perfil de bebee para: {company_name}.
            Tip para beBee: Usa la herramienta de búsqueda con 'site:bebee.com/company {company_name}' para encontrar la URL exacta."""
        }]
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_urls":
            validated_data = AI_AgentOutput(**block.input)
            return validated_data.sources

    raise ValueError("El agente no devolvió la estructura.")

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