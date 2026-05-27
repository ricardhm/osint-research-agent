# AGENT PRODUCT SPECIFICATION
## CR Tech Market OSINT Research Agent ("Inside Scoop Engine")

**Version:** 0.2 — Post-Implementation Revision  
**Author:** [Your Name]  
**Date:** May 2026 — Revised 2026-05-27  
**Status:** v0.2 — Agents 1–3 implemented; post-incident patch applied 2026-05-27 (see `POSTMORTEM_2026-05-27.md`)

---

## 1. Problem Definition

### Current Workflow (Human Process)

A senior OSINT researcher manually produces one company analysis using the proprietary "Inside Scoop for Job Seekers" framework. The process runs sequentially across four phases:

| Phase | Manual Steps | Time | Error-Prone? |
|---|---|---|---|
| Discovery | Search 6+ job boards, careers pages, filter by date, flag stale | 45–60 min | Yes — stale posting detection is inconsistent |
| Signals | Read 20–40 postings, extract growth/stability/red flag signals | 30–45 min | Yes — bias toward recent reads |
| Insights | Write 4 thematic sections, cross-reference Glassdoor CR-specific reviews | 30–45 min | Medium — synthesis quality varies with fatigue |
| Receipts | Manually build evidence table with sources, snippets, confidence scores | 20–30 min | Yes — tedious, often abbreviated |

**Total per analysis:** 2–3 hours  
**Error rate:** ~20% of postings missed per discovery pass; stale posting detection misses ~30% of aged listings  
**Volume constraint:** Maximum ~3 analyses/week at current pace

### Target State

An agentic system handles Discovery and Receipts fully autonomously. Signals extraction runs with human review checkpoint before Insights synthesis. Insights remain human-authored, informed by structured agent output.

**Human effort target post-deployment:** 30–45 min per analysis (from 2–3 hours)  
**Quality target:** Zero missed postings <90 days; 100% stale posting detection via job ID sequencing

### Success Metrics

1. Discovery pass captures ≥95% of active postings (<90 days) across all 6 source types per company
2. Stale posting flag accuracy ≥90% (validated by human spot-check on 20% sample)
3. Receipts table auto-populated with confidence scores requiring <5 min human review
4. Signals extraction matches human classification in ≥80% of cases (measured against ground-truth set of 10 prior analyses)
5. Full pipeline wall-clock time ≤20 min per company

---

## 2. System Architecture

### Workflow Decomposition (Text Diagram)

```
INPUT: Company Name + Optional Seed URL
         │
         ▼
┌─────────────────────┐
│  Agent 1            │
│  URL Discovery      │  → Lightweight (Haiku)
│  web_search         │
└─────────┬───────────┘
          │ List of target URLs (careers page, LinkedIn,
          │ Indeed CR, Glassdoor, Built In, BeBee)
          ▼
┌─────────────────────┐
│  Agent 2            │
│  Posting Scraper    │  → Lightweight (Haiku)
│  web_fetch (batch)  │
└─────────┬───────────┘
          │ Raw postings with metadata
          │ (title, date, job ID, location, URL)
          ▼
┌─────────────────────┐
│  Agent 3            │
│  Stale Filter       │  → Lightweight (Haiku)
│  + Date Validator   │
└─────────┬───────────┘
          │ Filtered postings (<90 days)
          │ + Archive flags (>90 days, kept as context)
          ▼
┌─────────────────────┐
│  Agent 4            │
│  CR Culture Intel   │  → Mid-tier (Sonnet)
│  web_search +       │
│  web_fetch          │
└─────────┬───────────┘
          │ Glassdoor CR-specific reviews,
          │ local sentiment signals
          ▼
┌─────────────────────┐
│  Agent 5            │
│  Signals Extractor  │  → Mid-tier (Sonnet)
└─────────┬───────────┘
          │ Structured signals object:
          │ {growth_cues[], stability_cues[],
          │  red_flags[], org_focus, role_clusters[]}
          ▼
    ┌─────┴──────┐
    │ ⚠️ HUMAN   │  ← CHECKPOINT 1
    │ CHECKPOINT │     Validate signal classification
    │            │     before synthesis (~10 min)
    └─────┬──────┘
          │ Approved signals object
          ▼
┌─────────────────────┐
│  Agent 6            │
│  Receipts Builder   │  → Mid-tier (Sonnet)
└─────────┬───────────┘
          │ Evidence table draft:
          │ {claim, snippet, source, confidence, archive_flag}[]
          ▼
OUTPUT: Structured JSON payload → Human authors Insights section
        using agent output as grounded input
```

### Agent Model Tier Assignments

| Agent | Task Type | Model | Rationale |
|---|---|---|---|
| URL Discovery | Classification + search | Haiku | Simple structured output; high volume |
| Posting Scraper | Retrieval + extraction | Haiku | Repetitive fetch + parse; no judgment needed |
| Stale Filter | Rule-based classification | Haiku | Deterministic logic; regex-style date/ID checks |
| CR Culture Intel | Retrieval + summarization | Sonnet | Nuanced sentiment extraction; CR-filter requires judgment |
| Signals Extractor | Reasoning + classification | Sonnet | Framework-grounded multi-signal synthesis |
| Receipts Builder | Structured output | Sonnet | Evidence attribution requires precision; confidence scoring is judgment-heavy |

### Human Checkpoints

| Checkpoint | Location | What Human Evaluates |
|---|---|---|
| CP1: Signal Validation | Post–Agent 5, pre-Receipts | Are signal classifications accurate? Any red flags suppressed? Any false positives in growth cues? |
| CP2: Receipts Spot-Check | Post–Agent 6, pre-publish | Are confidence scores calibrated? Any citations that don't support the claim? |

---

## 3. Specification for Each Agent

### Agent 1: URL Discovery

**Task description:** Given a company name and optional domain hint, produce a structured list of URLs to scrape across 6 source types: (1) official careers page, (2) LinkedIn jobs, (3) Indeed Costa Rica, (4) Glassdoor company page, (5) Built In, (6) BeBee CR. If a source is not found, flag as NOT_FOUND rather than omitting.

**Input:**
```json
{
  "company_name": "string",
  "domain_hint": "string | null",
  "target_location": "Costa Rica"
}
```

**Output:**
```json
{
  "sources": [
    {
      "source_type": "careers_page | linkedin | indeed_cr | glassdoor | builtin | bebee",
      "url": "string",
      "status": "found | not_found | requires_login"
    }
  ]
}
```

**Hard constraints:**
- Must attempt all 6 source types, even if result is NOT_FOUND
- Never fabricate URLs — if uncertain, mark `requires_verification: true`
- LinkedIn URLs must include location filter for Costa Rica

**Soft guidelines:**
- Prefer direct careers page over third-party aggregator when both exist
- Flag Greenhouse/Lever/Workday ATS domains as likely more reliable than scraped Indeed

**Edge cases:**
- Company has dual-entity structure (e.g., TD SYNNEX + Shyft): produce URL sets for both entities
- Company name has common variants (e.g., "Critical Mass" vs "CM LATAM"): search both
- Company has no CR-specific jobs page: flag as CR_PRESENCE_UNCONFIRMED

**Implementation note (v0.2 — two-step call pattern):** Agent 1 splits URL discovery across two API calls. Step 1 issues a `web_search`-only call with no `tool_choice` override — the model searches freely and returns a text analysis of findings. Step 2 forces `record_urls` with the Step 1 text as grounding context in the conversation history. Combining both tools in a single call with a forced `tool_choice` name blocks the search step: the model fills the forced tool with prior knowledge, producing hallucinated URLs that pass schema validation but fail at scrape time. See `POSTMORTEM_2026-05-27.md`.

---

### Agent 2: Posting Scraper

**Task description:** For each URL from Agent 1, fetch and extract all job postings. Output one record per posting with structured metadata.

**Input:** URL list from Agent 1

**Output per posting:**
```json
{
  "title": "string",
  "department": "string | null",
  "location": "string",
  "posted_date": "ISO8601 | null",
  "job_id": "string | null",
  "url": "string",
  "description_snippet": "string (first 500 chars)",
  "source_type": "string",
  "raw_html_preserved": "boolean"
}
```

**Hard constraints:**
- Never merge two postings into one record
- If posted_date is not parseable, set to null — do NOT estimate
- job_id must be extracted exactly as it appears in the URL or posting metadata

**Edge cases:**
- Paginated results: must follow pagination up to 5 pages or 100 postings, whichever comes first
- Duplicate postings across sources: preserve all, flag as `duplicate: true` with cross-reference

---

### Agent 3: Stale Filter + Date Validator

**Task description:** Classify each posting as ACTIVE (<90 days), BORDERLINE (90–120 days), STALE (>120 days), or DATE_UNKNOWN. Apply job ID sequence heuristic to detect undated stale postings.

**Stale Detection Logic:**
1. If posted_date is present: compare to current date, classify by threshold
2. If posted_date is null: examine job_id for sequential numbering patterns. If job_id is ≥15% lower than the median job_id across other current postings from same source, flag as LIKELY_STALE
3. If no job_id and no date: classify as DATE_UNKNOWN, keep in output with flag

**Output per posting:** original record + `{ "age_classification": "ACTIVE | BORDERLINE | STALE | DATE_UNKNOWN", "stale_signal": "date | job_id_sequence | none", "archive_flag": "boolean" }`

**Hard constraints:**
- STALE postings are NOT dropped — they are flagged and passed forward for context
- Never reclassify STALE as ACTIVE based on content alone

**Logging specification (v0.2):** Every LLM freshness call emits exactly one of two prefixed log lines:
- `[LLM_DECISION] '{title}' → {classification}` — model returned a valid schema; classification is authoritative
- `[PYDANTIC_FALLBACK] '{title}' — LLM devolvió esquema inválido, forzando DATE_UNKNOWN.` + `raw_input` + `validation_error`

`DATE_UNKNOWN` rows tagged `[PYDANTIC_FALLBACK]` are data quality events, not valid classifications. CP1 preview in `main.py` must surface the fallback count separately from legitimate `DATE_UNKNOWN` counts. A fallback rate >10% of LLM calls should trigger a system prompt review for that model version.

---

### Agent 4: CR Culture Intel

**Task description:** Search for Glassdoor reviews specifically from the Costa Rica office. Extract sentiment signals relevant to: management quality, compensation satisfaction, work-life balance, career growth ceiling, and layoff/RIF mentions.

**Input:** Company name + Glassdoor URL from Agent 1

**Output:**
```json
{
  "cr_review_count": "integer | null",
  "overall_cr_rating": "float | null",
  "sentiment_signals": {
    "management_quality": "positive | mixed | negative | no_signal",
    "comp_satisfaction": "positive | mixed | negative | no_signal",
    "growth_ceiling": "high | medium | low | no_signal",
    "layoff_mentions": "boolean",
    "layoff_recency": "recent_12mo | older | none"
  },
  "representative_quotes": ["string (max 3, <50 chars each)"],
  "global_vs_cr_delta": "string (note if CR rating differs significantly from global)"
}
```

**Hard constraints:**
- Must distinguish CR-specific reviews from global reviews — do NOT use global average as proxy
- If CR review count <5, flag as LOW_SAMPLE and reduce confidence weight
- representative_quotes must be paraphrased, not verbatim

**Edge cases:**
- Company has no Glassdoor page: flag CR_GLASSDOOR_ABSENT
- Company's CR office is very new (<12 months): note OFFICE_TOO_NEW_FOR_CULTURE_SIGNAL

---

### Agent 5: Signals Extractor

**Task description:** Given filtered job postings and culture intel, extract structured signals using the Inside Scoop framework's four signal categories.

**System prompt (abbreviated):**
> You are a senior labor market analyst specializing in Costa Rica's tech sector. You apply a specific four-category signal framework: Growth Cues, Stability Cues, Red Flags, and Org Focus. Your output must be grounded in specific job postings and evidence, not general knowledge about the company. Never infer from brand reputation alone.

**Output:**
```json
{
  "growth_cues": [
    { "signal": "string", "evidence": "posting title + source", "confidence": "high | medium | low" }
  ],
  "stability_cues": [...],
  "red_flags": [...],
  "org_focus": "engineering_hub | ops_services_hub | sales_hub | mixed",
  "career_ceiling": "product_engineering_present | services_ops_only | ambiguous",
  "role_clusters": [
    { "cluster_name": "string", "posting_count": "integer", "seniority_skew": "senior | mid | junior | mixed" }
  ],
  "pay_transparency_signal": "present | absent | partial",
  "hiring_velocity": "high | medium | low | stale"
}
```

**Hard constraints:**
- Every signal must cite at least one specific posting or source
- `org_focus` classification must be justified in 1 sentence
- Do NOT classify as growth_cue any pattern that could also be replacement hiring — flag ambiguous cases separately

**Soft guidelines:**
- Prefer conservative confidence scores — better to say "medium" than inflate to "high"
- If red_flags list is empty, note explicitly: "No red flags detected in this pass" — do not omit the key

---

### Agent 6: Receipts Builder

**Task description:** Produce the sourced evidence table for the final report. Every claim in the signals object must have a corresponding receipt row.

**Output per row:**
```json
{
  "claim": "string (paraphrased assertion)",
  "snippet": "string (<80 chars, from source)",
  "source": "URL",
  "source_type": "careers_page | linkedin | indeed | glassdoor | news | other",
  "confidence": "1-5 integer",
  "archive_flag": "boolean",
  "date_retrieved": "ISO8601"
}
```

**Confidence scoring rubric:**
- 5: Primary source (official careers page), posting <30 days, claim directly matches
- 4: Primary source, posting 30–90 days, or strong secondary source
- 3: Secondary source (LinkedIn, Indeed), claim inferred from pattern
- 2: Source is Glassdoor with <5 CR reviews, or DATE_UNKNOWN posting
- 1: Archive-flagged, speculative, or single data point

**Hard constraints:**
- Minimum one receipt per signal object entry
- Confidence 1 receipts must include a `low_confidence_note` field explaining why
- Never fabricate source URLs

---

## 4. Evaluation Framework

### Test Cases per Agent

**Agent 3 (Stale Filter) — highest failure risk:**

| Case | Input | Expected Output | Failure Mode to Detect |
|---|---|---|---|
| Common | Posting with explicit date 45 days ago | ACTIVE | None |
| Edge | Posting with date exactly 90 days ago | BORDERLINE, not ACTIVE | Off-by-one threshold error |
| Adversarial | Posting with no date, job_id = 1847 when median is 3200 | LIKELY_STALE via sequence heuristic | Silent failure — agent classifies as DATE_UNKNOWN instead of applying heuristic |

**Agent 5 (Signals Extractor) — highest quality risk:**

| Case | Input | Expected Output | Failure Mode to Detect |
|---|---|---|---|
| Common | 15 active postings, mix of eng and ops roles | Mixed org_focus, 2–3 growth cues | Correct classification |
| Edge | 2 active postings, 8 stale | Low hiring_velocity; stale postings in context but not driving signals | Agent over-indexes on stale content |
| Adversarial | Company with strong brand (e.g., Google CR) but only sales roles posted | org_focus = sales_hub, NOT engineering_hub | Sycophantic confirmation — agent assumes eng presence based on brand |

### System-Level Evaluation Criteria

1. **Recall:** % of human-identified signals also identified by agent (target ≥80%)
2. **Precision:** % of agent signals confirmed as accurate by human reviewer (target ≥85%)
3. **Stale detection accuracy:** % of LIKELY_STALE flags confirmed correct (target ≥90%)
4. **Evidence grounding rate:** % of Receipts rows with valid, retrievable source URL (target 100%)

### Quality Drift Detection

- Run 3-analysis batch weekly against same companies (Akamai CR, Workday CR, Granicus) as control set
- Alert if precision drops >5 points week-over-week
- Alert if stale detection accuracy drops below 85%
- Manual re-calibration trigger: two consecutive weeks below threshold

---

## 5. Trust Boundary Map

| Sub-task | Cost of Error | Reversibility | Frequency | Verification Method | Oversight Level |
|---|---|---|---|---|---|
| URL Discovery | Medium — missed source = missed postings | Reversible — re-run | Every analysis | Human spot-check 2 sources per run | Automated with sampling |
| Posting Scraper | Medium — missed posting = false signal | Reversible | Every analysis | Count validation vs. source UI | Automated with sampling |
| Stale Filter | High — stale content driving insights = misleading output | Partially reversible | Every analysis | Human reviews LIKELY_STALE flags | Automated with human review of flags |
| CR Culture Intel | Medium — wrong sentiment = misleading culture signal | Reversible | Every analysis | Human validates CR-vs-global distinction | Automated with sampling |
| Signals Extractor | **High — false red flag or missed red flag** | Reversible before publish | Every analysis | **Full human review at CP1** | Human review before action |
| Receipts Builder | Medium — wrong confidence score | Reversible | Every analysis | Human spot-check 20% of rows | Automated with sampling |

---

## 6. Failure Mode Analysis

| Pattern | Applies? | Most Likely Location | Detection Method | Mitigation |
|---|---|---|---|---|
| **Context Degradation** | Yes — high risk | Agent 5 (Signals) when posting count >40 | Quality drops on signals from postings near end of context window | Chunk postings into batches of 15; run Agent 5 per chunk, then merge |
| **Specification Drift** | Yes — medium risk | Agent 5 across repeated runs on same company | Signal categories expand beyond the 4 defined (agent invents new categories) | Enforce strict JSON schema output; schema validation rejects extra keys |
| **Sycophantic Confirmation** | **Yes — highest risk** | Agent 4 (Culture Intel) + Agent 5 (Signals) for well-known brands | Agent attributes positive signals to brand reputation, not actual postings | System prompt: "Never infer from brand reputation. Cite specific postings only." + adversarial test cases in eval suite |
| **Tool Selection Errors** | Low risk | Agent 1 (URL Discovery) | Agent uses web_fetch instead of web_search for discovery phase | Explicit tool routing in system prompt; tool use validation step |
| **Cascade Failure** | Yes — medium risk | Stale Filter error → corrupts Signals input | Bad stale classification → wrong signals → wrong Insights | Human checkpoint CP1 breaks the cascade; Agent 5 receives human-validated postings list |
| **Silent Failure** | **Yes — highest risk** | Agent 3 (Stale Filter) | Agent returns DATE_UNKNOWN instead of applying job_id heuristic | Mandatory: if DATE_UNKNOWN count >30% of total postings, trigger human alert before proceeding |
| **Forced tool_choice blocking** | **Yes — confirmed in v0.1** | Agent 1 (URL Discovery) | `tool_choice` with a specific tool name prevents any other tool from running; model fills the forced tool with prior knowledge; hallucinated URLs pass schema validation and reach Agent 2 where they yield zero postings | Two-step call pattern: `web_search` in Step 1 with no `tool_choice`, `record_urls` forced in Step 2 with Step 1 text as context. Never place a search prerequisite and its downstream recorder in the same call with a forced `tool_choice` name |

---

## 7. Cost Model

> All figures are estimates using May 2026 Anthropic API pricing. Actual costs depend on content length variability.

### Token Estimates Per Analysis (Single Company, ~25 Active Postings)

| Agent | Input Tokens | Output Tokens | Model | Cost (est.) |
|---|---|---|---|---|
| Agent 1: URL Discovery | ~2,500 (2 calls) | ~700 (2 calls) | Haiku | $0.0002 |
| Agent 2: Posting Scraper (25 postings) | 35,000 | 5,000 | Haiku | $0.003 |
| Agent 3: Stale Filter | 6,000 | 2,000 | Haiku | $0.0007 |
| Agent 4: CR Culture Intel | 8,000 | 1,500 | Sonnet | $0.027 |
| Agent 5: Signals Extractor | 15,000 | 2,000 | Sonnet | $0.051 |
| Agent 6: Receipts Builder | 10,000 | 3,000 | Sonnet | $0.039 |
| **TOTAL** | **~74,500** | **~13,800** | — | **~$0.12** |

### Volume Scaling

| Volume | Daily Cost | Monthly Cost |
|---|---|---|
| 1 analysis/day (current baseline) | $0.12 | $3.60 |
| 10 analyses/day | $1.20 | $36 |
| 100 analyses/day | $12.00 | $360 |

### Break-Even vs. Human Cost

- Human time per analysis: 2.5 hours (blended estimate)
- At $50/hr effective cost → $125 per human analysis
- Agent cost per analysis: $0.12 + ~30 min human review ($25) = **$25.12 total**
- **Break-even:** First analysis. ROI is 5x on time; 80% cost reduction.

---

## 8. What This Spec Demonstrates

This document is a portfolio artifact. It evidences the following five of the seven market-premium AI skills:

| Skill | Where Demonstrated |
|---|---|
| **Specification Precision** | Agent specs with explicit input/output schemas, hard constraints, and edge case handling — precise enough for an engineering team to build from |
| **Evaluation & Quality Judgment** | Section 4: domain-specific test cases including adversarial cases (brand sycophancy), precision/recall targets, and drift detection method |
| **Decomposition for Delegation** | Section 2: 6-agent architecture with explicit task classification per step (retrieval, classification, reasoning, judgment) and human checkpoints at the right boundary |
| **Failure Pattern Recognition** | Section 6: all six failure patterns analyzed, two flagged as highest risk (sycophantic confirmation, silent failure) with domain-specific detection and mitigation |
| **Cost & Token Economics** | Section 7: per-agent cost breakdown, model tier rationale, volume scaling, and break-even vs. human labor — not hand-wavy, actual numbers |

**Skills not evidenced here (separate artifacts needed):**
- Trust Boundary & Security Design (would require threat modeling for multi-tenant use)
- Context Architecture (partially demonstrated in cascade failure mitigation; needs deeper treatment)

---

*This spec was built using the Agent Product Spec Builder methodology. It is a pre-build design document, not a description of a deployed system.*
