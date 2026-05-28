import json
import os
import sys
import time
from collections import Counter
from typing import List, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

from models import (
    AgeClassification, CRCultureIntelOutput, FilteredPosting,
    InsideScoopOutput, GrowthCue, AmbiguousCue, StabilityCue, RedFlag,
    RoleCluster, OrgFocus, CareerCeiling, PayTransparency, HiringVelocity,
    SenioritySkew, SignalConfidence,
)

load_dotenv()

SYSTEM_PROMPT = """You are a tech labor-market analyst specializing in Costa Rica's tech sector.
Your task: given a set of filtered job postings and CR-specific culture intel, extract
structured intelligence signals using the Inside Scoop for Job Seekers framework.

════════════════════════════
SIGNAL FRAMEWORK — 4 BUCKETS
════════════════════════════

GROWTH_CUES — evidence of genuine headcount expansion:
  Qualifies as a growth_cue only if 2 of 3 are present:
    (a) role type is new to the observed roster
    (b) multiple seniority levels open in the same function
    (c) a manager or director role posted in that function
  If only 1 of 3 → route to AMBIGUOUS_CUES with ambiguity_reason="possible replacement hiring"

AMBIGUOUS_CUES — signals that could be growth OR replacement:
  - Single opening in an established function with no new-type signal
  - Recurring postings for the same title
  - Anything that passes the replacement-hiring threshold test (above)

STABILITY_CUES — evidence of org maturity and health:
  - Staff/principal/senior roles across multiple departments
  - Culture intel: positive WLB, tenure signals, stable ratings
  - Sustained multi-source posting activity over time

RED_FLAGS — evidence of risk or dysfunction:
  - STALE_DOMINANT: >60% of postings are STALE or DATE_UNKNOWN
  - Layoff mentions in culture intel (recent_12mo → high confidence)
  - Sudden role concentration suggesting restructuring
  - Culture intel: negative management or comp signals

══════════════════════════════
HARD CONSTRAINTS — ALL 8 APPLY
══════════════════════════════

C1. NEVER infer signals from brand reputation.
    Only use evidence from the provided postings and culture intel.
    Prestige, company size, or industry standing are not signals.

C2. Adversarial test (apply always):
    If all or most postings are Sales/CS/Account Management,
    org_focus MUST be "sales_hub" — never "engineering_hub".
    Company prestige does not override posting evidence.

C3. Every signal entry MUST cite a specific posting title + URL in evidence.
    Generic evidence ("multiple engineering roles") is rejected.
    Format: "«Title» — <url>"

C4. Replacement hiring rule (see GROWTH_CUES above):
    Do not put a pattern into growth_cues unless it meets 2-of-3.
    When in doubt, use ambiguous_cues.

C5. If red_flags is empty after your analysis:
    Set red_flags_note = "No red flags detected in this pass."
    Never omit the red_flags_note key regardless of whether flags exist.

C6. org_focus_justification = exactly 1 sentence citing posting evidence.
    Example: "9 of 12 active postings are in SWE/SRE/EM functions."

C7. The schema uses extra=forbid. Return only the keys defined in the tool.
    Do not add any extra fields.

C8. STALE and DATE_UNKNOWN postings are context only.
    They may not be the sole driver of any growth_cue, ambiguous_cue, or stability_cue.
    They may contribute to red_flags (STALE_DOMINANT) and org_focus supporting data only."""

CHUNK_SIZE = 15
_STALE_TAGS = {AgeClassification.STALE, AgeClassification.DATE_UNKNOWN}


# ── FORMATTERS ────────────────────────────────────────────────────────────────

def _format_postings(postings: List[FilteredPosting]) -> str:
    lines = []
    for fp in postings:
        p = fp.posting
        lines.append(
            f"[{fp.age_classification.value}] "
            f"title=\"{p.title}\" "
            f"dept={p.department or 'unknown'} "
            f"loc={p.location} "
            f"source={p.source_type.value} "
            f"url={p.url}"
        )
    return "\n".join(lines)


def _format_culture(culture: CRCultureIntelOutput) -> str:
    ss = culture.sentiment_signals
    quotes = "; ".join(f"\"{q.paraphrase}\"" for q in culture.representative_quotes[:3])
    return (
        f"source_quality={culture.source_quality.value} "
        f"cr_reviews={culture.cr_review_count} rating={culture.overall_cr_rating}\n"
        f"management={ss.management_quality.value} comp={ss.comp_satisfaction.value} "
        f"growth={ss.growth_ceiling.value} wlb={ss.wlb.value}\n"
        f"layoffs={ss.layoff_mentions} recency={ss.layoff_recency.value}\n"
        f"delta={culture.global_vs_cr_delta.direction.value} ({culture.global_vs_cr_delta.note})\n"
        f"flags={culture.flags or 'none'}\n"
        f"quotes: {quotes}"
    )


# ── LLM CALL ──────────────────────────────────────────────────────────────────

def _call_llm(
    client: anthropic.Anthropic,
    postings_text: str,
    culture_text: str,
    company_name: str,
    chunk_label: str,
) -> InsideScoopOutput:
    record_tool = {
        "name": "record_signals",
        "description": "Registra los signals estructurados del Inside Scoop analysis.",
        "input_schema": InsideScoopOutput.model_json_schema(),
    }

    user_content = (
        f"COMPANY: {company_name}\n"
        f"CHUNK: {chunk_label}\n\n"
        f"JOB POSTINGS:\n{postings_text}\n\n"
        f"CR CULTURE INTEL:\n{culture_text}\n\n"
        "Apply the Inside Scoop framework. Cite posting title + URL in every evidence field."
    )

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=3000,
                tools=[record_tool],
                tool_choice={"type": "tool", "name": "record_signals"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except anthropic.RateLimitError:
            if attempt < 2:
                wait = 60 * (attempt + 1)
                print(f"  [agent_5] rate limit — waiting {wait}s ({chunk_label})...")
                time.sleep(wait)
            else:
                raise

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_signals":
            try:
                return InsideScoopOutput(**block.input)
            except ValidationError as e:
                print(
                    f"[PYDANTIC_FALLBACK] agent_5 {chunk_label} — "
                    f"LLM devolvió esquema inválido.\n"
                    f"  raw_input={block.input}\n"
                    f"  validation_error={e}"
                )
                raise

    raise ValueError(f"Agent 5 no devolvió record_signals para {chunk_label}.")


# ── MERGE ─────────────────────────────────────────────────────────────────────

def _dedup(items, key="signal"):
    seen, out = set(), []
    for item in items:
        k = getattr(item, key)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


# Topic markers for semantic dedup of red_flags.
# Culture intel signals repeat verbatim across chunks → same topic = duplicate.
_TOPIC_MARKERS: dict[str, set[str]] = {
    "layoff":        {"layoff", "layoffs", "termination", "terminated"},
    "comp":          {"compensation", "salary", "comp", "market", "pay", "raises"},
    "career_growth": {"career", "ceiling", "promotion", "advancement", "mobility"},
    "management":    {"management", "manager", "leadership", "mgmt"},
    "stale_dom":     {"stale_dominant", "stale postings"},
    "sycophancy":    {"sycophancy_risk", "sycophancy_risk_detected"},
}

_CONFIDENCE_RANK = {
    SignalConfidence.HIGH: 2,
    SignalConfidence.MEDIUM: 1,
    SignalConfidence.LOW: 0,
}


def _signal_topic(text: str) -> Optional[str]:
    lower = text.lower()
    for topic, markers in _TOPIC_MARKERS.items():
        if any(m in lower for m in markers):
            return topic
    return None


def _fuzzy_dedup_flags(flags: list) -> list:
    """Collapse red_flags by topic; keep the higher-confidence entry on collision."""
    result: list = []
    seen_topics: dict[str, int] = {}
    for incoming in flags:
        topic = _signal_topic(incoming.signal)
        if topic and topic in seen_topics:
            idx = seen_topics[topic]
            if _CONFIDENCE_RANK.get(incoming.confidence, 0) > _CONFIDENCE_RANK.get(result[idx].confidence, 0):
                result[idx] = incoming
        else:
            if topic:
                seen_topics[topic] = len(result)
            result.append(incoming)
    return result


def _majority_vote(values: list):
    """Most common value. On tie, first-encountered (chunk 0) wins."""
    counts = Counter(values)
    max_count = max(counts.values())
    for v in values:
        if counts[v] == max_count:
            return v


def _merge_chunks(chunks: List[InsideScoopOutput]) -> InsideScoopOutput:
    if len(chunks) == 1:
        return chunks[0]

    growth_cues    = _dedup([c for ch in chunks for c in ch.growth_cues])
    ambiguous_cues = _dedup([c for ch in chunks for c in ch.ambiguous_cues])
    stability_cues = _dedup([c for ch in chunks for c in ch.stability_cues])
    red_flags      = _fuzzy_dedup_flags([c for ch in chunks for c in ch.red_flags])

    # Role clusters: dedup by name, sum posting_count
    cluster_map: dict[str, RoleCluster] = {}
    for ch in chunks:
        for rc in ch.role_clusters:
            if rc.cluster_name in cluster_map:
                existing = cluster_map[rc.cluster_name]
                cluster_map[rc.cluster_name] = RoleCluster(
                    cluster_name=rc.cluster_name,
                    posting_count=existing.posting_count + rc.posting_count,
                    seniority_skew=existing.seniority_skew,
                )
            else:
                cluster_map[rc.cluster_name] = rc

    # Majority vote; chunk 0 wins on tie via first-encountered traversal
    all_org_focus       = [ch.org_focus      for ch in chunks]
    all_career_ceilings = [ch.career_ceiling  for ch in chunks]
    all_velocities      = [ch.hiring_velocity for ch in chunks]

    org_focus_winner = _majority_vote(all_org_focus)
    career_ceiling   = _majority_vote(all_career_ceilings)
    hiring_velocity  = _majority_vote(all_velocities)

    # org_focus_justification from the first chunk that cast the winning vote
    justification = next(
        ch.org_focus_justification for ch in chunks if ch.org_focus == org_focus_winner
    )

    # Pay transparency: presence wins
    pay_vals = [ch.pay_transparency_signal for ch in chunks]
    if PayTransparency.PRESENT in pay_vals:
        pay_sig = PayTransparency.PRESENT
    elif PayTransparency.PARTIAL in pay_vals:
        pay_sig = PayTransparency.PARTIAL
    else:
        pay_sig = PayTransparency.ABSENT

    red_flags_note = (
        "No red flags detected in this pass."
        if not red_flags
        else next((ch.red_flags_note for ch in chunks if ch.red_flags and ch.red_flags_note), None)
    )

    return InsideScoopOutput(
        growth_cues=growth_cues,
        ambiguous_cues=ambiguous_cues,
        stability_cues=stability_cues,
        red_flags=red_flags,
        red_flags_note=red_flags_note,
        org_focus=org_focus_winner,
        org_focus_justification=justification,
        career_ceiling=career_ceiling,
        role_clusters=list(cluster_map.values()),
        pay_transparency_signal=pay_sig,
        hiring_velocity=hiring_velocity,
    )


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_agent_5(
    filtered_postings: List[FilteredPosting],
    culture_intel: CRCultureIntelOutput,
    company_name: str = "Unknown",
    quiet: bool = False,
) -> InsideScoopOutput:
    client = anthropic.Anthropic()

    active   = [fp for fp in filtered_postings if fp.age_classification not in _STALE_TAGS]
    stale    = [fp for fp in filtered_postings if fp.age_classification in _STALE_TAGS]
    culture_text = _format_culture(culture_intel)

    if len(active) <= CHUNK_SIZE:
        all_postings = active + stale
        if not quiet:
            print(f"  [agent_5] single chunk — {len(active)} active/borderline + {len(stale)} stale")
        result = _call_llm(
            client,
            _format_postings(all_postings),
            culture_text,
            company_name,
            "1/1",
        )
        if not quiet:
            print(
                f"  [agent_5] done — growth={len(result.growth_cues)} "
                f"ambiguous={len(result.ambiguous_cues)} "
                f"stability={len(result.stability_cues)} "
                f"red_flags={len(result.red_flags)}"
            )
        return result

    # Chunk active postings; stale goes to chunk 0 only
    chunks = [active[i:i + CHUNK_SIZE] for i in range(0, len(active), CHUNK_SIZE)]
    total  = len(chunks)
    if not quiet:
        print(f"  [agent_5] chunking: {len(active)} active → {total} chunks of ≤{CHUNK_SIZE}, {len(stale)} stale in chunk 1")

    results = []
    for idx, chunk in enumerate(chunks):
        chunk_postings = chunk + (stale if idx == 0 else [])
        label = f"{idx + 1}/{total}"
        if not quiet:
            print(f"  [agent_5] chunk {label} — {len(chunk)} active + {len(stale) if idx == 0 else 0} stale")
        results.append(
            _call_llm(client, _format_postings(chunk_postings), culture_text, company_name, label)
        )

    merged = _merge_chunks(results)
    if not quiet:
        print(
            f"  [agent_5] merged {total} chunks → "
            f"growth={len(merged.growth_cues)} ambiguous={len(merged.ambiguous_cues)} "
            f"stability={len(merged.stability_cues)} red_flags={len(merged.red_flags)}"
        )
    return merged


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent 5: Inside Scoop for Job Seekers")
    parser.add_argument("agent3_output", help="Filtered postings JSON from Agent 3")
    parser.add_argument("agent4_fixture", help="Culture intel JSON from Agent 4")
    parser.add_argument("--output", default=None, help="Output file path (default: data/<company>_inside_scoop.json)")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs")
    args = parser.parse_args()

    with open(args.agent3_output, "r", encoding="utf-8") as f:
        raw3 = json.load(f)
    # Accept both agent_3 standalone output (company/postings)
    # and pipeline run format (company_name/filtered_postings)
    company_name = raw3.get("company") or raw3.get("company_name", "Unknown")
    postings_list = raw3.get("postings") or raw3.get("filtered_postings", [])
    filtered_postings = [FilteredPosting.model_validate(p) for p in postings_list]

    with open(args.agent4_fixture, "r", encoding="utf-8") as f:
        raw4 = json.load(f)
    culture_intel = CRCultureIntelOutput.model_validate(raw4.get("culture_intel", raw4))

    if not args.quiet:
        active_count = sum(1 for fp in filtered_postings if fp.age_classification not in _STALE_TAGS)
        stale_count  = len(filtered_postings) - active_count
        print(f"\n🤖 Iniciando Agente 5: Inside Scoop para '{company_name}'...")
        print(f"   {active_count} active/borderline + {stale_count} stale postings")
        print(f"   culture source_quality={culture_intel.source_quality.value}")

    result = run_agent_5(
        filtered_postings, culture_intel, company_name=company_name, quiet=args.quiet
    )

    output_path = args.output or f"data/{company_name.lower()}_inside_scoop.json"
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {"company": company_name, "inside_scoop": result.model_dump(mode="json")},
            f,
            indent=4,
        )

    if not args.quiet:
        print(f"\n✅ Agente 5 completado. Resultados guardados en {output_path}")
        print(f"   org_focus={result.org_focus.value}  career_ceiling={result.career_ceiling.value}")
        print(f"   hiring_velocity={result.hiring_velocity.value}  pay_transparency={result.pay_transparency_signal.value}")
