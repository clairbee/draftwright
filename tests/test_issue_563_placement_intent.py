"""#563 — authored dimensions select a semantic view/strip, never page coordinates."""

from __future__ import annotations

import warnings
from typing import cast

import pytest
from build123d import Align, Box, Cylinder, Pos, Rot

from draftwright import Sheet
from draftwright.compose import _compose_anno_boxes, _footprint_from_boxes
from draftwright.model import DimensionParameterId
from draftwright.model.compiled import compile_dimensions
from draftwright.model.planner import plan_dimensions
from draftwright.sheet_emit import emit_sheet_script


def _opposite_face_taps():
    """A GRM-02-shaped pair: coaxial M2/M4 blind operations from opposite faces."""
    return (
        Box(40, 40, 20, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        - Pos(0, 0, 4) * Cylinder(1, 6)
        - Pos(0, 0, -10) * Cylinder(2, 6)
    )


def _authored_taps() -> Sheet:
    sheet = Sheet.from_part(_opposite_face_taps(), page="A3", scale=2).take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="automatic",
    )
    holes = sorted(
        (feature for feature in sheet.features if feature.kind == "hole"),
        key=lambda feature: feature.diameter,
    )
    for feature, side, thread in zip(
        holes,
        ("left", "right"),
        ("M2x0.4", "M4x0.7"),
        strict=True,
    ):
        handle = sheet.of(feature).thread(thread)
        for parameter_id in handle.dimension_ids():
            if parameter_id == "location":
                sheet.dimension(handle, cast(DimensionParameterId, parameter_id))
            else:
                sheet.dimension(
                    handle,
                    cast(DimensionParameterId, parameter_id),
                    view="plan",
                    side=side,
                )
    envelope = next(feature for feature in sheet.features if feature.kind == "envelope")
    for parameter in envelope.parameters():
        sheet.dimension(envelope, cast(DimensionParameterId, parameter.parameter_id))
    return sheet


def test_referential_intent_survives_ir_planner_compiler_and_places_opposite_sides():
    sheet = _authored_taps()
    requests = [
        request
        for request in sheet.model().authored_dimensions
        if request.feature.kind == "hole" and request.role != "location"
    ]
    assert {(request.view, request.side) for request in requests} == {
        ("plan", "left"),
        ("plan", "right"),
    }

    planned = [group for group in plan_dimensions(sheet.model()) if group.feature.kind == "hole"]
    assert {(group.view, group.side) for group in planned} == {
        ("plan", "left"),
        ("plan", "right"),
    }
    compiled = [
        group for group in compile_dimensions(sheet.model()).groups if group.feature_kind == "hole"
    ]
    assert {(group.view, group.side) for group in compiled} == {
        ("plan", "left"),
        ("plan", "right"),
    }

    drawing = sheet.build()
    plan_left, _, plan_right, _ = drawing.view_bounds("plan")
    callouts = {
        annotation.label: annotation
        for name, annotation in drawing.iter_annotations()
        if name.startswith("hc_plan")
    }
    assert callouts["⌀2 ↧ 6 M2x0.4"].elbow[0] < plan_left
    assert callouts["⌀4 ↧ 3 M4x0.7"].elbow[0] > plan_right
    assert not [issue for issue in drawing.lint() if issue.severity != "info"]


def test_referential_placement_round_trips_through_generated_sheet_code():
    sheet = _authored_taps()
    source = emit_sheet_script(
        sheet.model(),
        "part",
        "grm02",
        title="GRM-02",
        number="GRM-02",
        view_constraints=sheet.view_constraints,
    )
    assert 'view="plan", side="left"' in source
    assert 'view="plan", side="right"' in source

    namespace = {"part": _opposite_face_taps()}
    body = source.replace("\npart\n", "\n", 1)
    exec(  # noqa: S102 - generated public Sheet code is the round-trip under test
        compile(body[: body.index("drawing = sheet.build()")], "<issue-563>", "exec"),
        namespace,
    )
    regenerated = namespace["sheet"]
    policies = {
        (request.feature.diameter, request.view, request.side)
        for request in regenerated.model().authored_dimensions
        if request.feature.kind == "hole" and request.role != "location"
    }
    assert policies == {(2.0, "plan", "left"), (4.0, "plan", "right")}


def test_augmenting_referential_intent_is_preserved_when_the_emitter_mirrors_it():
    sheet = Sheet(Box(40, 40, 10))
    hole = sheet.hole(diameter=4, at=(0, 0, 0), axis="z")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheet.auto_dimensions()
        sheet.add_dimension(hole, "bore.diameter", view="plan", side="left")

    source = emit_sheet_script(sheet.model(), "part", "augment", title="P", number="N")
    assert 'sheet.dimension(hole1, "bore.diameter", view="plan", side="left")' in source


def test_independent_envelope_dimensions_honour_distinct_view_overrides():
    sheet = Sheet.from_part(Box(40, 20, 10), page="A3").take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="automatic",
    )
    envelope = next(feature for feature in sheet.features if feature.kind == "envelope")
    sheet.dimension(envelope, "width.length", view="front")
    sheet.dimension(envelope, "depth.length", view="side")

    planned = next(group for group in plan_dimensions(sheet.model()) if group.feature is envelope)
    assert {(pd.param.parameter_id, pd.view) for pd in planned.dims if not pd.suppressed} == {
        ("width.length", "front"),
        ("depth.length", "side"),
    }
    compiled = next(
        group
        for group in compile_dimensions(sheet.model()).groups
        if group.feature_kind == "envelope"
    )
    assert {(pd.parameter_id, pd.view) for pd in compiled.dims} == {
        ("width.length", "front"),
        ("depth.length", "side"),
    }

    drawing = sheet.build()
    assert drawing.view_of("m_env_width") == "front"
    assert drawing.view_of("m_env_depth") == "side"
    assert not [issue for issue in drawing.lint() if issue.severity != "info"]


def test_augmenting_envelope_view_policy_builds_without_moving_its_siblings():
    sheet = Sheet.from_part(Box(40, 20, 10), page="A3")
    envelope = next(feature for feature in sheet.features if feature.kind == "envelope")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheet.auto_dimensions()
        sheet.add_dimension(envelope, "width.length", view="front")

    drawing = sheet.build()
    assert drawing.view_of("m_env_width") == "front"
    assert drawing.view_of("m_env_depth") == "side"


def test_referential_override_vetoes_an_automatic_view_reduction():
    part = Rot(0, 90, 0) * Cylinder(10, 40)
    sheet = Sheet.from_part(part, page="A3").take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="automatic",
    )
    envelope = next(feature for feature in sheet.features if feature.kind == "envelope")
    sheet.dimension(envelope, "width.length", view="plan")

    drawing = sheet.build()
    assert "plan" in drawing.views
    assert drawing.view_decision["status"] == "retained_for_requirements"


def _measured_sheet(*, view=None, side=None) -> Sheet:
    sheet = Sheet(Box(40, 20, 10)).authored_dimensions()
    sheet.measured_dimension(
        kind="linear",
        value=10,
        label="10",
        dominant_axis="Z",
        ref_bbox=(-10, -5, 0, 10, 5, 10),
        ref_pts=[(0, 0, 0), (0, 0, 10)],
        view=view,
        side=side,
    )
    return sheet


def test_measured_dimension_uses_requested_corridor_and_round_trips():
    sheet = _measured_sheet(view="front", side="left")
    drawing = sheet.build()
    annotation = drawing.get_annotation("pmi_z_0")
    assert annotation._dw_spec.side == "left"
    assert not [issue for issue in drawing.lint() if issue.severity != "info"]

    source = emit_sheet_script(sheet.model(), "part", "measured", title="P", number="N")
    assert "view='front'" in source and "side='left'" in source
    namespace = {"part": Box(40, 20, 10)}
    exec(  # noqa: S102 - generated public Sheet code is the round-trip under test
        compile(source[: source.index("drawing = sheet.build()")], "<issue-563-pmi>", "exec"),
        namespace,
    )
    record = next(
        feature
        for feature in namespace["sheet"].model().features
        if feature.kind == "authored_dimension"
    )
    assert (record.view, record.side) == ("front", "left")


def test_no_measured_override_keeps_existing_geometric_derivation():
    annotation = _measured_sheet().build().get_annotation("pmi_z_0")
    assert annotation._dw_spec.side == "right"


def test_view_only_measured_override_preserves_the_derived_side():
    def build(view):
        sheet = Sheet(Box(60, 40, 20), page="A3").authored_dimensions()
        sheet.measured_dimension(
            kind="linear",
            value=10,
            label="10",
            dominant_axis="Z",
            ref_bbox=(-25, -2, 0, -15, 2, 10),
            ref_pts=[(-20, 0, 0), (-20, 0, 10)],
            view=view,
        )
        return sheet.build().get_annotation("pmi_z_0")._dw_spec.side

    assert build(None) == build("front") == "left"


def test_front_above_measured_intent_participates_in_view_composition():
    for view in ("front", None):
        sheet = Sheet(Box(60, 40, 20), page="A3").authored_dimensions()
        sheet.measured_dimension(
            kind="linear",
            value=40,
            label="40",
            dominant_axis="X",
            ref_bbox=(-20, -2, 4, 20, 2, 8),
            ref_pts=[(-20, 0, 6), (20, 0, 6)],
            view=view,
            side="above",
        )
        drawing = sheet.build()
        assert drawing.get_annotation("pmi_x_0")._dw_spec.side == "above"
        assert not [issue for issue in drawing.lint() if issue.severity != "info"]


def test_y_and_diameter_measured_intents_use_their_supported_exact_corridors():
    y_sheet = Sheet(Box(40, 20, 10), page="A3").authored_dimensions()
    y_sheet.measured_dimension(
        kind="linear",
        value=20,
        label="20",
        dominant_axis="Y",
        ref_bbox=(-10, -10, 2, 10, 10, 8),
        ref_pts=[(0, -10, 5), (0, 10, 5)],
        view="side",
        side="above",
    )
    y_drawing = y_sheet.build()
    assert y_drawing.get_annotation("pmi_y_0")._dw_spec.side == "above"
    assert not [issue for issue in y_drawing.lint() if issue.severity != "info"]

    diameter_sheet = Sheet(Box(40, 40, 10), page="A3").authored_dimensions()
    diameter_sheet.measured_dimension(
        kind="diameter",
        value=10,
        label="ø10",
        dominant_axis="Z",
        ref_bbox=(-5, -5, 0, 5, 5, 10),
        ref_pts=[(-5, 0, 5), (5, 0, 5)],
        view="plan",
        side="above",
    )
    diameter_drawing = diameter_sheet.build()
    assert diameter_drawing.get_annotation("pmi_d_0")._dw_spec.side == "above"
    assert not [issue for issue in diameter_drawing.lint() if issue.severity != "info"]


@pytest.mark.parametrize("side", ["left", "right"])
def test_y_plan_measured_intents_participate_in_horizontal_composition(side):
    sheet = Sheet(Box(40, 20, 10), page="A3").authored_dimensions()
    sheet.measured_dimension(
        kind="linear",
        value=20,
        label="20",
        dominant_axis="Y",
        ref_bbox=(-2, -10, 2, 2, 10, 8),
        ref_pts=[(0, -10, 5), (0, 10, 5)],
        view="plan",
        side=side,
    )
    drawing = sheet.build()
    assert drawing.get_annotation("pmi_y_0")._dw_spec.side == side
    assert not [issue for issue in drawing.lint() if issue.severity != "info"]


def test_compose_reserves_every_supported_measured_corridor_family():
    sheet = Sheet(Box(40, 20, 10)).authored_dimensions()
    cases = (
        ("linear", "X", "front", None),
        ("linear", "Z", "front", None),
        ("linear", "Y", "side", None),
        ("linear", "Y", "plan", None),
        ("linear", "X", "front", "below"),
        ("diameter", "Z", "plan", "above"),
        ("diameter", "Z", "plan", "below"),
        ("diameter", "X", "side", "above"),
        ("diameter", "X", "side", "below"),
    )
    for index, (kind, axis, view, side) in enumerate(cases):
        sheet.measured_dimension(
            kind=kind,
            value=10,
            label=str(index),
            dominant_axis=axis,
            ref_bbox=(-5, -5, 0, 5, 5, 10),
            ref_pts=[(-5, 0, 5), (5, 0, 5)],
            view=view,
            side=side,
        )

    footprint = _footprint_from_boxes(_compose_anno_boxes(sheet.model(), n_steps=0))
    assert footprint.left > 0 and footprint.right > 0
    assert footprint.fv_top > 0 and footprint.fv_bottom > 0
    assert footprint.pv_authored_top > 0 and footprint.pv_bottom > 0
    assert footprint.sv_top > 0 and footprint.sv_bottom > 0


@pytest.mark.parametrize(
    ("view", "side", "message"),
    [
        ("iso", "below", "view must be one of"),
        ("front", "above", "cannot render linear/Z"),
    ],
)
def test_invalid_measured_placement_fails_clearly(view, side, message):
    with pytest.raises(ValueError, match=message):
        _measured_sheet(view=view, side=side)


def test_invalid_referential_strip_and_compound_conflict_fail_clearly():
    bad_side = Sheet(Box(40, 40, 10)).authored_dimensions()
    hole = bad_side.hole(diameter=4, at=(0, 0, 0), axis="z")
    bad_side.dimension(hole, "bore.diameter", view="plan", side="above")
    with pytest.raises(ValueError, match="supported sides"):
        plan_dimensions(bad_side.model())

    conflict = Sheet(Box(40, 40, 10)).authored_dimensions()
    blind = conflict.hole(diameter=4, at=(0, 0, 0), axis="z").depth(5)
    conflict.dimension(blind, "bore.diameter", view="plan", side="left")
    conflict.dimension(blind, "bore.depth", view="plan", side="right")
    with pytest.raises(ValueError, match="conflicting placement intent"):
        plan_dimensions(conflict.model())


def test_location_unknown_side_unavailable_view_and_missing_planned_view_fail_clearly():
    invalid_side = Sheet(Box(40, 40, 10)).authored_dimensions()
    with pytest.raises(ValueError, match="side must be one of"):
        invalid_side.measured_dimension(
            kind="linear",
            value=10,
            label="10",
            dominant_axis="Z",
            ref_bbox=(-5, -5, 0, 5, 5, 10),
            ref_pts=[(0, 0, 0), (0, 0, 10)],
            view="front",
            side="inside",
        )

    location_sheet = Sheet(Box(40, 40, 10)).authored_dimensions()
    located = location_sheet.hole(diameter=4, at=(5, 5, 0), axis="z")
    location_sheet.dimension(located, "location", view="plan", side="left")
    with pytest.raises(ValueError, match="unavailable for location dimensions"):
        location_sheet.model()

    bad_view = Sheet(Box(40, 40, 10)).authored_dimensions()
    bore = bad_view.hole(diameter=4, at=(0, 0, 0), axis="z")
    bad_view.dimension(bore, "bore.diameter", view="front")
    with pytest.raises(ValueError, match="cannot render in 'front'"):
        plan_dimensions(bad_view.model())

    missing_view = Sheet(Box(40, 40, 10)).authored_dimensions()
    bore = missing_view.hole(diameter=4, at=(0, 0, 0), axis="z")
    missing_view.dimension(bore, "bore.diameter", view="plan")
    with pytest.raises(ValueError, match="cannot be shown"):
        plan_dimensions(missing_view.model(), planned_views=("front",))

    measured_missing = Sheet(Box(40, 20, 10)).authored_dimensions().authored_views()
    measured_missing.view("front")
    measured_missing.measured_dimension(
        kind="diameter",
        value=10,
        label="ø10",
        dominant_axis="Z",
        ref_bbox=(-5, -5, 0, 5, 5, 10),
        ref_pts=[(-5, 0, 5), (5, 0, 5)],
        view="plan",
        side="above",
    )
    with pytest.raises(ValueError, match="cannot be shown"):
        measured_missing.build()

    side_only_missing = Sheet(Box(40, 20, 10)).authored_dimensions().authored_views()
    side_only_missing.view("front")
    side_only_missing.measured_dimension(
        kind="linear",
        value=20,
        label="20",
        dominant_axis="Y",
        ref_bbox=(-10, -10, 2, 10, 10, 8),
        ref_pts=[(0, -10, 5), (0, 10, 5)],
        side="right",
    )
    with pytest.raises(ValueError, match="cannot be shown"):
        side_only_missing.build()


def test_pattern_pitch_placement_policy_is_rejected_instead_of_moving_the_callout():
    sheet = Sheet(Box(40, 20, 10)).authored_dimensions()
    sheet.hole(diameter=4, at=(-10, 0, 0), axis="z")
    pattern = sheet.pattern(
        sheet.features[-1],
        kind="linear",
        count=3,
        pitch=10,
        direction=(1, 0, 0),
        at=(-10, 0, 0),
    )
    sheet.dimension(pattern, "pitch.length", view="plan", side="left")
    with pytest.raises(ValueError, match="unavailable.*pattern pitch"):
        plan_dimensions(sheet.model())
