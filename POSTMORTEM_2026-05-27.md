# Postmortem: Agent 1 URL Hallucination + Agent 3 Silent Fallback Ambiguity

**Date:** 2026-05-27  
**Severity:** High (Agent 1) / Medium (Agent 3)  
**Status:** Resolved  
**Affected components:** `agent_1.py` · `agent_3.py`  

---

## Summary

Two bugs were identified and patched in a single session:

1. **Agent 1 (URL Discovery):** `tool_choice` forced `record_urls` as the model's only tool call, blocking `web_search` entirely. The model hallucinated `careers_page` and BeBee URLs from prior knowledge instead of searching for them. Output passed Pydantic schema validation, making the error silent.

2. **Agent 3 (Stale Filter):** `DATE_UNKNOWN` from a Pydantic `ValidationError` fallback was indistinguishable in logs from a legitimate LLM decision to classify a posting as `DATE_UNKNOWN`. Both paths produced identical output; neither left a trace.

---

## Timeline

| Time | Event |
|---|---|
| T+0 | Bug reported: Agent 1 returning plausible-looking but unverified careers URLs |
| T+5 | `agent_1.py` reviewed — root cause identified: `tool_choice={"type":"tool","name":"record_urls"}` |
| T+10 | Two-step fix proposed and approved |
| T+12 | `agent_1.py` patched |
| T+15 | `agent_3.py` reviewed — logging ambiguity identified in `ValidationError` fallback |
| T+20 | Logging fix proposed and approved |
| T+22 | `agent_3.py` patched |

---

## Root Cause Analysis

### Bug 1 — Agent 1: Forced `tool_choice` Blocks `web_search`

**Code path (pre-patch):**

```python
response = client.messages.create(
    tools=[
        {"type": "web_search_20250305", "name": "web_search"},
        record_tool  # record_urls
    ],
    tool_choice={"type": "tool", "name": "record_urls"},  # ← root cause
    messages=[...]
)
```

`tool_choice={"type": "tool", "name": "record_urls"}` instructs the model to call `record_urls` as its **first and only** action. Despite `web_search` appearing in `tools`, the model never receives an opportunity to invoke it. The model populates `record_urls` directly from prior knowledge, producing hallucinated URLs.

For BeBee and custom careers pages — sources that require real-time lookup — this generates silently incorrect output. The schema validates because the URLs are structurally well-formed; they simply point to pages that don't exist. Agent 2 then fetches nothing and produces zero postings from those sources.

**Why it was easy to miss:** The output JSON passes Pydantic `HttpUrl` validation. URLs look plausible (e.g., `https://www.bebee.com/company/akamai`). Without a live HTTP reachability check, the error is invisible until Agent 2 returns empty results — which could also be attributed to scraping failures.

---

### Bug 2 — Agent 3: `ValidationError` Fallback Produces Ambiguous `DATE_UNKNOWN`

**Code path (pre-patch):**

```python
try:
    return LLMFreshnessOutput(**block.input)
except ValidationError as e:
    print(f"Error de validación Pydantic desde el LLM: {e}")
    return LLMFreshnessOutput(
        age_classification=AgeClassification.DATE_UNKNOWN,
        stale_signal=StaleSignal.NONE,
        archive_flag=False
    )
```

When the LLM returns a malformed schema (e.g., an unrecognized enum value, a missing required field), Pydantic raises `ValidationError` and the fallback silently emits `DATE_UNKNOWN` — the same value the LLM returns when it **legitimately** finds no date signals in a posting. The two paths are identical in output and in logs.

**Impact:** Any spot-check of `DATE_UNKNOWN` postings at CP1 cannot determine whether the classification reflects genuine data absence or a crashed LLM response. Downstream, Agent 6 (Receipts Builder) assigns a confidence score of 2 to all `DATE_UNKNOWN` rows without distinguishing signal quality from schema failure.

---

## Impact Assessment

| Metric | Estimated Impact |
|---|---|
| Incorrect `careers_page` URLs | 100% of pre-patch runs (always hallucinated; never searched) |
| Incorrect BeBee URLs | 100% of pre-patch runs |
| Agent 2 posting yield from affected sources | ~0 (scraper fetches unreachable pages) |
| `DATE_UNKNOWN` provenance | Unquantified — no historical log differentiates LLM decision from Pydantic crash |
| Confidence score integrity in Receipts Builder | Degraded — `[PYDANTIC_FALLBACK]` rows counted equal to genuine `DATE_UNKNOWN` |

---

## Fix

### Agent 1 — Two-Step Call Pattern

Separated the single API call into two calls with distinct, non-overlapping responsibilities.

```
                        AGENT 1 — Two-Step Flow (post-patch)

  Input: company_name
        │
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 1 — Search Call                                       │
  │                                                             │
  │  tools:       [web_search]                                  │
  │  tool_choice: (absent — model decides when to stop)         │
  │  max_tokens:  2000                                          │
  │                                                             │
  │  Model calls web_search one or more times.                  │
  │  API executes searches server-side.                         │
  │  Model produces a text analysis of findings.                │
  └────────────────────────────┬────────────────────────────────┘
                               │
                               │  research_findings: str
                               │  (extracted text blocks from response)
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  STEP 2 — Record Call                                       │
  │                                                             │
  │  tools:       [record_urls]                                 │
  │  tool_choice: {"type": "tool", "name": "record_urls"}       │
  │  max_tokens:  1000                                          │
  │                                                             │
  │  messages:                                                  │
  │    user      → original research prompt                     │
  │    assistant → research_findings  ← search grounding        │
  │    user      → "registra ahora las URLs con record_urls"    │
  └────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
  List[SourceURL]  — URLs grounded in actual search results
```

**What the single-call design did (pre-patch):**

```
  BEFORE (Bug):
  ┌──────────────────────────────────────────────────────────────┐
  │  Single Call                                                 │
  │                                                              │
  │  tools:       [web_search, record_urls]                      │
  │  tool_choice: {"type": "tool", "name": "record_urls"}  ← BUG │
  │                                                              │
  │  Model MUST call record_urls as its first and only action.   │
  │  web_search is present but never reachable.                  │
  │  record_urls is populated from prior knowledge.              │
  │  Output is hallucinated and structurally valid.              │
  └──────────────────────────────────────────────────────────────┘
```

---

### Agent 3 — Distinguishable Logging

Added `[LLM_DECISION]` on the success path and `[PYDANTIC_FALLBACK]` on the except path. The fallback now logs `raw_input` (the exact malformed payload from the LLM) and the full `ValidationError`.

**Before:**
```
Error de validación Pydantic desde el LLM: 1 validation error for LLMFreshnessOutput
age_classification
  Input should be 'ACTIVE', 'BORDERLINE', 'STALE' or 'DATE_UNKNOWN' [type=enum, ...]
```

**After — success path:**
```
[LLM_DECISION] 'Senior Software Engineer, Costa Rica' → DATE_UNKNOWN
```

**After — fallback path:**
```
[PYDANTIC_FALLBACK] 'Senior Software Engineer, Costa Rica' — LLM devolvió esquema inválido, forzando DATE_UNKNOWN.
  raw_input={'age_classification': 'UNKNOWN', 'stale_signal': 'none', 'archive_flag': False}
  validation_error=1 validation error for LLMFreshnessOutput
  age_classification
    Input should be 'ACTIVE', 'BORDERLINE', 'STALE' or 'DATE_UNKNOWN' [type=enum, ...]
```

`[LLM_DECISION]` and `[PYDANTIC_FALLBACK]` are mutually exclusive for any given posting. Scanning logs for `[PYDANTIC_FALLBACK]` now gives an exact count of schema failures per run.

---

## Lessons Learned

**1. `tool_choice` with a specific name is a sequential lock, not a priority hint.**  
When `tool_choice={"type":"tool","name":"X"}` is set, the model calls `X` immediately and stops. Any tool that must run before `X` — including `web_search` — must live in a separate API call. Multi-tool + forced `tool_choice` is only safe when `X` itself has no prerequisites.

**2. Pydantic `ValidationError` fallbacks need provenance markers.**  
A fallback that emits a valid enum value (`DATE_UNKNOWN`) is indistinguishable from a correct LLM decision without explicit tagging. Always prefix the fallback log with a distinguishable string (`[PYDANTIC_FALLBACK]`) and include the raw LLM payload — it's the only way to diagnose what the LLM actually returned.

**3. Structural validity is not semantic validity.**  
Agent 1's hallucinated URLs are valid `HttpUrl` instances. They pass Pydantic, they pass the pipeline, and they reach Agent 2 where they silently return zero postings. HTTP reachability is a different check from schema validity, and it needs to happen at the Agent 1 boundary.

**4. Both bugs shared a common pattern: silent failure with valid-looking output.**  
Neither raised an exception. Neither produced anomalous output shapes. Both required trace-level inspection to detect. The pipeline's type-safety guarantees (Pydantic contracts between agents) protect data shape but not data truth.

---

## Open Action Items

| Item | Priority | Status |
|---|---|---|
| Add HTTP HEAD check in Agent 1 post-processing — flag `requires_verification` on unreachable URLs | High | Open |
| Surface `[PYDANTIC_FALLBACK]` count in CP1 summary in `main.py` | Medium | Open |
| Add Agent 1 URL hallucination test case to evaluation suite | Medium | Open |
| Add `tool_choice` constraint to agent development guidelines in CLAUDE.md | Low | Open |
| Update `OSINT_Agent_Product_Spec.md` | — | Completed (this session) |
