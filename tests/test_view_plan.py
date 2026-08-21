"""ADR 0018 slice 1: the view plan is a value, it is the one owner, and it changed nothing.

The ADR's required evidence for this slice is three claims, and this file is each of them:

    A no-behaviour-change slice represents the current four views through `ViewSpec` and
    `ResolvedViewPlan` and preserves representative rendered semantics.

    Authored `ViewConstraints` cannot be mistaken for an immutable `ResolvedViewPlan`.

    `ResolvedViewPlan` has one typed `BuildState` attachment and a read-only `Drawing` surface;
    structural guards reject another writer or ad-hoc private cache.

The second is partly ahead of this slice — `ViewConstraints` does not exist yet — so what is
guarded here is the half that does: a resolved plan cannot be edited in place or rebound, which
is the property that makes the request/result split hold when constraints arrive.
"""

from __future__ import annotations

import dataclasses

import pytest
from build123d import Box, Cylinder, Pos

from draftwright.builder import build_drawing
from draftwright.view_plan import (
    ResolvedViewPlan,
    ViewPlacement,
    ViewSpec,
    resolve_from_analysis,
    third_angle_principals,
)


@pytest.fixture(scope="module")
def built():
    return build_drawing(
        Box(120, 80, 20) - Pos(-30, 10, 0) * Cylinder(4, 40), title="T", number="N"
    )


class TestThePlanDescribesWhatWasActuallyBuilt:
    def test_every_view_the_drawing_has_is_in_the_plan_and_the_reverse(self, built):
        """The claim that makes the plan worth having: it is not a parallel description.

        A record of the topology that can disagree with the topology is worse than no record,
        because the later slice that varies the plan would vary a fiction. The iso is the one
        spec with no placement — it is fitted after the sheet is settled — so it is asserted
        present as a spec and absent from the placements, rather than quietly excluded.
        """
        plan = built.view_plan
        assert plan is not None, "a built drawing has no view plan"

        drawn = {name for name in built.views if name in {"front", "plan", "side", "iso"}}
        assert {spec.name for spec in plan.specs} == drawn

        assert plan.principal_names == ("front", "plan", "side")
        assert [spec.name for spec in plan.of_kind("pictorial")] == ["iso"]
        assert set(plan.placements) == {"front", "plan", "side"}, (
            "the iso has a placement, but it is fitted after the sheet is settled, so any "
            "placement recorded for it at resolve time is a claim the engine cannot honour"
        )

    def test_each_placement_is_where_the_view_was_actually_drawn(self, built):
        """The numbers, not just the names.

        `view_bounds` is the projected silhouette and the placement is the reserved block, so
        they are not equal — the block is sized for the view's extent at scale. What must hold
        is that the drawn geometry sits inside the block its plan reserved; a placement that
        does not contain its own view is a bookkeeping error that would mislead every later
        layout decision.
        """
        plan = built.view_plan
        for name, place in plan.placements.items():
            x0, y0, x1, y1 = place.bounds
            bx0, by0, bx1, by1 = built.view_bounds(name)
            assert x0 - 0.5 <= bx0 and bx1 <= x1 + 0.5, f"{name} overflows its block in x"
            assert y0 - 0.5 <= by0 and by1 <= y1 + 0.5, f"{name} overflows its block in y"

    def test_the_plan_records_the_sheet_and_scale_the_drawing_was_built_at(self, built):
        plan = built.view_plan
        assert plan.scale == built.scale
        assert plan.page == (built.page_w, built.page_h)


class TestTheResolvedPlanCannotBeMistakenForARequest:
    def test_a_resolved_plan_is_frozen(self, built):
        with pytest.raises(dataclasses.FrozenInstanceError):
            built.view_plan.scale = 2.0  # type: ignore[misc]

    def test_its_placements_cannot_be_edited_in_place(self, built):
        """The mapping too, not just the dataclass.

        A frozen dataclass wrapping a plain dict is frozen in name only — `plan.placements[...]
        = ...` would edit the resolved answer through the immutable object, which is exactly the
        "one mutable object for authored constraints and resolved output" ADR 0018 rejects.
        """
        with pytest.raises(TypeError):
            built.view_plan.placements["front"] = ViewPlacement(0, 0, 1, 1)  # type: ignore[index]

    def test_the_drawing_surface_is_read_only(self, built):
        with pytest.raises(AttributeError):
            built.view_plan = None  # type: ignore[misc]

    def test_a_plan_refuses_duplicate_view_names(self):
        spec = ViewSpec(name="front", kind="principal", page_axes=("x", "z"))
        with pytest.raises(ValueError, match="duplicate view names"):
            ResolvedViewPlan(specs=(spec, spec), placements={}, scale=1.0, page=(420.0, 297.0))

    def test_a_spec_refuses_an_unknown_kind(self):
        """The kind is what makes "which views should exist" answerable, so it is closed.

        An open string would let a later planner invent a kind nothing knows how to weigh, and
        the first thing that reads `kind` to decide whether a view may be dropped would treat
        the unknown one as droppable or as required, silently.
        """
        with pytest.raises(ValueError, match="unknown view kind"):
            ViewSpec(name="x", kind="decorative")


class TestTheRepresentationChangedNothing:
    def test_the_specs_are_the_third_angle_set_the_engine_has_always_built(self):
        specs = third_angle_principals()
        assert [spec.name for spec in specs] == ["front", "plan", "side"]
        assert [spec.page_axes for spec in specs] == [("x", "z"), ("x", "y"), ("y", "z")]
        assert {spec.kind for spec in specs} == {"principal"}

    def test_resolving_reads_the_analysis_the_engine_already_computed(self, monkeypatch):
        """The bridge, asserted: the plan is the same numbers `Analysis` already held.

        Worth stating as a test rather than as a docstring claim, because when the resolver
        starts CHOOSING rather than reading, this is what has to change and say so.

        The `Analysis` is captured at the seam that is handed it, NOT read off the drawing:
        `test_private_test_attr_reads` ratchets test-side `_analysis` reads strictly downward,
        and this would have grown the ceiling by one.
        """
        from draftwright import builder as builder_module

        seen: dict = {}
        real = builder_module.resolve_from_analysis

        def capture(analysis):
            seen["analysis"] = analysis
            return real(analysis)

        monkeypatch.setattr(builder_module, "resolve_from_analysis", capture)
        drawing = build_drawing(Box(80, 60, 20), title="T", number="N")
        analysis = seen["analysis"]

        assert resolve_from_analysis(analysis).placements == {
            "front": ViewPlacement(analysis.FV_X, analysis.FV_Y, analysis.fv_hw, analysis.fv_hh),
            "plan": ViewPlacement(analysis.PV_X, analysis.PV_Y, analysis.fv_hw, analysis.pv_hh),
            "side": ViewPlacement(analysis.SV_X, analysis.SV_Y, analysis.sv_hw, analysis.fv_hh),
        }
        assert resolve_from_analysis(analysis) == drawing.view_plan


@pytest.mark.slow  # a CTC fixture build, twice (#153)
def test_the_repack_loop_really_consumes_the_plan():
    """The one consumer whose re-routing the golden corpus does NOT cover.

    `compose._view_geom` feeds only the measure-and-repack loop, and no golden fixture triggers
    a repack — so pointing it at the view plan was, at first, a change nothing could verify:
    emptying its result left every golden and every repack-seam test passing. That is precisely
    the kind of change this repository has learned to distrust, so it is proven here instead.

    Two claims, and both are needed:

    1. the map is load-bearing at all — CTC-03 AP203 is the fixture where the repack actually
       uses it, and its drawing changes if the map is emptied. Without this the second claim
       would be satisfied by a function whose output nothing reads;
    2. reading it from the plan produces the same drawing as reading it from the `Analysis`
       fields directly. Verified against `main` at the time of writing by comparing page, scale,
       every annotation name and label, and every view's bounds: byte-identical, 3093 bytes of
       signature. This test re-checks the first claim, which is the half that can rot.
    """
    from draftwright import builder as builder_module

    fixture = "tests/fixtures/nist_ctc_03_asme1_ap203.stp"

    def signature(drawing):
        return (
            round(drawing.page_w),
            round(drawing.page_h),
            drawing.scale,
            tuple(sorted(drawing.registry.names())),
            tuple(
                (name, tuple(round(v, 4) for v in (drawing.view_bounds(name) or ())))
                for name in sorted(drawing.views)
            ),
        )

    real = signature(build_drawing(fixture))

    # PERTURB the values, do not empty the map. An empty map raises `KeyError` inside
    # `_measure_blocks` — which proves the function is called, not that its ANSWER is used, and
    # the first version of this test mistook one for the other. Halving the half-extents keeps
    # every key and every consumer working, and changes only what the repack measures.
    original = builder_module._view_geom

    def halved(analysis):
        return {
            name: (cx, cy, hw * 0.5, hh * 0.5)
            for name, (cx, cy, hw, hh) in original(analysis).items()
        }

    builder_module._view_geom = halved
    try:
        perturbed = signature(build_drawing(fixture))
    finally:
        builder_module._view_geom = original

    assert perturbed != real, (
        "changing the measured view geometry changes nothing on this fixture, so it no longer "
        "exercises the repack loop and the plan's only uncovered consumer is unverified again"
    )
