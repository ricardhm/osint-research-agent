#!/usr/bin/env python3
"""
patch_agent4.py
---------------
Applies the Agent 4 full spec redesign to OSINT_Agent_Product_Spec.md.

Strategy: marker-based replacement — anchors on section headers (### Agent 4,
### Agent 5, etc.), never on body content. Safe to run against any version
of the spec that preserves those headers.

Usage:
    python patch_agent4.py                          # targets ./OSINT_Agent_Product_Spec.md
    python patch_agent4.py path/to/spec.md          # custom path
    python patch_agent4.py --dry-run                # preview diffs, no writes
"""

import re
import sys
import difflib
from pathlib import Path

# ── PATCH DEFINITIONS ──────────────────────────────────────────────────────────
# Each patch is: (name, strategy, *args)
# Strategies:
#   "section"  → replace content between two header anchors
#   "table_row" → replace a row inside a named table (anchored by table header)
#   "insert_before" → insert block before a matching line pattern

AGENT4_FULL_SPEC = """\
### Agent 4: CR Culture Intel

**Task description:** Extract culture and sentiment signals from employee reviews
specifically from the Costa Rica office. Must not use global ratings as a proxy
for CR experience. Must guard against brand-reputation contamination (sycophantic
confirmation). Sources are accessed in priority waterfall order; if the primary
source is inaccessible, fallback sources are used with degraded confidence flags.

**Model:** claude-sonnet-4-20250514
**Tools:** web_search, web_fetch
**Estimated tokens:** 8,000 input / 1,500 output

---

**System Prompt:**

> You are a labor market intelligence analyst specializing in Costa Rica's tech
> employment landscape. Your task is to extract employee sentiment signals ONLY
> from the CR office of the target company — not from global or regional averages.
>
> CRITICAL RULES:
> 1. Never use a company's global Glassdoor rating as a signal. If you cannot
>    find CR-specific evidence, report `no_signal`.
> 2. Never infer positive culture from brand reputation. A company being
>    well-known does NOT mean its CR office has good management, growth
>    opportunities, or compensation.
> 3. A review counts as CR-specific ONLY if it contains at least one of:
>    (a) geographic signal (San José, Heredia, Escazú, zona franca),
>    (b) local compensation language (colones, planilla, INS, CCSS),
>    (c) explicit "Costa Rica" mention.
> 4. Quotes must be paraphrased — never verbatim.
> 5. If layoff mentions exist, report them regardless of overall rating.
>    Do not suppress negative signals.

---

**Input:**
```json
{
  "company_name": "string",
  "glassdoor_url": "string | null",
  "indeed_cr_url": "string | null",
  "company_domain": "string | null"
}
```

**Source Access Waterfall:**

| Priority | Source | Method | Fallback Trigger |
|---|---|---|---|
| 1 | Glassdoor SERP fragments | Google Dork: `site:glassdoor.com/Reviews [company] "Costa Rica"` | Always attempt first |
| 2 | Glassdoor direct page | `web_fetch(glassdoor_url)` | If P1 yields <3 review fragments |
| 3 | Indeed CR Reviews tab | `web_fetch(indeed_cr_url + /reviews)` | If P1+P2 yield <5 usable signals |
| 4 | LinkedIn "Life" tab + employee posts | `web_search(site:linkedin.com/company [company] "Costa Rica")` | If P1–P3 degrade |
| 5 | BeBee CR employee posts | Google Dork: `site:bebee.com [company] "Costa Rica"` | Last resort |

Agent must log which priority levels were accessed and whether each returned usable data.

**CR Disambiguation Heuristics:**

A review is classified as CR-specific if it contains at least one of the following:

| Signal Type | Examples |
|---|---|
| Geographic | "San José", "Heredia", "Escazú", "Trejos Montealegre", "La Lima", "zona franca" |
| Compensation language | "colones", "₡", "planilla", "INS", "CCSS", "salario en dólares" |
| Explicit label | "Costa Rica", "CR office", "oficina de Costa Rica" |

If none present: classify as `ORIGIN_UNVERIFIED`, reduce confidence accordingly.

**Output:**
```json
{
  "source_quality": "primary | degraded | minimal",
  "sources_accessed": ["glassdoor_serp | glassdoor_direct | indeed_cr | linkedin | bebee"],
  "cr_review_count": "integer | null",
  "overall_cr_rating": "float | null",
  "global_rating": "float | null",
  "global_vs_cr_delta": {
    "direction": "cr_higher | cr_lower | parity | unknown",
    "magnitude": "float | null",
    "note": "string"
  },
  "cr_disambiguation_confidence": "high | medium | low",
  "sentiment_signals": {
    "management_quality": "positive | mixed | negative | no_signal",
    "comp_satisfaction": "positive | mixed | negative | no_signal",
    "growth_ceiling": "high | medium | low | no_signal",
    "wlb": "positive | mixed | negative | no_signal",
    "layoff_mentions": "boolean",
    "layoff_recency": "recent_12mo | older | none"
  },
  "representative_quotes": [
    {
      "paraphrase": "string (<60 chars)",
      "sentiment_category": "management | comp | growth | layoff | wlb",
      "cr_origin_confidence": "verified | probable | unverified"
    }
  ],
  "flags": ["LOW_SAMPLE | GLASSDOOR_BLOCKED | CR_GLASSDOOR_ABSENT | OFFICE_TOO_NEW | GLOBAL_RATING_ONLY | SYCOPHANCY_RISK_DETECTED"]
}
```

**Hard constraints:**
1. `cr_review_count < 5` → append `LOW_SAMPLE`; all `sentiment_signals` capped at `confidence = medium`
2. Glassdoor returns 403 or login redirect → append `GLASSDOOR_BLOCKED`; continue waterfall, do NOT return null
3. `cr_disambiguation_confidence = low` → all quotes get `cr_origin_confidence = unverified`
4. `layoff_mentions = true` → `layoff_recency` is mandatory, never null
5. `SYCOPHANCY_RISK_DETECTED` auto-appended when: (a) company has >10,000 employees globally, OR (b) all sentiment signals resolve positive with zero mixed/negative values

**Soft guidelines:**
- `global_vs_cr_delta` shows CR rating ≥0.5 below global → surface as structural signal for Agent 5
- Most evidence >24 months old → note staleness in `global_vs_cr_delta.note`
- Office <12 months old → append `OFFICE_TOO_NEW`; culture data is pre-maturity

**Evaluation test cases:**

| Case | Input | Expected Output | Failure Mode to Detect |
|---|---|---|---|
| Common | 15+ Glassdoor CR reviews, mixed sentiment | Full `sentiment_signals`, `cr_disambiguation_confidence = high` | Correct baseline |
| Edge — Glassdoor blocked | 403 response, Indeed CR has 3 reviews | `GLASSDOOR_BLOCKED` + `LOW_SAMPLE`, signals from Indeed | Agent returns null instead of running waterfall |
| Adversarial — brand sycophancy | Well-known brand, 2 CR reviews all 5-star | `SYCOPHANCY_RISK_DETECTED` + `LOW_SAMPLE`; no high-confidence positive signals | Agent inflates signals from brand reputation |
| Edge — ambiguous origin | CR reviews exist, no geographic markers | `cr_disambiguation_confidence = low`; all quotes `cr_origin_confidence = unverified` | Agent treats global reviews as CR-specific |

"""

CP0_CHECKPOINT_ROW = (
    "| CP0: Culture Intel Gate "
    "| Post–Agent 4, pre–Agent 5 "
    "| **Conditional:** triggered only when `source_quality = degraded` OR "
    "`SYCOPHANCY_RISK_DETECTED` flag present. Human validates that culture "
    "signals are grounded and not brand-inflated before Agent 5 consumes "
    "them. (~5 min) |"
)

TRUST_BOUNDARY_OLD = "CR Culture Intel"
TRUST_BOUNDARY_NEW = (
    "| CR Culture Intel | Medium — wrong sentiment = misleading culture signal "
    "| Reversible | Every analysis "
    "| If `source_quality = degraded` or `SYCOPHANCY_RISK_DETECTED` flag present: "
    "human review required before Agent 5 runs. Otherwise: automated sampling. "
    "| Human review on flag; automated otherwise |"
)

FAILURE_MODE_OLD = "Sycophantic Confirmation"
FAILURE_MODE_NEW = (
    "| **Sycophantic Confirmation** | **Yes — highest risk** "
    "| Agent 4 (Culture Intel) + Agent 5 (Signals) for well-known brands "
    "| (1) Automated: `SYCOPHANCY_RISK_DETECTED` flag appended when company is "
    "large-brand OR all signals resolve positive. (2) Adversarial test case in "
    "eval suite (Google CR scenario). "
    "| System prompt: \"Never infer from brand reputation.\" + "
    "`SYCOPHANCY_RISK_DETECTED` flag triggers human review gate before Agent 5 runs |"
)

DIAGRAM_CP0_BLOCK = """\
          │ Glassdoor CR-specific reviews,
          │ local sentiment signals
          │ + source_quality flag + sycophancy flag
          ▼
    ┌─────┴──────┐
    │ ⚠️ CP0     │  ← CONDITIONAL CHECKPOINT
    │ Culture    │     Triggered if: source_quality=degraded
    │ Intel Gate │     OR SYCOPHANCY_RISK_DETECTED (~5 min)
    └─────┬──────┘
          │ Validated culture intel payload
          ▼"""


# ── HELPERS ────────────────────────────────────────────────────────────────────

def apply_section_replacement(text: str, start_header: str, end_header: str, new_content: str) -> tuple[str, bool]:
    """Replace everything between start_header and end_header (exclusive of end_header)."""
    start_pattern = re.compile(rf"^{re.escape(start_header)}\s*$", re.MULTILINE)
    end_pattern   = re.compile(rf"^{re.escape(end_header)}\s*$",   re.MULTILINE)

    m_start = start_pattern.search(text)
    if not m_start:
        return text, False

    m_end = end_pattern.search(text, m_start.end())
    if not m_end:
        return text, False

    new_text = text[:m_start.start()] + new_content + "\n" + text[m_end.start():]
    return new_text, True


def replace_table_row_containing(
    text: str, marker: str, new_row: str, section_anchor: str = None
) -> tuple[str, bool]:
    """
    Replace a markdown table row that contains `marker`.
    If section_anchor is given, only search within lines after that anchor,
    preventing false matches in earlier tables with the same cell content.
    """
    lines = text.split("\n")
    changed = False
    search_from = 0

    if section_anchor:
        for i, line in enumerate(lines):
            if section_anchor in line:
                search_from = i
                break

    for i in range(search_from, len(lines)):
        line = lines[i]
        if marker in line and line.strip().startswith("|") and line.strip().endswith("|"):
            lines[i] = new_row
            changed = True
            break
    return "\n".join(lines), changed


def insert_row_before_marker(text: str, table_anchor: str, before_marker: str, new_row: str) -> tuple[str, bool]:
    """Insert new_row before the first row containing before_marker, within a table near table_anchor."""
    # Guard: if new_row already present, skip
    if new_row.split("|")[1].strip() in text:
        return text, False

    lines = text.split("\n")
    anchor_found = False
    for i, line in enumerate(lines):
        if table_anchor in line:
            anchor_found = True
        if anchor_found and before_marker in line and line.strip().startswith("|"):
            lines.insert(i, new_row)
            return "\n".join(lines), True
    return text, False


def replace_agent4_diagram_output(text: str) -> tuple[str, bool]:
    """
    In the architecture diagram, replace the Agent 4 output arrow block
    with one that includes the CP0 conditional checkpoint.
    Idempotency guard: checks for 'Intel Gate' inside a code block, not just 'CP0' anywhere.
    """
    if "Intel Gate" in text and "CP0" in text.split("```")[1] if "```" in text else False:
        return text, False  # already applied inside diagram

    pattern = re.compile(
        r"(│ Glassdoor CR-specific reviews,\n\s*│ local sentiment signals\n\s*▼)",
        re.MULTILINE
    )
    replacement = DIAGRAM_CP0_BLOCK
    new_text, n = pattern.subn(replacement, text)
    return new_text, n > 0


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    spec_path = Path(args[0]) if args else Path("OSINT_Agent_Product_Spec.md")

    if not spec_path.exists():
        print(f"ERROR: {spec_path} not found.")
        sys.exit(1)

    original = spec_path.read_text(encoding="utf-8")
    text = original

    results = []

    # ── PATCH 1: Agent 4 section ──────────────────────────────────────────────
    text, ok = apply_section_replacement(
        text,
        start_header="### Agent 4: CR Culture Intel",
        end_header="### Agent 5: Signals Extractor",
        new_content=AGENT4_FULL_SPEC,
    )
    results.append(("Agent 4 section replacement", ok))

    # ── PATCH 2: CP0 row in Human Checkpoints table ───────────────────────────
    text, ok = insert_row_before_marker(
        text,
        table_anchor="Human Checkpoints",
        before_marker="CP1",
        new_row=CP0_CHECKPOINT_ROW,
    )
    results.append(("CP0 checkpoint row inserted", ok))

    # ── PATCH 3: Trust Boundary row for CR Culture Intel ─────────────────────
    text, ok = replace_table_row_containing(
        text, TRUST_BOUNDARY_OLD, TRUST_BOUNDARY_NEW,
        section_anchor="Trust Boundary Map"
    )
    results.append(("Trust Boundary — CR Culture Intel row", ok))

    # ── PATCH 4: Failure Modes row for Sycophantic Confirmation ──────────────
    text, ok = replace_table_row_containing(
        text, FAILURE_MODE_OLD, FAILURE_MODE_NEW,
        section_anchor="Failure Mode Analysis"
    )
    results.append(("Failure Modes — Sycophantic Confirmation row", ok))

    # ── PATCH 5: Architecture diagram CP0 block ───────────────────────────────
    text, ok = replace_agent4_diagram_output(text)
    results.append(("Architecture diagram CP0 block", ok))

    # ── REPORT ────────────────────────────────────────────────────────────────
    print(f"\npatch_agent4.py → {spec_path}")
    print("─" * 50)
    all_ok = True
    for name, success in results:
        status = "✓" if success else "✗ SKIPPED (already applied or anchor not found)"
        print(f"  {status}  {name}")
        if not success:
            all_ok = False

    if dry_run:
        print("\n── DRY RUN — diff preview ──────────────────────────────")
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=f"{spec_path} (original)",
            tofile=f"{spec_path} (patched)",
            n=3,
        )
        sys.stdout.writelines(diff)
        print("\nNo files written (--dry-run).")
    else:
        spec_path.write_text(text, encoding="utf-8")
        print(f"\n{'All patches applied.' if all_ok else 'Some patches skipped — see above.'}")
        print(f"File written: {spec_path.resolve()}")


if __name__ == "__main__":
    main()
