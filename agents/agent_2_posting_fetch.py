import os
import json
import asyncio
from typing import List
from dotenv import load_dotenv
import anthropic
from firecrawl import FirecrawlApp
from playwright.async_api import async_playwright
from pydantic import BaseModel, ValidationError

# Importamos los contratos establecidos
from models import SourceURL, SourceType, RawPosting, SourceStatus

load_dotenv()

# Instancia global del cliente LLM
client = anthropic.Anthropic()

# Modelo contenedor para el Tool Use de Anthropic
class LLM_PostingOutput(BaseModel):
    postings: List[RawPosting]

def extract_postings_from_text(content: str, source_url: str, source_type: SourceType) -> List[RawPosting]:
    """
    Frontera estocástica: Delega al LLM la extracción de datos no estructurados a estructurados.
    """
    if not content or len(content.strip()) == 0:
        print(f"⚠️ Contenido vacío recibido de {source_url}. Saltando extracción.")
        return []

    # Recortamos a un límite seguro para evitar desbordar el context window (Haiku aguanta bien, pero es defensivo)
    safe_content = content[:150000]

    # Tool definition usando el schema V2 de Pydantic
    record_tool = {
        "name": "record_postings",
        "description": "Extrae la lista de vacantes de empleo (job postings) del texto proporcionado.",
        "input_schema": LLM_PostingOutput.model_json_schema()
    }

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            tools=[record_tool],
            tool_choice={"type": "tool", "name": "record_postings"},
            system="""Eres un extractor experto de datos de RRHH.
            Tu objetivo es extraer empleos a partir del texto scrapeado de una web.
            Debes inferir el título, departamento, ubicación, fecha (si es visible), job_id, URL de la vacante, y un extracto de la descripción (máximo 250 caracteres).
            IMPORTANTE: Si la vacante no muestra su URL individual, utiliza la URL de la página fuente proporcionada.

            REGLA CRÍTICA para posted_date:
            - Si la fecha está en formato relativo ("2 days ago", "hace 3 días", "3 days ago", "1 week ago"), cópiala EXACTAMENTE como string. NO la conviertas a ISO8601.
            - Solo usa formato ISO8601 si la fecha absoluta está explícitamente visible en el texto.
            - Si no hay fecha visible, usa null.""",
            messages=[{
                "role": "user",
                "content": f"URL Fuente: {source_url}\nTipo de Fuente: {source_type.value}\n\nContenido Scrapeado:\n{safe_content}"
            }]
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "record_postings":
                # Frontera de Validación Estricta
                try:
                    validated_data = LLM_PostingOutput(**block.input)
                    
                    final_postings = []
                    for p in validated_data.postings:
                        # Garantía Determinista: Sobrescribimos el source_type para evitar alucinaciones
                        p.source_type = source_type
                        final_postings.append(p)
                        
                    return final_postings
                
                except ValidationError as ve:
                    print(f"❌ Error de Validación Pydantic en salida del LLM para {source_url}:\n{ve}")
                    return []

        print(f"⚠️ El modelo no utilizó la herramienta de extracción para {source_url}.")
        return []

    except Exception as e:
        print(f"❌ Error en API de Anthropic procesando {source_url}: {e}")
        return []

def scrape_with_firecrawl(url: str, source_type: SourceType) -> List[RawPosting]:
    """Ruta determinista A: API-based scraping para sitios amigables"""
    print(f"🔥 Iniciando Firecrawl para: {url}")
    try:
        app = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))
        
        # Manejo defensivo para diferencias de versión en el SDK de Firecrawl (V1 vs V2)
        try:
            # Intento 1: SDK V1 estándar
            result = app.scrape_url(url, params={"formats": ["markdown"]})
        except TypeError:
            # Intento 2: Fallback para SDK V2
            result = app.scrape_url(url)
        
        # Extracción del markdown soportando respuestas de diccionario (V1) u objetos (V2)
        if isinstance(result, dict):
            markdown_content = result.get('markdown', result.get('content', ''))
        else:
            # Si la V2 devuelve un modelo Pydantic o similar
            markdown_content = getattr(result, 'markdown', getattr(result, 'content', ''))
            
        print(f"✅ Firecrawl extrajo {len(markdown_content) if markdown_content else 0} caracteres. Pasando a IA...")
        
        return extract_postings_from_text(markdown_content, url, source_type)
        
    except Exception as e:
        print(f"❌ Error en Firecrawl para {url}: {e}")
        return []

async def scrape_with_playwright(url: str, source_type: SourceType) -> List[RawPosting]:
    """Ruta determinista B: DOM-based scraping para SPAs y JS-Heavy sites"""
    print(f"🎭 Iniciando Playwright para: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Usamos un User-Agent realista
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Navegamos y esperamos a que el DOM base cargue
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Pequeño buffer determinista para permitir requests asíncronas de la página
            await asyncio.sleep(4) 
            
            # Extraemos text limpio para minimizar tokens y ruido al LLM
            content = await page.evaluate("document.body.innerText")
            await browser.close()
            
            print(f"✅ Playwright extrajo {len(content)} caracteres. Pasando a IA...")
            return extract_postings_from_text(content, url, source_type)
            
    except Exception as e:
        print(f"❌ Error en Playwright para {url}: {e}")
        return []

async def agent_2_orchestrate(input_file: str, output_file: str):
    """Función principal de orquestación del Agente 2"""
    print("\n🤖 Iniciando Agente 2: Web Scraper & Extractor...")
    
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    company = data.get("company", "Unknown")
    sources = [SourceURL(**s) for s in data.get("sources", [])]
    
    all_raw_postings: List[RawPosting] = []
    
    for source in sources:
        # Solo scrapeamos las fuentes que el Agente 1 encontró
        if source.status != SourceStatus.FOUND:
            print(f"⏭️ Saltando {source.source_type.value} - Estado: {source.status.value}")
            continue
            
        url_str = str(source.url)
        
        # Enrutador por tipo de fuente
        if source.source_type in [SourceType.CAREERS_PAGE, SourceType.INDEED_CR, SourceType.BUILTIN, SourceType.BEBEE]:
            postings = scrape_with_firecrawl(url_str, source.source_type)
            all_raw_postings.extend(postings)
            
        elif source.source_type in [SourceType.LINKEDIN, SourceType.GLASSDOOR]:
            postings = await scrape_with_playwright(url_str, source.source_type)
            all_raw_postings.extend(postings)
            
        else:
            print(f"⚠️ SourceType no mapeado en el enrutador: {source.source_type}")

    # Estructuramos y persistimos el output final
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    final_output = {
        "company": company,
        "total_raw_postings": len(all_raw_postings),
        "postings": [p.model_dump(mode="json") for p in all_raw_postings]
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4)
        
    print(f"\n🚀 Agente 2 completado exitosamente.")
    print(f"📊 {len(all_raw_postings)} vacantes en crudo guardadas en {output_file}")

def run_scraper(sources: List[SourceURL]) -> List[RawPosting]:
    """
    Adaptador sincrónico para el Orquestador Maestro (main.py).
    Toma la lista de URLs, maneja el entorno asíncrono y devuelve los objetos crudos.
    """
    async def _process_urls():
        all_raw_postings: List[RawPosting] = []
        
        for source in sources:
            url_str = str(source.url)
            
            # Enrutador por tipo de fuente
            if source.source_type in [SourceType.CAREERS_PAGE, SourceType.INDEED_CR, SourceType.BUILTIN, SourceType.BEBEE]:
                postings = scrape_with_firecrawl(url_str, source.source_type)
                all_raw_postings.extend(postings)
                
            elif source.source_type in [SourceType.LINKEDIN, SourceType.GLASSDOOR]:
                postings = await scrape_with_playwright(url_str, source.source_type)
                all_raw_postings.extend(postings)
                
            else:
                print(f"⚠️ SourceType no mapeado: {source.source_type}")
                
        return all_raw_postings

    # Ejecutamos el loop de eventos asíncrono y devolvemos la lista limpia
    return asyncio.run(_process_urls())

if __name__ == "__main__":
    input_path = "data/akamai_urls.json"
    output_path = "data/akamai_postings_raw.json"
    
    # Dado que utilizamos Playwright, el core debe correr en un Event Loop asíncrono
    asyncio.run(agent_2_orchestrate(input_path, output_path))