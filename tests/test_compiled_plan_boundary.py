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
from dataclasses import replace

import pytest
from build123d import Box, Cylinder, Pos

from draftwright import Sheet
from draftwright.annotations.from_model import render_height_ladder
from draftwright.builder import build_drawing, detect_part_model
from draftwright.model.compiled import RenderableDimensionPlan, compile_dimensions

#: Marks that carry NO value, and so legitimately survive an empty compiled plan.
#: Each needs that reason; "the test failed otherwise" is not one.
_VALUE_FREE = (
    "centerline",  # shows where an axis is
    "m_cm",  # centre marks — sized off the hole they mark (#875)
    "note_",  # the ISO NTS note
    "title_block",
    "section_",  # cutting-plane arrows and label
    "hatch",
    "detail_marker",
    "detail_caption",
)

#: Marks that DO carry a value and still survive an empty plan — i.e. renderers that have
#: not crossed the boundary yet. Listed individually rather than lumped in with furniture,
#: because calling them furniture is how the pitch dim hid: annotation names are not a
#: semantic type system, and a prefix list quietly became the definition of "dimensional"
#: (#923 review round 4). Each entry is a pending migration, and the ADR names it too.
_PENDING_VALUE_CARRYING = (
    "m_locx",  # hole location ladders — #883
    "m_locy",
    "m_env",  # envelope width/depth — render_envelope, still on the advisory surface
    "hc_",  # hole callouts — likewise
    "dim_pitch",  # pattern pitch — derived in _add_furniture from the feature
    "dim_od",  # rotational OD — render_rotational, still on the advisory surface
    "ldr_",  # concentric bore leaders — likewise
    "m_dia",  # step/boss diameters — likewise
    "m_steplen",
    "m_slot",
    "m_pocket",
    "m_boss",
    "m_plate",
    "m_chamf",
    "m_fillet",
    "m_flat",
    "m_groove",
    "pmi_",  # raw AP242 PMI — the one documented permanent exception
)


def _staircase():
    return Box(120, 60, 15) + Pos(-20, 0, 15) * Box(80, 60, 15) + Pos(-40, 0, 30) * Box(40, 60, 15)


def _crowded_staircase():
    """A tall narrow stacked-tier block whose shoulders sit 3 mm apart in Z.

    At the auto sheet scale the legibility gate drops at least one rung, which is the
    trigger for the enlarged detail view — the only way to exercise the detail redraw at
    all. Narrow in X/Y so the detail footprint actually fits the sheet; a fixture whose
    detail is `detail_unplaceable` draws nothing and would make this test vacuous.
    (Mirrors `_crowded_shoulder_part` in tests/test_make_drawing.py.)
    """
    part = Pos(0, 0, 3) * Box(20, 16, 6)
    z = 6.0
    for w in (16, 13, 10, 7, 5):
        part = part + Pos(0, 0, z + 1.5) * Box(w, 12, 3)
        z += 3
    return part


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

    @pytest.mark.parametrize(
        "make_part", [_staircase, _uniform_staircase], ids=["stepped", "uniform"]
    )
    def test_a_label_always_measures_its_own_span(self, make_part):
        """The invariant that keeps a dimension honest: the number printed IS the distance
        between the two points the line runs between.

        It broke the moment the compiler started measuring from `StepLevelFeature.base`
        while the renderer still anchored every witness at the view's bottom edge — a
        declared base above the part's bottom made the line span the whole part and read
        the shorter figure (#923 review). Checking it at the source catches the
        disagreement for every renderer rather than one fixture at a time.

        Distance along the span's OWN varying axis, not the Z delta: a height rung runs
        along Z and a shoulder along X, and a Z-only check silently passes every shoulder
        while claiming to be general (#923 review round 2). A representative rung is
        included rather than exempted — it measures one rise, so it obeys the same rule;
        what differs is only that its LABEL reports that rise n times.
        """
        plan = compile_dimensions(detect_part_model(make_part()))
        for ladder in plan.ladders:
            for rung in ladder.rungs:
                if rung.span is None:
                    continue
                lo, hi = rung.span
                measured = max(abs(b - a) for a, b in zip(lo, hi))
                assert measured == pytest.approx(rung.value, rel=0.1), (
                    f"{ladder.kind} {rung.label!r} spans {measured} but claims {rung.value}"
                )
                if ladder.representative:
                    # The one deliberate difference, asserted rather than skipped: the span
                    # is a single rise and the label multiplies it.
                    assert "×" in rung.label, "a representative mark must say how many"

    def test_a_declared_base_is_measured_from_that_base(self):
        """`StepLevelFeature.base` is the IR's own statement of what the rungs measure from.
        The planner always used it; the renderer used the bounding-box minimum, so for a
        declared base the plan and the drawing disagreed about the number. One source now."""
        from draftwright.model.ir import Frame, PartModel, StepLevelFeature

        step = StepLevelFeature(Frame((0, 0, 5), "z"), base=5.0, levels=(10.0, 20.0))
        model = PartModel(
            bbox=Box(90, 60, 30).bounding_box(),
            orientation="prismatic",
            features=[step],
            datums=[],
        )
        rungs = compile_dimensions(model).ladder("step_height")
        assert [r.value for r in rungs.rungs] == [5.0, 15.0], "measured from base=5, not bbox"
        assert all(r.span[0][2] == 5.0 for r in rungs.rungs), "and the LINE starts there too"

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
        # `_feature` is the FeatureRef escape hatch: resolving a provenance handle back to
        # its feature inside a dimensional renderer is a boundary violation, and this is
        # where it gets caught.
        forbidden = {
            "features",
            "bb",
            "levels",
            "shoulders",
            "orientation",
            "z_size",
            "base",
            "_feature",
        }
        assert not (reads & forbidden), (
            f"{sorted(reads & forbidden)} is model content — the ladder is drawn from the "
            "compiled plan's approved entries, whose spans carry every coordinate it needs"
        )

    def test_the_provenance_handle_exposes_no_measurement(self):
        """Carrying the `Feature` on an approved entry left the bypass one attribute access
        away — `.feature.levels` rebuilds exactly what the compiler withheld (#923 review).
        The handle exposes identity and category, and no measurement."""
        from draftwright.model.compiled import FeatureRef

        ladder = compile_dimensions(detect_part_model(_staircase())).ladder("step_height")
        assert isinstance(ladder.ref, FeatureRef)
        assert ladder.ref.kind == "step_level", "category is fine — it is not a measurement"
        for content in ("levels", "shoulders", "base", "datum", "parameters"):
            assert not hasattr(ladder.ref, content), f"FeatureRef exposes {content}"

    def test_identities_survive_the_compile(self):
        """`DimensionId` is ADR 0016's stable addressable identity; a renderer-facing result
        that discarded it would create identity debt on the boundary meant to remove it."""
        plan = compile_dimensions(detect_part_model(_staircase()))
        for ladder in plan.ladders:
            for rung in ladder.rungs:
                assert rung.id is not None, f"{ladder.kind} rung lost its DimensionId"

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
    def test_an_empty_plan_draws_no_ladder_in_a_REAL_build(self, monkeypatch):
        """The behavioural statement, and it has to render to mean anything.

        The first version of this test built an empty `RenderableDimensionPlan` and asserted
        its lookups returned `None` — which is a fact about a dataclass, not about the
        engine. It would have passed with `render_height_ladder` ignoring the plan entirely
        and rebuilding every dimension from the model, i.e. with the exact defect the
        boundary exists to prevent (#923 review). Patching the compiler inside a real build
        is what makes it load-bearing.
        """
        part = _staircase()
        drawn = {n for n, _ in Sheet.from_part(part).build().iter_annotations()}
        assert [n for n in drawn if n.startswith(("dim_step", "dim_height"))], (
            "the fixture must draw a ladder to be worth emptying"
        )

        monkeypatch.setattr(
            "draftwright.annotations.orchestrator.compile_dimensions",
            lambda *a, **kw: RenderableDimensionPlan(),
        )
        empty = {n for n, _ in Sheet.from_part(part).build().iter_annotations()}
        # Anything that is neither value-free furniture nor a NAMED pending migration.
        # Filtering to `dim_step`/`dim_height` let `dim_shoulder_*` through for a whole
        # round, and folding value-carrying marks into a "furniture" list hid the pitch dim
        # for another — a guard that only looks where you already know to look is not a
        # guard, and a prefix list must not become the definition of "dimensional".
        leaked = sorted(
            n for n in empty if not n.startswith(_VALUE_FREE + _PENDING_VALUE_CARRYING)
        )
        assert not leaked, (
            f"{leaked} reached the page from an EMPTY compiled plan — something is "
            "rebuilding dimensions from somewhere other than the plan, and it is not on "
            "the pending list"
        )

    def test_the_detail_view_emits_exactly_the_approved_rungs(self):
        """The detail escalation obeys the boundary too — the last dimensional bypass.

        `_request_prismatic_detail` used to re-derive the step from `dwg.model()` and
        rebuild the ladder from `step.levels`, so a rung the compiler withheld still
        reached the detail view: an approved three-rung plan drew five (#923 review).
        Restricting the direct renderer while its escalation reconstructed the same content
        left the rule true only of the path anyone happened to look at.

        This replaces a test that asserted the *source text* of the defect — which passed
        only while the bug existed, required it, and said nothing about behaviour. Here a
        deliberately PARTIAL plan goes through a real build and the detail view must carry
        those rungs and no others."""
        part = _crowded_staircase()
        model = detect_part_model(part)
        full = compile_dimensions(model).ladder("step_height")
        assert full is not None and not full.representative and len(full.rungs) >= 3, (
            f"the fixture must have individual rungs to withhold (got {full})"
        )

        # Three of five: enough rungs left that the legibility gate still drops one and the
        # escalation still fires. Withholding more suppresses the detail request itself, and
        # the test then passes by drawing nothing — which is how its first version was
        # vacuous against the very bug it targets.
        keep = full.rungs[:3]
        partial = RenderableDimensionPlan(ladders=(replace(full, rungs=tuple(keep)),))

        def _partial(*_a, **_kw):
            return partial

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("draftwright.annotations.orchestrator.compile_dimensions", _partial)
            dwg = build_drawing(part, title="T", number="N", detail_view=True)

        detail = {
            n: getattr(o, "label", None) for n, o in dwg.iter_annotations() if "dim_detail" in n
        }
        assert detail, "the fixture must actually place a detail view, or this proves nothing"
        assert len(detail) <= len(keep), (
            f"the detail view drew {len(detail)} step dims from a plan approving "
            f"{len(keep)} — it is rebuilding the ladder from the model: {sorted(detail)}"
        )
        approved_labels = {r.label for r in keep}
        assert set(detail.values()) <= approved_labels, (
            f"the detail view drew {sorted(set(detail.values()) - approved_labels)}, which "
            "the compiler did not approve"
        )

    def test_the_migration_guard_measures_the_CONTRACT_not_the_signature(self):
        """How far the boundary actually reaches, by what each renderer is HANDED.

        The first version of this counted `render_*` functions taking `model` and reported
        the migration nearly complete. That measured the wrong property: a renderer taking
        legacy `groups` receives `PlannedDimension`s whose `suppressed` is still an advisory
        boolean it can ignore — which is the exact surface eight #921 rounds found being
        ignored. Not naming a parameter `model` is not the same as having crossed the
        boundary (#923 review round 4).

        So classification is by contract: `plan` means approved entries only; `groups`
        means the advisory surface; `model` means raw inventory. The pending lists are
        pinned so the count cannot drift, and so finishing is a visible event rather than
        an assumption.
        """
        by_contract: dict[str, list[str]] = {"plan": [], "groups": [], "model": []}
        for mod in ("from_model", "holes"):
            src = (
                pathlib.Path(__file__).resolve().parents[1]
                / "src"
                / "draftwright"
                / "annotations"
                / f"{mod}.py"
            ).read_text(encoding="utf-8")
            for node in ast.parse(src).body:
                if not isinstance(node, ast.FunctionDef) or not node.name.startswith("render_"):
                    continue
                args = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
                for contract in ("plan", "groups", "model"):
                    if contract in args:
                        by_contract[contract].append(node.name)
                        break

        assert sorted(by_contract["plan"]) == [
            "render_boss_diameters",
            "render_boss_heights",
            "render_chamfers",
            "render_fillets",
            "render_flats",
            "render_grooves",
            "render_height_ladder",
            "render_plates",
            "render_step_positions",
        ], "the migrated set changed — update this and the ADR's inventory together"

        assert sorted(by_contract["groups"]) == [
            "render_centermarks",
            "render_diameters",
            "render_envelope",
            "render_pocket_patterns",
            "render_pockets",
            "render_rotational",
            "render_slot_patterns",
            "render_slots",
            "render_step_lengths",
        ], f"the advisory-surface set changed: {sorted(by_contract['groups'])}"

        assert sorted(by_contract["model"]) == [
            "render_gdt",
            "render_locations",
            "render_pmi",
        ], f"the raw-inventory set changed: {sorted(by_contract['model'])}"

    def test_the_pending_dimensional_paths_are_the_ones_the_adr_names(self):
        """Two paths still emit dimensional content of their own, and the ADR says so.

        A pattern's pitch dim prints `4× 20` — a VALUE, which is what makes something
        dimensional under this rule, however it is grouped in the code. It survives an
        empty compiled plan today. This test does not assert the bypass exists (a test
        that requires a bug is not a guard); it asserts the ADR and the code agree about
        WHICH paths are outstanding, so the list cannot quietly grow."""
        adr = (
            pathlib.Path(__file__).resolve().parents[1]
            / "docs"
            / "adr"
            / "0016-declared-dimensioning-intent.md"
        ).read_text(encoding="utf-8")
        assert "render_rotational" in adr and "render_envelope" in adr, (
            "the ADR's pending inventory stopped naming the advisory-surface renderers — "
            "it must list what has NOT crossed the boundary, not just what has"
        )
        assert "Pattern pitch dimensions" in adr, "pitch dims dropped off the pending list"
        assert "#883" in adr, "locations dropped off the pending list"
