import os
import json
import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List
from models import SourceURL

# 0. Carga las variables del archivo .env a la memoria
load_dotenv()

# 1. Definimos un modelo contenedor para que Pydantic genere el esquema de la lista
class AgentOutput(BaseModel):
    sources: List[SourceURL]

def agent_1_discover(company_name: str) -> List[SourceURL]:
    client = anthropic.Anthropic()
    
    # 2. Convertimos tu Pydantic model a un JSON Schema para la API de Anthropic
    record_tool = {
        "name": "record_urls",
        "description": "Registra las URLs encontradas en la estructura de datos requerida.",
        "input_schema": AgentOutput.model_json_schema()
    }

    print(f"Buscando fuentes OSINT para: {company_name}...")
    
    response = client.messages.create(
        model="claude-haiku-4-5-20251001", # String corregido a la versión actual estable
        max_tokens=1000,
        # Inyectamos tu herramienta de búsqueda nativa y nuestra herramienta de formateo
        tools=[
            {"type": "web_search_20250305", "name": "web_search"},
            record_tool
        ],
        # OBLIGAMOS a Claude a usar esta herramienta para emitir su respuesta
        tool_choice={"type": "tool", "name": "record_urls"}, 
        system="""Eres un especialista en OSINT de mercado laboral. 
        Tu único objetivo es encontrar URLs reales y precisas de job postings.
        
        REGLAS ESTRICTAS DE VALIDACIÓN:
        1. CERO ALUCINACIONES: NO asumas subdominios lógicos (ej. careers.empresa.com). Si la búsqueda web no te da la URL exacta y verificable, repórtala como 'not_found'.
        2. FILTROS GEOGRÁFICOS: Para LinkedIn, BuiltIn e Indeed, DEBES construir o encontrar la URL que incluya los parámetros de búsqueda para Costa Rica.
        3. MUROS DE LOGIN: Plataformas como Glassdoor utilizan IDs dinámicos ofuscados. Si encuentras la URL pero requiere autenticación para ver los empleos, usa el status 'requires_login'.""",
        messages=[{
            "role": "user",
            "content": f"""Encuentra URLs de job postings para la empresa: {company_name}
            
            Requisitos por fuente:
            - careers_page: Encuentra el portal oficial de empleo (ej. jobs.empresa.com o empresa.wd1.myworkdayjobs.com).
            - linkedin: URL de búsqueda filtrada por la empresa y ubicación Costa Rica.
            - indeed_cr: URL de búsqueda filtrada por la empresa en cr.indeed.com.
            - glassdoor: URL del perfil de la empresa (usa status requires_login si aplica).
            - builtin: URL filtrada por empresa y país CRI.
            - bebee: URL del perfil de la empresa en CR.
            """
        }]
    )

    # 3. Extraemos y validamos el bloque de respuesta directamente en Pydantic
    for block in response.content:
        if block.type == "tool_use" and block.name == "record_urls":
            # Si Claude alucinó un formato, Pydantic lanzará ValidationError aquí
            validated_data = AgentOutput(**block.input)
            return validated_data.sources

    raise ValueError("El agente no devolvió la estructura de datos esperada.")

if __name__ == "__main__":
    target_company = "Akamai"
    
    # Ejecutamos el agente
    urls_found = agent_1_discover(target_company)
    
    # Preparamos el sistema de archivos
    os.makedirs("data", exist_ok=True)
    output_file = "data/akamai_urls.json"
    
    # Serializamos usando las capacidades nativas de Pydantic para manejar Enums y HttpUrls
    final_output = {
        "company": target_company,
        "sources": [url.model_dump(mode="json") for url in urls_found]
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4)
        
    print(f"✅ Agente 1 completado. Resultados guardados en {output_file}")