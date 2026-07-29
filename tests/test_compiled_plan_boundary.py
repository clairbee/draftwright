"""ADR 0016's boundary: a dimensional renderer draws only what the compiler approved.

The rule — *renderers may emit dimensional content only from the compiled plan* — exists
because the previous arrangement made honouring suppression a convention each renderer had
to opt into. Eight adversarial review rounds on #921 found eight that had not. Fixing them
one at a time produced four different mechanisms for saying the same thing and no reason to
believe the ninth renderer would be different.

These tests pin the property rather than the instances:

- the compiler decides WHAT (`TestTheCompilerOwnsContent`);
- the renderer decides WHERE, and cannot reach back for content
  (`TestTheRendererCannotSeeContent`);
- an omission is not a drop, and the two report differently (`TestOmissionIsNotADrop`);
- the migration is real and does not silently stall (`TestTheBoundaryIsLoadBearing`).

`render_height_ladder` is the first slice on purpose: it exercises every hard case at once —
correlated rungs, a geometry-derived overall dimension, spans that must survive projection,
and suppression. If the boundary holds here it will hold for the flatter renderers.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from build123d import Box, Cylinder, Pos

from draftwright import Sheet
from draftwright.annotations.from_model import render_height_ladder
from draftwright.builder import detect_part_model
from draftwright.model.compiled import RenderableDimensionPlan, compile_dimensions


def _staircase():
    return Box(120, 60, 15) + Pos(-20, 0, 15) * Box(80, 60, 15) + Pos(-40, 0, 30) * Box(40, 60, 15)


def _uniform_staircase():
    return (
        Box(90, 60, 10)
        + Pos(0, 0, 10) * Box(75, 60, 10)
        + Pos(0, 0, 20) * Box(60, 60, 10)
        + Pos(0, 0, 30) * Box(45, 60, 10)
    )


class TestTheCompilerOwnsContent:
    def test_the_rung_set_arrives_decided(self):
        plan = compile_dimensions(detect_part_model(_staircase()))
        rungs = plan.ladder("step_height")
        assert rungs is not None
        assert [r.label for r in rungs.rungs] == ["15", "30"]
        assert all(r.span is not None for r in rungs.rungs), "spans travel in PART space"

    def test_a_uniform_staircase_collapses_in_the_compiler(self):
        """`n× rise` is a decision about what the drawing SAYS, so it is made once, before
        any renderer sees the set — not rediscovered beside the legibility gate, which reads
        similarly but is genuinely about the page."""
        rungs = compile_dimensions(detect_part_model(_uniform_staircase())).ladder("step_height")
        assert rungs is not None and rungs.representative
        assert len(rungs.rungs) == 1 and "×" in rungs.rungs[0].label

    def test_the_overall_height_is_an_approved_entry_not_a_bbox_read(self):
        plan = compile_dimensions(detect_part_model(Box(90, 60, 20)))
        overall = plan.ladder("overall_height")
        assert overall is not None and overall.rungs[0].value == pytest.approx(20)

    def test_drawing_state_is_an_input_to_the_compile(self):
        """`include_overall` is the finalize drain's explicit-envelope-height request —
        drawing state, not model state — so it decides membership of the SET rather than
        being applied by the renderer afterwards."""
        model = detect_part_model(Box(90, 60, 20))
        assert compile_dimensions(model, include_overall=False).ladder("overall_height") is None
        assert compile_dimensions(model, include_overall=True).ladder("overall_height") is not None

    def test_a_rotational_od_conveying_the_height_is_settled_once(self):
        """Two rules for this used to live apart — the planner suppressed a Z-turned
        envelope height, the renderer independently suppressed that AND an X/Y rotational
        OD — and neither knew about the other. Both are here now."""
        model = detect_part_model(Cylinder(radius=20, height=40))
        plan = compile_dimensions(model)
        assert plan.ladder("overall_height") is not None  # Z body: the ladder carries it
        reasons = [o.reason for o in plan.diagnostics]
        assert all("rotational OD" not in r for r in reasons)


class TestTheRendererCannotSeeContent:
    def test_the_signature_takes_the_plan_and_the_frame(self):
        """The structural half of the rule. A renderer that cannot name `model` or `a`
        cannot reconstruct a dimension the compiler withheld — the failure mode is removed
        rather than tested for."""
        params = set(inspect.signature(render_height_ladder).parameters)
        assert {"plan", "frame"} <= params
        assert not ({"model", "a"} & params), (
            "a dimensional renderer must not take the PartModel or the Analysis — both "
            "carry the feature inventory and the bounding box it would rebuild content from"
        )

    def test_the_body_never_touches_the_feature_inventory(self):
        """Reads the source rather than trusting the signature: a renderer could still
        reach content through an argument that legitimately carries it."""
        src = inspect.getsource(render_height_ladder)
        tree = ast.parse(src)
        reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
        }
        forbidden = {"features", "bb", "levels", "shoulders", "orientation", "z_size", "base"}
        assert not (reads & forbidden), (
            f"{sorted(reads & forbidden)} is model content — the ladder is drawn from the "
            "compiled plan's approved entries, whose spans carry every coordinate it needs"
        )

    def test_the_layout_frame_carries_no_part_geometry(self):
        from draftwright._core import LayoutFrame

        fields = set(LayoutFrame.__dataclass_fields__)
        assert not (fields & {"part", "bb", "holes", "x_size", "y_size", "z_size", "model"}), (
            "LayoutFrame is the page geometry a renderer may use; part geometry belongs to "
            "the compiler, which is the only place allowed to turn it into a dimension"
        )


class TestOmissionIsNotADrop:
    """Two different "not drawn" meet in this renderer and must stay distinguishable: the
    compiler's omission (never arrived) and the placer's drop (arrived, did not fit)."""

    def test_an_omission_is_reported_through_diagnostics(self):
        model = detect_part_model(Box(90, 60, 20))
        plan = compile_dimensions(model, include_overall=False)
        assert plan.ladder("overall_height") is None
        assert not any(o.authored for o in plan.diagnostics), "no author involved here"

    def test_a_planner_reason_is_not_an_authored_omission(self):
        """`Omission.authored` is the distinction three #921 attempts kept blurring: only an
        author's omission makes an empty result the script's own doing."""
        from draftwright.model.compiled import Omission

        assert Omission(None, "height.length", 1.0, "square footprint").authored is False
        assert Omission(None, "height.length", 1.0, "not in the authored dimension set").authored


class TestTheBoundaryIsLoadBearing:
    def test_suppressing_the_whole_plan_empties_the_ladder(self):
        """The behavioural statement, independent of any renderer's internals: nothing the
        compiler withholds reaches the page. This is the test that would have caught all
        four ladder-related rounds without knowing what any of them were."""
        part = _staircase()
        drawn = {n for n, _ in Sheet.from_part(part).build().iter_annotations()}
        assert [n for n in drawn if n.startswith(("dim_step", "dim_height"))], (
            "the fixture must draw a ladder to be worth emptying"
        )

        empty = RenderableDimensionPlan()
        assert empty.ladder("step_height") is None and empty.ladder("overall_height") is None

    def test_the_migration_has_not_silently_stalled(self):
        """A count, so finishing the migration is visible rather than assumed. Lower it as
        each dimensional renderer moves; the sequence ends when locations are inside too
        (#883) and only the documented AP242 PMI exception still takes the model."""
        src = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "draftwright"
            / "annotations"
            / "from_model.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        unmigrated = sorted(
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name.startswith("render_")
            and "model" in {a.arg for a in node.args.args}
        )
        assert unmigrated == [
            "render_gdt",
            "render_locations",
            "render_pmi",
            "render_step_positions",
        ], f"the unmigrated set changed: {unmigrated}"
