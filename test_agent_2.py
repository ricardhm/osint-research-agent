import json
import pytest
from pydantic import ValidationError
from unittest.mock import patch, AsyncMock, MagicMock

# Importamos nuestros contratos y funciones del agente
from models import RawPosting, SourceType
from agents.agent_2_posting_fetch import extract_postings_from_text, scrape_with_firecrawl, scrape_with_playwright

# --- FIXTURES ---

@pytest.fixture
def raw_postings_data():
    """Fixture que carga el output real generado por el Agente 2"""
    try:
        with open("data/akamai_postings_raw.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pytest.skip("El archivo de datos akamai_postings_raw.json no existe. Ejecuta agent_2.py primero.")

# --- FASE 1: VALIDACIÓN ESTRUCTURAL Y DE DATOS (Integración) ---

def test_raw_postings_schema_compliance(raw_postings_data):
    """
    Verifica que TODOS los registros en el JSON cumplen el contrato de Pydantic
    y que los tipos obligatorios están presentes.
    """
    postings = raw_postings_data.get("postings", [])
    assert len(postings) > 0, "El JSON no contiene vacantes."

    for item in postings:
        try:
            # Pydantic V2 validará HttpUrl, tipos y constraints al instanciar
            posting = RawPosting(**item)
            
            # Validaciones de calidad estocástica adicionales
            assert len(posting.description_snippet) > 10, "El snippet es demasiado corto para ser útil."
            assert posting.source_type in [e for e in SourceType], "SourceType inválido detectado."
            
        except ValidationError as e:
            pytest.fail(f"Fallo de validación Pydantic en el registro {item.get('title')}: {e}")

# --- FASE 2: PRUEBAS DE RESILIENCIA (Mocks de Fallos) ---

def test_extract_postings_empty_content():
    """Valida que la frontera estocástica maneja textos vacíos deterministamente sin llamar a la API."""
    result = extract_postings_from_text("", "https://fake.url", SourceType.CAREERS_PAGE)
    assert result == [], "Debe retornar lista vacía si no hay contenido."

@patch("agent_2.client.messages.create")
def test_extract_postings_llm_validation_error(mock_anthropic_create):
    """
    Simula que el LLM alucina un tipo de dato incorrecto (ej. URL malformada)
    para asegurar que Pydantic captura el ValidationError y el pipeline sobrevive.
    """
    # Creamos un bloque de respuesta mockeado simulando un Tool Use fallido
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "record_postings"
    mock_block.input = {
        "postings": [
            {
                "title": "Data Engineer",
                "location": "Costa Rica",
                "url": "esto-no-es-una-url", # Esto causará un ValidationError en Pydantic
                "description_snippet": "Valid snippet",
                "source_type": "careers_page"
            }
        ]
    }
    
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_anthropic_create.return_value = mock_response

    # Ejecutamos la función
    result = extract_postings_from_text("Dummy text", "https://akamai.com", SourceType.CAREERS_PAGE)
    
    # El agente debe atrapar el ValidationError de Pydantic y devolver una lista vacía, no crashear
    assert result == [], "El agente debió atrapar el ValidationError y retornar una lista vacía."

@patch("agent_2.FirecrawlApp")
def test_scrape_with_firecrawl_api_failure(MockFirecrawlApp):
    """Simula una caída de la API de Firecrawl (ej. timeout o 500)"""
    # Configuramos el mock para que lance una excepción
    mock_app_instance = MockFirecrawlApp.return_value
    mock_app_instance.scrape_url.side_effect = Exception("API Timeout")

    result = scrape_with_firecrawl("https://akamai.com/careers", SourceType.CAREERS_PAGE)
    
    # Debe manejar la excepción suavemente
    assert result == [], "El fallback de error en Firecrawl falló."

@pytest.mark.asyncio
@patch("agent_2.async_playwright")
async def test_scrape_with_playwright_timeout(mock_async_playwright):
    """Simula un timeout del navegador en Playwright para la carga del DOM"""
    # Configuramos una cadena de mocks asíncronos que eventualmente lance error
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_context
    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = AsyncMock()
    mock_browser.new_context.return_value.new_page.return_value.goto.side_effect = Exception("DOM Timeout")
    
    mock_context.chromium.launch.return_value = mock_browser

    result = await scrape_with_playwright("https://linkedin.com/jobs", SourceType.LINKEDIN)
    
    assert result == [], "Playwright no manejó correctamente el timeout asíncrono."