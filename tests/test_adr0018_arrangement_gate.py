"""ADR 0018 §5: the arrangement works — what is missing is somewhere to keep the decision.

The ADR treats `view sets x scales x sheets x arrangements` as ONE constrained choice.
`LayoutCandidate` models all four; `_layout_geometry` now implements two of the
arrangements. This module is the measurement that says why the fourth dimension is not yet
varied in production, because the reason is not the obvious one.

`stacked-iso` puts the isometric in the title block's column instead of giving it a column
of its own, which wins back that column's width. It is not a stub and it is not harmful:
the `chamfered` part moves from A3 to A4 under it and loses NOTHING — no dropped dimension,
no new lint code. That is precisely ADR 0018 §5's "at that scale, the smallest standard
sheet".

The blocker is that the arrangement has nowhere to live between the stage that decides it
and the stages that apply it. `_layout_geometry` is the single layout authority, but its
callers hand it different arguments — scale selection knows only ESTIMATED strip depths,
placement and repack know MEASURED ones. Resolving `auto` inside the shared function
therefore does not make the stages agree; it lets them disagree with more steps. The dense
plate is that disagreement: resolving per call site loses two location requirements on a
sheet whose size does not change. Note what is and is not claimed — that a per-call-site
resolution is lossy is measured; WHY it is lossy is not isolated, and at the estimate the
two arrangements barely differ for that part.

Hence `arrangement="columns"` is the default and `"auto"` is reachable only by asking.
"""

import itertools

import pytest
from build123d import Axis, Box, Cylinder, Pos, chamfer

import draftwright.analysis as analysis_mod
import draftwright.builder as builder_mod
import draftwright.compose as compose_mod
from draftwright import build_drawing
from draftwright.compose import _layout_geometry, choose_scale

A4 = (297.0, 210.0, 120.0)
A3 = (420.0, 297.0, 150.0)


def _chamfered():
    """The `chamfered` golden's part — the corpus's smallest arrangement-sensitive case."""
    plate = Box(90, 60, 20)
    edge = plate.edges().filter_by(Axis.Z).sort_by(lambda e: e.center().X + e.center().Y)[-1]
    return chamfer(edge, 12)


def _dense_plate():
    """`test_make_drawing`'s crowded plate: 24 Z-holes in 5 diameter groups."""
    part = Box(70, 50, 12)
    for i, (gx, gy) in enumerate(itertools.product([-25, -15, -5, 5, 15, 25], [-15, -5, 5, 15])):
        part -= Pos(gx, gy, 0) * Cylinder(1.0 + (i % 5) * 0.4, 20)
    return part


def _geom(arrangement, page=A4, size=(90.0, 60.0, 20.0), n_steps=0):
    page_w, page_h, tb_w = page
    return _layout_geometry(
        *size, 1.0, page_w, page_h, tb_w, None, n_steps, arrangement=arrangement
    )


def _resolve_arrangement_per_call_site(monkeypatch):
    """Resolve the arrangement per call site, as production would if it selected on it.

    Applied to all three importers — `compose` (scale selection via `_fits`), `analysis`
    (placement) and `builder` (repack) each hold their own reference. Called INSIDE a test
    rather than from a fixture so the unpatched baseline can be built first.
    """
    original = compose_mod._layout_geometry

    def resolving(*args, **kwargs):
        kwargs["arrangement"] = "auto"
        return original(*args, **kwargs)

    for module in (compose_mod, analysis_mod, builder_mod):
        monkeypatch.setattr(module, "_layout_geometry", resolving)


def _lint_codes(drawing):
    return {issue.code for issue in drawing.lint()}


class TestTheAlternativeArrangementIsRealGeometry:
    def test_columns_does_not_fit_a4_and_stacked_iso_does(self):
        # The precondition the whole module rests on: a case where the two disagree.
        # Without it everything below would pass vacuously.
        assert _geom("columns").auto_fits is False
        assert _geom("stacked-iso").auto_fits is True

    def test_the_saving_is_exactly_the_reclaimed_iso_column(self):
        # The mechanism, not merely the verdict.
        columns, stacked = _geom("columns"), _geom("stacked-iso")
        assert stacked.iso_natural > 0.0
        assert columns.auto_row_w - stacked.auto_row_w == pytest.approx(columns.iso_natural)

    def test_the_iso_still_gets_a_real_gap_to_live_in(self):
        # Reclaiming the width would be worthless if the iso then had nowhere to go: the
        # largest-empty-rect search must return a genuine rectangle, not the whole-drawable
        # fallback that overlaps the views.
        assert _geom("stacked-iso").iso_fits is True

    def test_the_resolved_arrangement_is_reported_not_guessed(self):
        assert _geom("columns").arrangement == "columns"
        assert _geom("auto").arrangement == "stacked-iso"


class TestTheArrangementIsNotTheProblem:
    """The sheet it wins is a real win, which is why the blocker is worth naming precisely."""

    def test_the_shipped_default_puts_the_chamfered_part_on_a3(self):
        _, page_w, page_h, _ = choose_scale(90.0, 60.0, 20.0)
        assert (page_w, page_h) == A3[:2]

    def test_resolving_the_arrangement_wins_a4_and_costs_nothing(self, monkeypatch):
        baseline = _lint_codes(build_drawing(_chamfered()))
        _resolve_arrangement_per_call_site(monkeypatch)
        drawing = build_drawing(_chamfered())
        assert (drawing.page_w, drawing.page_h) == A4[:2]
        assert _lint_codes(drawing) == baseline, (
            "the smaller sheet must lose no requirement — if it does, the cost of varying "
            "arrangement is the sheet size and not the carried decision"
        )


class TestTheDecisionHasNowhereToLive:
    """Selection and placement resolve `auto` from different inputs, so they disagree."""

    def test_estimated_and_measured_strips_resolve_the_same_sheet_differently(self):
        # Selection sees no measured strips and resolves `columns` for the 3-step corridor
        # at A3 -> it escalates. Placement, seeing the real corridor, would resolve
        # `stacked-iso` at that same A3 and never escalate at all.
        corridor = {"size": (5.0, 90.0, 100.0), "page": A3}
        assert _geom("columns", n_steps=0, **corridor).auto_fits is True
        assert _geom("columns", n_steps=3, **corridor).auto_fits is False
        assert _geom("stacked-iso", n_steps=3, **corridor).auto_fits is True

        _, flat_page, _, _ = choose_scale(5.0, 90.0, 100.0, n_steps=0)
        _, deep_page, _, _ = choose_scale(5.0, 90.0, 100.0, n_steps=3)
        assert deep_page > flat_page, "the shipped default still escalates for the corridor"

    def test_the_disagreement_loses_requirements_on_an_unchanged_sheet(self, monkeypatch):
        # The dense plate is the disagreement made visible. The sheet does NOT change, so
        # nothing here can be blamed on cramming a part onto a smaller page. Centring the
        # ortho views rather than packing them left does not change this outcome either —
        # mutating `x_offset` leaves every assertion in this module passing — so the loss is
        # a property of resolving per call site, not of the stacked layout.
        baseline = build_drawing(_dense_plate())
        _resolve_arrangement_per_call_site(monkeypatch)
        drawing = build_drawing(_dense_plate())
        assert (drawing.page_w, drawing.page_h) == (baseline.page_w, baseline.page_h)
        assert _lint_codes(drawing) - _lint_codes(baseline) == {
            "location_ref_dropped",
            "feature_not_located",
        }
