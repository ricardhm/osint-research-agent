# Postmortem: Cross-Source Dedup Failure + Relative Date Parser Gap in Agent 3

**Date:** 2026-05-27  
**Severity:** High (dedup) / Medium (relative dates)  
**Status:** Resolved  
**Affected component:** `agent_3.py` — `deduplicate_jobs`, `process_postings`  

---

## Summary

Two bugs were identified and patched in `agent_3.py`:

1. **Cross-source dedup failure:** The dedup key `title|location` broke when the same job appeared across multiple sources with different location formats ("Costa Rica" vs "San José, Costa Rica" vs "Remote (Costa Rica)"). Unicode variance compounded the issue: "San José" vs "San Jose" produced different keys. Each source's formatting convention produced a unique key for the same posting, so duplicates were never collapsed.

2. **Relative date strings bypassing deterministic classification:** Indeed CR formats `posted_date` as "hace 3 días" or "3 days ago" instead of ISO8601. The deterministic ISO parser fails with `ValueError`, but because `posted_date` is truthy, the `elif` job_id branch is unreachable. The posting falls directly to the LLM, which — lacking date information in the snippet — returns `DATE_UNKNOWN`. A deterministic result was available; the system paid stochastic cost to get a worse answer.

---

## Timeline

| Time | Event |
|---|---|
| T+0 | Reported: dedup count suspicious — more unique postings than expected for companies with both Indeed CR and Careers Page presence |
| T+5 | Root cause identified: `title\|location` key; location format varies per source |
| T+10 | Secondary finding: Unicode variance ("San José" vs "San Jose") also breaks key match |
| T+15 | Fix designed: title-only key + NFKD normalization + `_SOURCE_PRIORITY` tiebreaker |
| T+20 | Second bug reported: Indeed CR `posted_date` format "hace N días" → LLM fallback → DATE_UNKNOWN |
| T+30 | Relative date regex parser designed — 9 patterns covering ES + EN, hours/days/weeks/months |
| T+35 | Both fixes implemented and committed |

---

## Root Cause Analysis

### Bug 1 — Cross-Source Dedup Failure

**Location format variance across sources:**

| Source | Location field example |
|---|---|
| `careers_page` | `"Costa Rica"` |
| `indeed_cr` | `"San José, Costa Rica"` |
| `linkedin` | `"San José Province, Costa Rica"` |
| `builtin` | `"Remote (Costa Rica)"` |
| `bebee` | `"San Jose, CR"` |

The old key:
```python
key = f"{posting.title.strip().lower()}|{posting.location.strip().lower()}"
```

A posting titled "Software Engineer II" from five sources would produce five distinct keys. The dedup map never detected a collision; all five entries were kept.

**Unicode variance compounds the issue:**

"San José" (with accent) vs "San Jose" (without) produce different strings after `.lower()`. No NFKD decomposition was applied, so ASCII-normalized duplicates were also missed.

**Impact:** Posting counts inflated across multi-source companies. Agent 3 passed redundant postings to Agent 5 (Signals Extractor), which over-indexed on roles that appeared repeatedly across sources and interpreted repetition as hiring volume signal.

---

### Bug 2 — Relative Date String Bypasses Deterministic Classification

**Code path (pre-patch):**

```python
if posting.posted_date:                          # "hace 3 días" → truthy
    try:
        posted_dt = datetime.fromisoformat(...)  # ValueError: not ISO8601
        ...
    except ValueError:
        pass                                     # classification_val stays None

elif posting.job_id and ...:                     # UNREACHABLE — previous if was taken
    ...

if classification_val is None:                   # True
    llm_decision = evaluate_job_freshness_with_llm(posting)
    # LLM sees snippet with no date → returns DATE_UNKNOWN
```

The `elif` for job_id is structurally unreachable when `posted_date` is a non-ISO string. The posting goes straight to the LLM despite having parseable date information in `posted_date`. The LLM, reasoning from the snippet rather than the date field it cannot see, classifies as `DATE_UNKNOWN`.

**Impact:** Every Indeed CR posting with a relative date string consumed an LLM call and produced `DATE_UNKNOWN` instead of `ACTIVE`. CP1 DATE_UNKNOWN counts were inflated; human reviewers spent time on postings that were straightforwardly fresh.

---

## Fix

### Bug 1 — Title-Only Key + Unicode Normalization + Source Priority Tiebreaker

**`_normalize_key` (existing from prior patch):** applies `unicodedata.NFKD` decomposition then strips combining characters, collapsing "San José" → "san jose" and handling ligatures, typographic variants, and full-width characters.

**Key change:** `title|location` → `title` only. Location is not a reliable dedup axis cross-source; title normalized to ASCII is sufficient to detect the same role.

**Tiebreaker change:** `if careers_page and not careers_page` → compare by `_SOURCE_PRIORITY` index. Lower index wins:

```
careers_page(0) > builtin(1) > indeed_cr(2) > linkedin(3) > bebee(4)
```

Any `source_type` not in the map gets priority 99 and always loses.

```
  for each RawPosting:
        │
        ▼
  key = _normalize_key(title)
  ┌─────────────────────────────────────────────┐
  │ NFKD decompose → lowercase → strip combining │
  │ "San José"  →  "san jose"                    │
  │ "SOFTWARE ENGINEER II" → "software engineer ii" │
  └────────────────────┬────────────────────────┘
                       │
                       ▼
              key in unique_map?
              ├── NO  → insert
              └── YES → compare _SOURCE_PRIORITY
                         ├── incoming < current → replace
                         └── incoming ≥ current → discard
```

---

### Bug 2 — Three-Tier Date Classification Cascade

Inserted `_parse_relative_date()` inside the `except ValueError` block, between the failed ISO parse and giving up. The function matches 9 regex patterns compiled at import time:

| Pattern | Unit | Example |
|---|---|---|
| `hace\s+(\d+)\s+hora[s]?` | hours → 0d | "hace 3 horas" |
| `hace\s+(\d+)\s+d[ií]a[s]?` | days | "hace 3 días" |
| `hace\s+(\d+)\s+semana[s]?` | weeks×7 | "hace 2 semanas" |
| `hace\s+(\d+)\s+mes(?:es)?` | months×30 | "hace 5 meses" |
| `(\d+)\s+hour[s]?\s+ago` | hours → 0d | "3 hours ago" |
| `(\d+)\s+day[s]?\s+ago` | days | "3 days ago" |
| `(\d+)\s+week[s]?\s+ago` | weeks×7 | "2 weeks ago" |
| `(\d+)\s+month[s]?\s+ago` | months×30 | "5 months ago" |
| `just now / ahora mismo / recién` | now → 0d | "just now" |

```
  posted_date present?
        │
       YES
        │
        ▼
  try datetime.fromisoformat()
        │
        ├── OK  → classify by age.days ──► ACTIVE / BORDERLINE / STALE
        │         StaleSignal.DATE
        │
        └── ValueError
               │
               ▼
         _parse_relative_date(posted_date)
               │
               ├── match → relative_days
               │            │
               │            ├── <90  → ACTIVE,     StaleSignal.DATE
               │            ├── <120 → BORDERLINE, StaleSignal.DATE
               │            └── ≥120 → STALE,      StaleSignal.DATE
               │            logs: [RELATIVE_DATE] '{title}' → '{text}' = Nd
               │
               └── None → classification_val stays None
                            │
                            ▼
                     (falls through to job_id elif or LLM)
```

---

## Impact

| Metric | Before | After |
|---|---|---|
| Dedup accuracy cross-source | Fails on all location format variants | Collapses by title; location-independent |
| Unicode dedup accuracy | "San José" ≠ "San Jose" → duplicate passes | Normalized to same key |
| Source priority | Careers Page only; binary check | 5-tier priority; any source type handled |
| Indeed CR relative date → LLM calls | 100% of relative-date postings | 0% if pattern matches |
| Indeed CR relative date → DATE_UNKNOWN | 100% of relative-date postings | 0% if pattern matches |

---

## Lessons Learned

**1. Location is not a stable dedup axis in a multi-source pipeline.**  
Each job board formats location according to its own schema. Any dedup key that includes location will fail across sources. Title normalized to a common form is the minimal stable key.

**2. A truthy `posted_date` with a non-ISO format blocks the job_id heuristic.**  
The `elif` structure means: if `posted_date` is present but unparseable, the job_id branch is structurally unreachable. A relative date parser must live *inside* the `except ValueError` to preserve the original control flow.

**3. Regex patterns are cheaper than LLM calls and more accurate for structured signals.**  
The LLM, seeing a snippet without date context, returns `DATE_UNKNOWN` — which is technically correct but preventable. Deterministic parsing of a known format is faster, free, and produces a classified output (`ACTIVE`/`BORDERLINE`/`STALE`) instead of an unknown.

**4. Compile regexes at import time, not per-call.**  
`_RELATIVE_PATTERNS` is a module-level list of pre-compiled patterns. Per-call `re.compile()` inside a loop that runs once per posting would add latency at scale.

---

## Open Action Items

| Item | Priority | Status |
|---|---|---|
| Add "hace un día" / "a week ago" (word-form numerals) to `_parse_relative_date` | Low | Open |
| Add cross-source dedup test cases to evaluation suite (Section 4 of spec) | Medium | Open |
| Update `OSINT_Agent_Product_Spec.md` | — | Completed (this session) |
