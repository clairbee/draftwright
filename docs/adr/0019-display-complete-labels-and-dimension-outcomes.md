# ADR 0019 — Display-complete labels and a dimension-outcome ledger: finishing the compiled-plan boundary

- **Status:** Proposed
- **Date:** 2026-08-20
- **Deciders:** Paul Fremantle (pzfreo)
- **Supersedes:** ADR 0016 Amendment 6 (the rule stands; its enforcement mechanism is replaced).
  Amends ADR 0016 Amendment 3 (per-mark identity) and narrows Amendment 1's remaining
  renderer-side composition to zero.

## Context — ten review rounds are the evidence

Epic #1215/#1216 (PRs #1223–#1235; the review trail is PR #1235's body, §§1–6) fixed the same two defect classes ten review rounds in a
row, each round finding a new instance created or missed by the previous round's fix:

1. **An authored tolerance approved by the compiler and absent from the ink.** Found one site
   at a time: envelope extents, the height ladder, the turned-step chain, two public `Drawing`
   verbs, the deferred corridor route, prismatic rungs, the detail redraw, the short-rise
   escape, step shoulders, pattern pitch, compound-callout recess terms, both hole tables, the
   grid pitch, and the fillet/flat collapses. Two of the *fixes* shipped new instances of the
   class they fixed: a `depth_tol` reader with no writer (#1234), then a location-tolerance
   reader with no writer (#1235 r9) — dead code in the shape of a fix.

2. **An approved dimension that is not drawn at all, silently.** The envelope extents' no-op
   `on_drop`; the legibility gate's uncounted skip. The reporting retrofitted for these was
   itself wrong three rounds running: it gated the build (`placement_unsatisfiable` is a
   required scale drop, so a lint code refused to build drawings that had always built), the
   guard's join failed open (any absence-shaped code stood in for the real one), and the
   retraction collapsed five rungs into one id (one drawn rung withdrew a five-rung report).

This is a replay of the pre-Amendment-1 history that ADR 0016 itself documents: eight rounds
on #921 found renderers individually ignoring suppression, and the conclusion was *"fixing
them individually produced four mechanisms for saying the same thing… the signature of a
missing boundary, not of missing tests."* The boundary Amendment 1 built is **half-built**:

- `ApprovedDimension.value_text` crosses the boundary as finished text — but its own docstring
  says *"Group renderers add semantic syntax such as ø, THRU and tolerance text."* The
  tolerance crosses as a raw number every render path must remember to format
  (`_core._tol_suffix`) and append. Composition is opt-in, so every new path — a table cell, a
  redraw, an escape branch, an `N×` collapse — drops the requirement *by default*.
- Whether a collapsed `N×` mark may state a band at all, and how a band rounds at the drawn
  precision, are content decisions currently made ad hoc at each renderer. Three sites got it
  wrong three different ways (pitch claimed a band over jittered gaps; fillets took
  "first-authored wins"; `±0.02` renders as the false and unmanufacturable `±0.0`).
- "Approved but never drawn" has no ledger. The engine already has the correct pattern —
  requirement outcomes (`placed / suppressed / dropped / missing / unverifiable`) computed at
  one seam for holes, slots, channels and flats, which completeness reads *instead of* lint —
  and dimensions do not participate in it.
- Underneath both: `DimensionId` is per-parameter, not per-mark (Amdt 3), so every ladder rung
  shares one id and no claim-based accounting over ids can distinguish "all drawn" from "one
  drawn".

## Decision

### 1. The plan carries display-complete label text; renderers render, never compose

`ApprovedDimension` gains `display_text`: the complete string the mark states, tolerance
suffix, fit-class code and collapse wording included. `value_text` remains for renderers that
legitimately need the bare number (footprint estimation, semantic assembly of compound
callouts **from display-complete terms** — a hole callout's `depth`, `cbore_dia` etc. each
arrive as finished text). The existing `rendered_label` ("a complete compiler-owned label for
correlated marks") is the precedent and folds into this as the general case.

Consequences inside the compiler:

- `_tol_suffix` moves below the model rank (next to `_geometry._fmt`, the shared bottom-leaf
  formatter, taking `FitClass` with it or importing from `fits`, also a leaf). The drawn
  precision becomes an explicit compile input — which is where the `±0.02 → "±0.0"` honesty
  defect gets fixed once: a band that rounds to zero at the drawn precision is **withheld and
  diagnosed**, not printed.
- Collapse honesty becomes one compiler rule with one implementation: an `N×` mark states a
  band only when every member states the same band at the drawn precision (the rule
  `_pitch_text`, the ladder representative, and `_collapsed_tolerance` currently implement
  three times); a withheld band is an `Omission`-style diagnostic, not a silent drop.
- The label-provenance ratchet extends: `_tol_suffix` (old name) becomes unimportable from
  `annotations/`, `drawing.py` and `compose.py`; grep-level enforcement joins
  `test_label_provenance`.

The general guard (`test_issue_1215_no_approved_tolerance_is_dropped`) collapses from
predicate-engineering — three of its predicates reported green over live drops before the
fourth was exact — to string equality: *the claiming annotation's rendered text contains the
plan's `display_text` for each claimed mark, verbatim.*

### 2. Dimension outcomes reconcile at one seam

A single end-of-build reconciliation joins the compiled plan against the registry (the ADR
0010 claim seam) and produces an outcome per approved mark: `placed`, `dropped` (a pass
reported why — strip full, occupants named), or `withheld` (the compiler or a collapse rule
declined, diagnosed). It runs on **both** routes (`_auto_annotate` and `finalize()`), so
live/declared parity holds by construction rather than by remembering to call a helper twice.

Per-pass reporting keeps exactly one job: the *reason* (only the pass knows which strip was
full and who filled it). Whether an absence exists is computed centrally — which deletes the
retraction pass, the withholding-code join, and the max-count workaround wholesale. The
outcome ledger feeds completeness the way hole/slot/channel/flat requirement outcomes already
do; `passed`/`geometry_issues` read the ledger, not a code list.

The severity question dissolves rather than being answered: a missing principal extent is a
`dropped` outcome on a mandatory mark, which is what gates `passed` — no lint code has to be
simultaneously "loud enough to fail a drawing" and "quiet enough not to abort a build"
(`_is_required_scale_drop` keys on outcome stage, not on a name).

### 3. Per-mark identity

Ladder rungs (and any collapsed set that renders one mark per member) get a discriminator on
their `DimensionId` — `step_height.length.0`, `.1`, … — amending Amendment 3: the parameter id
remains the canonical *addressing* spelling for authored intent, and the discriminator exists
only where one parameter produces several marks. Addressing is unchanged (an author still
writes `dimension(step, "length", role="step_height")`); accounting stops being blind.

## What this deletes

`retract_resolved_withholdings` + `_approved_per_measurement`, the `_WITHHOLDING_CODES`
plumbing, `_absence_reported`/`_ABSENCE_CODES` in the guard, the three collapse-honesty
implementations, every `_tol_suffix` call outside the compiler (≈20 sites), and the guard's
predicate machinery. Net negative diff is the success criterion, per-site guards replaced by
two boundary guards.

## Consequences / risks

- `compile_dimensions` gains the drawn precision as an input; callers that compile without a
  draft (`Drawing.model()`-adjacent probes) pass the build's. One more argument, one fewer
  distributed assumption.
- Compound callouts (`hc_*`) remain assembled render-side from per-term display text — full
  string assembly in the compiler would move `⌴`/`↧` glyph policy down a rank for no gain; the
  boundary is "no term's text is composed render-side", not "one string per annotation".
- The helpers seam (#449: `Leader`/`HoleCallout` take no `tolerance=`) is unchanged — labels
  were already the only route; this ADR moves where they are *built*, not how they are drawn.
- Migration is per-renderer and each step is small: swap `label=...` composition for
  `display_text`, delete the local suffix call. The guard stays green throughout because
  equality-to-plan is implied by the current containment predicate.

## Evidence-gated work plan

1. **`display_text` + precision input + zero-band withholding** — gate: the r10 F7 case
   (`±0.02` at 1 dp) is withheld-and-diagnosed, not printed; label-provenance forbids the old
   formatter outside `model/`.
2. **Migrate renderers** (mechanical, several PRs) — gate: `annotations/`, `drawing.py`,
   `compose.py` import no suffix formatter; guard reduces to equality.
3. **Outcome ledger + per-mark ids** — gate: the partial-ladder case (two rungs, one drawn)
   yields one `placed` + one `dropped` outcome on both routes; the retraction pass and
   withholding joins are deleted; `passed` reads the ledger.
