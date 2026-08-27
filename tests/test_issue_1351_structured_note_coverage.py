"""Structured feature notes carry explicit requirement coverage without parsing prose (#1351)."""

from __future__ import annotations

from typing import cast

import pytest
from b123d_recognisers import recognise_slots
from build123d import Box, Cylinder, Pos

from draftwright import Sheet
from draftwright.linting.hole_coverage import hole_requirement_outcomes
from draftwright.linting.slot_coverage import slot_requirement_outcomes
from draftwright.model import DimensionParameterId
from draftwright.model.compiled import compile_dimensions
from draftwright.sheet_emit import emit_sheet_script

_SATISFIES = ("counterbore.diameter", "counterbore.depth")


def _part():
    return Box(60, 40, 20) - Cylinder(4, 40) - Pos(0, 0, 6) * Cylinder(7, 8)


def _sheet(*, note: bool, satisfies: tuple[str, ...] = ()) -> Sheet:
    sheet = Sheet.from_part(_part(), page="A3").take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="authored",
    )
    counterbore = next(
        feature for feature in sheet.features if feature.kind == "hole" and feature.cbore
    )
    handle = sheet.of(counterbore)
    for parameter_id in handle.dimension_ids():
        if parameter_id not in _SATISFIES:
            sheet.dimension(handle, cast(DimensionParameterId, parameter_id))
    for feature in sheet.features:
        if feature.kind == "envelope":
            for parameter in feature.parameters():
                sheet.dimension(feature, parameter.parameter_id)
    if note:
        handle.note(
            "PROFILED BORE: diameter 14 x 8 DEEP",
            satisfies=satisfies,
        )
    return sheet


def _counterbore_states(drawing) -> dict[str, str]:
    drawing.lint()  # declared builds acquire critique recognition lazily
    return {
        outcome.parameter_id: outcome.state
        for outcome in hole_requirement_outcomes(
            drawing._build.recognition,  # acceptance checks the public drawing's run inventory
            drawing.model().features,
            drawing.registry,
            drawing._build.omissions,
        )
        if outcome.parameter_id in _SATISFIES
    }


def test_structured_note_satisfies_omitted_roles_without_becoming_a_dimension():
    drawing = _sheet(note=True, satisfies=_SATISFIES).build()

    assert _counterbore_states(drawing) == {
        parameter: "satisfied_by_structured_note" for parameter in _SATISFIES
    }
    satisfaction_names = [
        name for name in drawing.registry.names() if drawing.registry.satisfaction_of(name)
    ]
    assert len(satisfaction_names) == 1
    assert drawing.registry.measurement_of(satisfaction_names[0]) == ()
    assert {
        identity.parameter for identity in drawing.registry.satisfaction_of(satisfaction_names[0])
    } == set(_SATISFIES)

    issues = drawing.lint()
    assert not [
        issue
        for issue in issues
        if issue.code == "hole_requirement_suppressed"
        and any(parameter in issue.message for parameter in _SATISFIES)
    ]
    assert not [
        issue
        for issue in issues
        if issue.code == "feature_not_dimensioned" and "ø14" in issue.message
    ]
    completeness = drawing.lint_summary()["quality"]["completeness"]
    assert completeness["satisfied_by_structured_note"] == 2
    assert completeness["audited_score"] == 1.0


@pytest.mark.parametrize("with_note", [False, True])
def test_prose_without_structured_satisfaction_cannot_silence_coverage(with_note):
    drawing = _sheet(note=with_note).build()

    assert _counterbore_states(drawing) == {parameter: "suppressed" for parameter in _SATISFIES}
    issues = drawing.lint()
    suppressed = [
        issue
        for issue in issues
        if issue.code == "hole_requirement_suppressed"
        and any(parameter in issue.message for parameter in _SATISFIES)
    ]
    assert len(suppressed) == 2
    assert any(
        issue.code == "feature_not_dimensioned" and "ø14" in issue.message for issue in issues
    )


@pytest.mark.parametrize(
    ("satisfies", "message"),
    [
        (("counterbore.diameter", "counterbore.diameter"), "duplicate parameter ids"),
        (("bore.depth",), "invalid parameter id"),
        (("counterbore",), "invalid parameter id"),
    ],
)
def test_invalid_or_ambiguous_satisfaction_claims_fail_before_mutating_the_sheet(
    satisfies, message
):
    sheet = _sheet(note=False)
    handle = sheet.of(next(feature for feature in sheet.features if feature.kind == "hole"))
    before = tuple(sheet.features)

    with pytest.raises(ValueError, match=message):
        handle.note("PROFILED BORE", satisfies=satisfies)

    assert tuple(sheet.features) == before


def test_structured_note_round_trips_through_generated_sheet_source():
    sheet = _sheet(note=True, satisfies=_SATISFIES)
    source = emit_sheet_script(
        sheet.model(),
        "part",
        "structured-note",
        title="T",
        number="N",
        page="A3",
    )
    assert ".note(" in source
    assert f"satisfies={_SATISFIES!r}" in source

    namespace = {"part": _part()}
    body = source.replace("\npart\n", "\n", 1)
    exec(  # noqa: S102 - exercise the generated public Sheet source
        compile(body[: body.index("drawing = sheet.build()")], "<structured-note>", "exec"),
        namespace,
    )
    regenerated = namespace["sheet"]
    note = next(feature for feature in regenerated.features if feature.kind == "note")
    assert note.satisfies == _SATISFIES
    assert note.origin in regenerated.features


def test_structured_note_authority_is_shared_by_non_hole_requirement_ledgers():
    part = Box(100, 70, 10) - Pos(22, -11, 0) * Box(30, 8, 20)
    (source,) = recognise_slots(part)
    sheet = Sheet(part)
    handle = sheet.slot(
        width=source.width,
        length=source.length,
        long_axis=source.long_axis,
        width_axis=source.width_axis,
        depth_axis=source.depth_axis,
        w_center=source.w_center,
        lo=source.lo,
        hi=source.hi,
        at=source.location,
    )
    sheet.dimension(sheet.envelope(), "width.length")  # authored: slot roles are omitted
    handle.note("MILL 8 WIDE SLOT", satisfies=("slot_width.length",))
    drawing = sheet.build()
    drawing.lint()

    states = {
        outcome.parameter_id: outcome.state
        for outcome in slot_requirement_outcomes(
            drawing.recognition(),
            drawing.model().features,
            drawing.registry,
            compile_dimensions(drawing.model()).diagnostics,
        )
    }
    assert states["slot_width.length"] == "satisfied_by_structured_note"
    assert states["slot_length.length"] == "suppressed"
