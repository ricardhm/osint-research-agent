import json
import os
import time
from typing import Optional

import anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

from agents.agent4_prompt import AGENT4_SYSTEM_PROMPT, build_agent4_user_prompt
from models import CRCultureIntelOutput

load_dotenv()

SYSTEM_PROMPT = AGENT4_SYSTEM_PROMPT


def _create_with_retry(client: anthropic.Anthropic, **kwargs) -> anthropic.types.Message:
    """Wrapper around client.messages.create with exponential backoff on RateLimitError."""
    for attempt in range(3):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            if attempt < 2:
                wait = 60 * (attempt + 1)
                print(f"  [agent_4] rate limit — waiting {wait}s before retry {attempt + 2}/3...")
                time.sleep(wait)
            else:
                raise


def run_agent_4(
    company_name: str,
    glassdoor_url: Optional[str] = None,
    indeed_cr_url: Optional[str] = None,
    company_domain: Optional[str] = None,
) -> CRCultureIntelOutput:
    client = anthropic.Anthropic()

    record_tool = {
        "name": "record_culture_intel",
        "description": "Registra los signals de cultura laboral CR-específicos extraídos de la investigación.",
        "input_schema": CRCultureIntelOutput.model_json_schema(),
    }

    user_content = build_agent4_user_prompt(
        company_name, glassdoor_url, indeed_cr_url, company_domain
    )

    # Step 1: Research — model runs source waterfall freely via web_search
    print(f"  [agent_4] step1 — researching CR culture intel for '{company_name}'...")
    search_response = _create_with_retry(
        client,
        model="claude-sonnet-4-6",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    print(f"  [agent_4] step1 stop_reason={search_response.stop_reason}")

    research_findings = "\n".join(
        block.text
        for block in search_response.content
        if hasattr(block, "text") and block.text
    )

    # Step 2: Record — force structured output grounded in research findings
    print(f"  [agent_4] step2 — recording structured culture intel...")
    step2_messages = [
        {"role": "user", "content": user_content},
        {
            "role": "assistant",
            "content": research_findings
            or "No se encontró información CR-específica en ninguna fuente del waterfall.",
        },
        {
            "role": "user",
            "content": "Basándote en tu investigación, registra ahora los signals con record_culture_intel.",
        },
    ]
    record_response = _create_with_retry(
        client,
        model="claude-sonnet-4-6",
        max_tokens=2000,
        tools=[record_tool],
        tool_choice={"type": "tool", "name": "record_culture_intel"},
        system=SYSTEM_PROMPT,
        messages=step2_messages,
    )

    for block in record_response.content:
        if block.type == "tool_use" and block.name == "record_culture_intel":
            try:
                result = CRCultureIntelOutput(**block.input)
                print(
                    f"  [agent_4] source_quality={result.source_quality.value} "
                    f"flags={result.flags} cr_reviews={result.cr_review_count}"
                )
                return result
            except ValidationError as e:
                print(
                    f"[PYDANTIC_FALLBACK] agent_4 '{company_name}' — "
                    f"LLM devolvió esquema inválido.\n"
                    f"  raw_input={block.input}\n"
                    f"  validation_error={e}"
                )
                raise

    raise ValueError(
        f"Agent 4 no devolvió record_culture_intel para '{company_name}'."
    )


if __name__ == "__main__":
    import sys

    target_company = sys.argv[1] if len(sys.argv) > 1 else "Lumenalta"

    # Load agent_1 output to get Glassdoor / Indeed CR URLs if available
    urls_file = f"data/{target_company.lower()}_urls.json"
    glassdoor_url = None
    indeed_cr_url = None

    if os.path.exists(urls_file):
        with open(urls_file, "r", encoding="utf-8") as f:
            url_data = json.load(f)
        for src in url_data.get("sources", []):
            if src.get("source_type") == "glassdoor" and src.get("status") in ("found", "requires_login"):
                glassdoor_url = src.get("url")
            elif src.get("source_type") == "indeed_cr" and src.get("status") == "found":
                indeed_cr_url = src.get("url")
        print(f"Loaded URLs from {urls_file}")
    else:
        print(f"No URL file at {urls_file} — running without pre-discovered URLs.")

    print(f"\n🤖 Iniciando Agente 4: CR Culture Intel para '{target_company}'...")
    result = run_agent_4(
        company_name=target_company,
        glassdoor_url=glassdoor_url,
        indeed_cr_url=indeed_cr_url,
    )

    os.makedirs("data", exist_ok=True)
    output_file = f"data/{target_company.lower()}_culture_intel.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {"company": target_company, "culture_intel": result.model_dump(mode="json")},
            f,
            indent=4,
        )

    print(f"\n✅ Agente 4 completado. Resultados guardados en {output_file}")
