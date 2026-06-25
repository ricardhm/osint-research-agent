# Inside Scoop Engine

**A six-agent OSINT pipeline that analyzes tech companies in Costa Rica as employers.**

Discovers active postings → fetches → dedupes → pulls CR-specific Glassdoor culture intel → classifies signals → outputs an Inside Scoop report.

Built in Python with Anthropic SDK, Pydantic v2, and a strict spec-driven inter-agent contract.

**Framework credit:** The "Inside Scoop for Job Seekers" analytical framework — including the signal terminology (growth cues, stability cues, red flags, org focus) and the Receipts table with confidence scoring — originated with [Nate B. Jones](https://www.linkedin.com/in/natebjones/) via his Substack. This project adapts that manual framework into a production agentic pipeline. The engineering implementation, inter-agent schema design, structured output contracts, and human-vs-agent evaluation methodology are original work built on top of his foundation.


---

## M2 — Human vs. Agent on Akamai CR

### What this milestone tests

Before trusting the pipeline on a company I'd never analyzed, I ran Agent 5 against three companies I'd already analyzed by hand: **Akamai CR, Lumenalta, Workday CR.**

This README documents the first comparison. Lumenalta and Workday CR follow.

### Protocol

| Constraint | Detail |
|---|---|
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
|---|---|---|
| G1: >50% Senior roles (conf 3) | — (treated as cluster attribute, not signal) | Human-only |
| G2: Principal role present (conf 2) | Principal/architect senior-layer buildout (conf medium) | **Match** |
| G3: >50% Engineering/Architecture (conf 3) | (classified under stability + org_focus) | Classification divergence |
| G4: Also hiring Sales/Finance (conf 3) | Sales intern + Finance specialist as *ambiguous* (backfill?) | Disagree |
| G5: No stale postings (conf 3) | (`hiring_velocity: medium` as separate field) | Human-only |
| — | Dual-seniority DevOps/DevSecOps coverage = functional expansion | Agent-only |

**Growth: 1 match, 2 disagreements, 2 human-only, 1 agent-only.**

### Stability Cues

| Human | Agent | Verdict |
|---|---|---|
| S1: Engineering hiring multiple roles | Multi-department technical hiring spread | **Match** |
| S2: Sales/Finance hiring | — (duplicate of G4) | Human-only, duplicate |
| S3: First Principal role signals talent confidence | (agent classified this as growth, not stability) | Reclassification |
| — | CR rating parity with global (4.3 = 4.3) | **Agent-only** |
| — | Positive WLB sentiment in CR reviews | **Agent-only** |

**Stability: 1 match, 1 reclassification, 1 human duplicate, 2 agent-only (both culture-derived).**

### Red Flags ⚠️ The Inversion

| Human | Agent | Verdict |
|---|---|---|
| **(empty)** | Confirmed layoffs in last 12 months, "twice in ~12 months" — conf **high** | Agent-only |
| **(empty)** | Mixed management: leadership changes, closed-door culture — conf medium | Agent-only |
| **(empty)** | CR comp below market, trailing global benchmark — conf medium | Agent-only |

**Red Flags: 0 human signals, 3 agent signals.** One high-confidence.

### Ambiguous Cues

| Human | Agent |
|---|---|
| A1: Hiring many external seniors = possible short internal path (conf 1) | 4 ambiguous signals (Product Support backfill, Finance backfill, Intern routine cycle, SRE II backfill) |

**Different analytical lens entirely.** I flagged a systemic ambiguity (internal mobility); the agent flagged per-posting ambiguity (backfill vs. growth). Both valid, neither overlaps.

### Structural Calls

| Field | Human | Agent | Verdict |
|---|---|---|---|
| `org_focus` | `engineering_hub` (6 of 9 technical) | `engineering_hub` (6 of 9 technical) | ✅ Exact match |
| `career_ceiling` | `principal_architect_present` | `product_engineering_present` | Adjacent miss — agent over-escalated one enum slot |
| `pay_transparency_signal` | (no field in template) | `absent` | Agent-only, captured by schema |

---

## Match Rate

| Metric | Result |
|---|---|
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

## Architecture

```
Agent 1 (URL Discovery)
   ↓
Agent 2 (Job Posting Fetch)
   ↓
Agent 3 (Dedup + Filter)
   ↓
Agent 4 (CR Culture Intel)
   ↓
   CP0 (conditional human checkpoint)
   ↓
Agent 5 (Signal Classification)
   ↓
   CP1 (human review of signals)
   ↓
Agent 6 (Markdown Output) ← planned M3
```

**State contract:** All agents read and write `OSINTPipelineState` — a Pydantic v2 model that defines the inter-agent boundary. Schema-first by design.

**Stack:**

- Python 3.14
- Anthropic SDK (Claude Haiku 4.5 for extraction, Sonnet 4.5 for intel)
- Pydantic v2 for inter-agent contracts and structured outputs
- Firecrawl + Playwright for web data
- SQLite + JSON for state persistence

---

## Run It Yourself

```bash
# Clone
git clone https://github.com/ricardhm/osint-research-agent
cd osint-research-agent

# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Add your ANTHROPIC_API_KEY

# Run pipeline on a target company
python main.py --company "Akamai" --location "Costa Rica"
```

---

## Repository Structure

```
osint-research-agent/
├── agents/
│   ├── agent_1_url_discovery.py
│   ├── agent_2_posting_fetch.py
│   ├── agent_3_dedup_filter.py
│   ├── agent_4_culture_intel.py
│   ├── agent_5_signals.py
│   └── agent_6_output.py
├── models.py                          # OSINTPipelineState, Pydantic schemas
├── main.py                            # Orchestrator
├── outputs/
│   └── akamai_inside_scoop.json       # Agent 5 output
├── manual_analyses/
│   ├── template.md
│   └── akamai_cr.md                   # Human vs-agent comparison — Akamai CR
└── docs/
    ├── adr/                           # Architecture Decision Records (M4)
    └── post_mortems/                  # Failure-mode catalog from M1
```

---

## Milestone Roadmap

| Milestone | Status | Output |
|---|---|---|
| M1 — Pipeline foundation | ✅ Shipped | Agents 1–3 + post-mortem series |
| M2 — Signals MVP | ✅ Shipped | Agent 5 + Akamai CR comparison (this README) |
| M2.5 — Lumenalta + Workday CR | Next | Two more human-vs-agent comparisons |
| M3 — Pipeline-generated analysis | Planned | First end-to-end output on a company I haven't analyzed |
| M4 — Production hardening | Planned | Ragas eval, Langfuse observability, LangGraph migration |

---

## Known Gaps (Documented, Not Hidden)

Every gap below ships an artifact. The artifact is the deliverable, not the code that closes the gap. Each one is published as a standalone post or design doc — the gap-closing produces the writing, not the other way around.

### Engine-level gaps (M3 scope)

- **Agent 5 ambiguous-cue bloat.** Four variants of "single posting = backfill?". Needs prompt refinement to consolidate.
- **Agent 5 `career_ceiling` over-escalation.** Enum mapping logic needs a calibration pass.
- **Agent 2 Pydantic validation errors** on LinkedIn and Indeed CR sources. Workaround in place; root-cause fix deferred to M3.
- **`--location` flag not yet wired.** Pipeline is currently Costa Rica–only. Multi-market support requires parameterizing Agent 1 URL generation and Agent 2 routing.

### Production-hardening gaps (M4 scope) — each ships an artifact

| Gap | Planned Artifact(s) | Status |
|---|---|---|
| **Evaluation framework** | Golden Dataset Construction post + ADR comparing Ragas / Promptfoo / LangSmith Eval | Backlog |
| **Cost observability** | "Anatomy of a 6-Agent Pipeline Cost" post + Model Routing Decision Matrix | Backlog |
| **Production observability** | Pre-mortem: "How My First Production Incident Will Fail" + Trace Schema design doc | Backlog |
| **LangGraph migration** | Contrarian post: "I built a multi-agent pipeline without LangGraph" + Agent 5 ported, side-by-side diff | Backlog |

### Conscious gap (M5+ scope)

| Gap | Planned Artifact(s) | Status |
|---|---|---|
| **Multi-tenancy and serving patterns** | "OSINT Engine as a Service" design doc + extended failure-mode catalog for failure modes at scale | Backlog, deliberate |

---

These are public roadmap items, not surprises. Each backlog item is scoped to a 2–6 hour deliverable. Sequencing is paced to avoid cannibalizing M2.5 and M2.6 (Lumenalta and Workday CR comparisons) and core operating commitments.

The discipline is to ship the *thinking about the gap* before the code that closes it. ADRs, pre-mortems, and design docs are first-class artifacts here, not afterthoughts.

---

## Why This Project Exists

This pipeline exists to make my engineering judgment legible at Staff+ level without leaning on credentials.

The starting point was [Nate B. Jones'](https://www.linkedin.com/in/natebjones/) "Inside Scoop for Job Seekers" framework — a manual prompt for extracting structured employer signals from job postings, published on his Substack for paid members. The framework is sharp: four signal categories, a receipts table with confidence scoring, a clear output format. The question that drove this project was simple: *what happens when you stop running this prompt manually and build the pipeline that runs it for you?*

Every milestone ships an artifact: working code, a failure-mode catalog, or a comparison like this one. The point is not to claim the agent is better than a human. The point is to document — honestly, with evidence — what production-grade agentic systems actually look like, where they fail, and where they help.

If you're hiring for production agentic work, the post-mortems, the schemas, and the comparison tables are the résumé.

---

**Contact:** https://www.linkedin.com/in/ricardohm/
**M2 post:** [Human vs. Agent on Akamai CR](https://www.linkedin.com/posts/ricardohm_agenticai-buildinpublic-productionai-share-7476053294382129152-c6rZ)
**Built with:** Claude Haiku/Sonnet 4.5, Pydantic v2, and a strict no-peek protocol between human and agent.
