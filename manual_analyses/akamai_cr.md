# Inside Scoop Manual Analysis — Akamai CR

**Date:** 2026-06-20
**Analyst:** Ric Hernández
**Time cap:** 90 min total / 10 min per signal section
**Posting universe:** 9 active CR postings (May snapshot)
**Culture intel source:** 69 CR-specific Glassdoor reviews

---

## M2 — Human vs. Agent on Akamai CR

### What this milestone tests

Before trusting the pipeline on a company I'd never analyzed, I ran Agent 5 against three companies I'd already analyzed by hand: **Akamai CR, Lumenalta, Workday CR.**

This document documents the first comparison. Lumenalta and Workday CR follow.

### Protocol

| Constraint | Detail |
| --- | --- |
| Posting universe | Identical — 9 active CR postings from the May snapshot |
| Culture intel | Identical — 69 CR-specific Glassdoor reviews via Agent 4 |
| Human time cap | 90 minutes total, 10 min per signal section |
| Agent timing | No constraint |
| No-peek rule | Pre-comparison reflection written before opening Agent 5 output |

### Headline finding

**My red flags section was empty. The agent's had three.**

I had read the same culture intel. I even named the concerns in my reflection notes. I just didn't promote any of them to the red-flags section under time pressure.

The full breakdown is below.

---

## Signal-by-Signal Comparison

### Growth Cues

| Human | Agent | Verdict |
| --- | --- | --- |
| G1: >50% Senior roles (conf 3) | — (treated as cluster attribute, not signal) | Human-only |
| G2: Principal role present (conf 2) | Principal/architect senior-layer buildout (conf medium) | **Match** |
| G3: >50% Engineering/Architecture (conf 3) | (classified under stability + org_focus) | Classification divergence |
| G4: Also hiring Sales/Finance (conf 3) | Sales intern + Finance specialist as *ambiguous* (backfill?) | Disagree |
| G5: No stale postings (conf 3) | (`hiring_velocity: medium` as separate field) | Human-only |
| — | Dual-seniority DevOps/DevSecOps coverage = functional expansion | Agent-only |

**Growth: 1 match, 2 disagreements, 2 human-only, 1 agent-only.**

### Stability Cues

| Human | Agent | Verdict |
| --- | --- | --- |
| S1: Engineering hiring multiple roles | Multi-department technical hiring spread | **Match** |
| S2: Sales/Finance hiring | — (duplicate of G4) | Human-only, duplicate |
| S3: First Principal role signals talent confidence | (agent classified this as growth, not stability) | Reclassification |
| — | CR rating parity with global (4.3 = 4.3) | **Agent-only** |
| — | Positive WLB sentiment in CR reviews | **Agent-only** |

**Stability: 1 match, 1 reclassification, 1 human duplicate, 2 agent-only (both culture-derived).**

### Red Flags ⚠️ The Inversion

| Human | Agent | Verdict |
| --- | --- | --- |
| **(empty)** | Confirmed layoffs in last 12 months, "twice in ~12 months" — conf **high** | Agent-only |
| **(empty)** | Mixed management: leadership changes, closed-door culture — conf medium | Agent-only |
| **(empty)** | CR comp below market, trailing global benchmark — conf medium | Agent-only |

**Red Flags: 0 human signals, 3 agent signals.** One high-confidence.

### Ambiguous Cues

| Human | Agent |
| --- | --- |
| A1: Hiring many external seniors = possible short internal path (conf 1) | 4 ambiguous signals (Product Support backfill, Finance backfill, Intern routine cycle, SRE II backfill) |

**Different analytical lens entirely.** I flagged a systemic ambiguity (internal mobility); the agent flagged per-posting ambiguity (backfill vs. growth). Both valid, neither overlaps.

### Structural Calls

| Field | Human | Agent | Verdict |
| --- | --- | --- | --- |
| `org_focus` | `engineering_hub` (6 of 9 technical) | `engineering_hub` (6 of 9 technical) | ✅ Exact match |
| `career_ceiling` | `principal_architect_present` | `product_engineering_present` | Adjacent miss — agent over-escalated one enum slot |
| `pay_transparency_signal` | (no field in template) | `absent` | Agent-only, captured by schema |

---

## Match Rate

| Metric | Result |
| --- | --- |
| Exact signal match | ~15% |
| Conceptual overlap (match + reclassification + partial) | ~38% |
| Structural calls | 75% (1 exact + 1 adjacent of 2) |
| Red flags caught | Human 0% / Agent 100% |

---

## Where the Agent Won

1. **Red-flag promotion under no time pressure.** Three culture-derived signals I had the evidence for but didn't promote.
2. **Schema discipline.** A dedicated `pay_transparency_signal` field caught what my unstructured template let drift into reflection notes.
3. **Cross-source stability call.** CR rating parity with global (4.3 = 4.3) is a synthesis I didn't make — required holding two numbers in mind at once after a 60-minute analysis.

## Where the Human Won

1. **Base-rate reasoning across snapshots.** I read "single Sales + single Finance posting" as diversification because I know Akamai CR's posting base is large. The agent reasons within the snapshot and flagged it as ambiguous backfill.
2. **Systemic insight from posting structure.** "Hiring many external seniors might signal a short internal promotion path" — low confidence, but a hypothesis the agent can't generate from one snapshot.
3. **`career_ceiling` enum calibration.** The agent over-escalated to `product_engineering_present` on the same Principal SWE evidence that supports `principal_architect_present`. Human enum discipline beat agent inflation.

## Where the Agent Was Weak

- **Ambiguous-cue bloat.** Four ambiguous signals, all variants of "single posting = backfill?". Pattern-matching rather than insight.
- **`career_ceiling` over-escalation.** One enum level too high.
- **No base-rate priors.** Single-snapshot reasoning can't distinguish diversification from churn.

## Where the Human Was Weak

- **Empty red flags section.** The headline finding.
- **Signal duplication.** G1 and G3 partial duplicates of S1. G4 = S2 verbatim. Inflated count for sense of section completeness.
- **Generic actionable note.** Section 8 closed with "ask comp range" — generic. The reflection notes had three sharper questions that didn't get promoted.

---

## Governing Principles

Three principles emerged from this comparison. They generalize beyond Akamai CR.

### 1. Humans under time pressure compress on whichever dimension requires the most context-switching.

For employer analysis, that's the qualitative culture layer. Agents don't context-switch.

### 2. The schema is the discipline.

If a field doesn't exist in the output template, the insight doesn't survive the workflow.

### 3. Agents reason within the snapshot. Humans reason across snapshots.

Base-rate priors are still a human edge.

---