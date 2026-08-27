"""Detected-baseline takeover is one public, order-independent Sheet workflow (#1350)."""

from __future__ import annotations

from typing import Literal, cast

import pytest
from build123d import Box, Cylinder, Pos

from draftwright import Sheet, SoftDeprecationWarning
from draftwright.model import DimensionParameterId
from draftwright.sheet_emit import emit_sheet_script
from draftwright.view_plan import (
    ViewConstraint,
    ViewConstraints,
    ViewPin,
    ViewRelation,
    ViewSpec,
)


def _counterbored_blind_part():
    """A prismatic part with both a counterbored through-hole and a separate blind bore."""
    return (
        Box(60, 40, 20)
        - Cylinder(4, 40)
        - Pos(0, 0, 6) * Cylinder(7, 8)
        - Pos(18, 0, 8) * Cylinder(3, 20)
    )


def _counterbore(sheet: Sheet):
    feature = next(f for f in sheet.features if f.kind == "hole" and f.cbore is not None)
    return sheet.of(feature)


def _author_complete_dimensions(sheet: Sheet) -> None:
    """State the complete useful manufacturing set for this fixture through public handles."""
    for feature in sheet.features:
        if feature.kind == "hole":
            handle = sheet.of(feature)
            for parameter_id in handle.dimension_ids():
                sheet.dimension(handle, cast(DimensionParameterId, parameter_id))
        elif feature.kind == "envelope":
            for parameter in feature.parameters():
                sheet.dimension(feature, parameter.parameter_id)


def _adopted_sheet(*, derived_views: Literal["automatic", "authored"] = "authored") -> Sheet:
    sheet = Sheet.from_part(_counterbored_blind_part(), page="A3")
    sheet.take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views=derived_views,
    )
    _author_complete_dimensions(sheet)
    return sheet


def _blocking_lint(drawing):
    return [issue for issue in drawing.lint() if issue.severity != "info"]


def test_takeover_retains_detected_handles_and_replaces_the_inferred_section():
    sheet = Sheet.from_part(_counterbored_blind_part(), page="A3")
    detected_features = tuple(sheet.features)
    bore = _counterbore(sheet)  # acquired before takeover

    returned = sheet.take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="authored",
    )
    assert returned is sheet
    assert tuple(sheet.features) == detected_features

    _author_complete_dimensions(sheet)
    sheet.section_view("A", through=bore)  # the pre-takeover handle remains usable
    drawing = sheet.build()

    assert set(drawing.views) == {"front", "plan", "side", "iso", "section_aa"}
    assert [spec.name for spec in drawing.view_plan.of_kind("section")] == ["section_aa"]
    assert len([name for name in drawing.annotations() if name == "section_caption"]) == 1
    assert not _blocking_lint(drawing)


def test_derived_source_can_accept_suppress_or_replace_the_inferred_section():
    accepted = _adopted_sheet(derived_views="automatic").build()
    assert "section_aa" in accepted.views
    assert accepted.section_decision["status"] == "placed"

    suppressed = _adopted_sheet(derived_views="authored").build()
    assert suppressed.view_plan.of_kind("section") == ()

    replaced_sheet = _adopted_sheet(derived_views="authored")
    replaced_sheet.section_view("B", through=_counterbore(replaced_sheet))
    replaced = replaced_sheet.build()
    assert [spec.name for spec in replaced.view_plan.of_kind("section")] == ["section_bb"]
    assert "section_aa" not in replaced.views
    assert not _blocking_lint(replaced)


def test_matching_declarations_mean_the_same_before_or_after_takeover():
    first = Sheet.from_part(_counterbored_blind_part(), page="A3")
    first.take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="authored",
    )
    _author_complete_dimensions(first)
    first.section_view("A", through=_counterbore(first))

    last = Sheet.from_part(_counterbored_blind_part(), page="A3")
    last.authored_dimensions()
    _author_complete_dimensions(last)
    last.section_view("A", through=_counterbore(last))
    last.take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="authored",
    )

    assert first.view_constraints.principal_source == last.view_constraints.principal_source
    assert first.view_constraints.derived_source == last.view_constraints.derived_source
    assert [item.spec.name for item in first.view_constraints.derived] == [
        item.spec.name for item in last.view_constraints.derived
    ]
    first_drawing, last_drawing = first.build(), last.build()
    assert set(first_drawing.views) == set(last_drawing.views)
    assert _blocking_lint(first_drawing) == _blocking_lint(last_drawing) == []


def test_takeover_rejects_contradictory_sources_atomically():
    sheet = Sheet.from_part(_counterbored_blind_part())
    before = sheet.view_constraints

    with pytest.raises(ValueError, match="automatic dimensions with authored views"):
        sheet.take_over(
            dimensions="automatic",
            principal_views="automatic",
            derived_views="authored",
        )
    assert sheet.view_constraints == before

    with pytest.raises(ValueError, match="dimensions must be"):
        sheet.take_over(
            dimensions="planner",  # type: ignore[arg-type]
            principal_views="automatic",
            derived_views="automatic",
        )
    assert sheet.view_constraints == before


@pytest.mark.parametrize(
    "invalid_declaration",
    [
        lambda sheet: sheet.view("bogus"),
        lambda sheet: sheet.section_view("A"),
        lambda sheet: sheet.detail_view("B", object()),
    ],
)
def test_invalid_authored_view_declarations_do_not_poison_a_detected_sheet(
    invalid_declaration,
):
    sheet = Sheet.from_part(_counterbored_blind_part())
    before = sheet.view_constraints

    with pytest.raises(ValueError):
        invalid_declaration(sheet)
    assert sheet.view_constraints == before

    # A failed declaration left no hidden authored source behind, so the matching automatic
    # takeover remains valid and produces the untouched detected baseline.
    sheet.take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="automatic",
    )
    assert sheet.view_constraints.principal_source == "automatic"
    assert sheet.view_constraints.derived_source == "automatic"


@pytest.mark.parametrize("legacy_verb", ["section", "detail"])
def test_legacy_derived_augmentations_conflict_atomically_in_both_orders(legacy_verb):
    before_takeover = Sheet.from_part(_counterbored_blind_part())
    with pytest.warns(DeprecationWarning):
        if legacy_verb == "section":
            before_takeover.section(_counterbore(before_takeover))
        else:
            before_takeover.detail()
    before_constraints = before_takeover.view_constraints
    with pytest.raises(ValueError, match=r"legacy section\(\)/detail\(\)"):
        before_takeover.take_over(
            dimensions="authored",
            principal_views="automatic",
            derived_views="authored",
        )
    assert before_takeover.view_constraints == before_constraints

    after_takeover = Sheet.from_part(_counterbored_blind_part()).take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="authored",
    )
    before_constraints = after_takeover.view_constraints
    before_options = dict(after_takeover._opts)
    before_section = after_takeover._section
    with (
        pytest.warns(DeprecationWarning),
        pytest.raises(ValueError, match="cannot follow an authored derived-view source"),
    ):
        if legacy_verb == "section":
            after_takeover.section(_counterbore(after_takeover))
        else:
            after_takeover.detail()
    assert after_takeover.view_constraints == before_constraints
    assert after_takeover._opts == before_options
    assert after_takeover._section == before_section


def test_takeover_rejects_prior_explicit_sources_and_accepts_all_automatic():
    authored = Sheet.from_part(_counterbored_blind_part()).authored_dimensions()
    with pytest.raises(ValueError, match="authored dimension source"):
        authored.take_over(
            dimensions="automatic",
            principal_views="automatic",
            derived_views="automatic",
        )

    automatic = Sheet.from_part(_counterbored_blind_part())
    with pytest.warns(SoftDeprecationWarning):
        automatic.auto_dimensions()
    with pytest.raises(ValueError, match=r"explicit auto_dimensions\(\) source"):
        automatic.take_over(
            dimensions="authored",
            principal_views="automatic",
            derived_views="automatic",
        )

    prior_views = Sheet.from_part(_counterbored_blind_part())
    prior_views.take_over(
        dimensions="authored",
        principal_views="automatic",
        derived_views="automatic",
    )
    with pytest.raises(ValueError, match="existing 'automatic' derived_views source"):
        prior_views.take_over(
            dimensions="authored",
            principal_views="automatic",
            derived_views="authored",
        )

    pending_addition = Sheet.from_part(_counterbored_blind_part()).authored_dimensions()
    pending_addition.add_view("side")
    with pytest.raises(ValueError, match="conflicts with automatic-set additions"):
        pending_addition.take_over(
            dimensions="authored",
            principal_views="authored",
            derived_views="authored",
        )

    pending_dimension = Sheet.from_part(_counterbored_blind_part())
    envelope = next(
        feature for feature in pending_dimension.features if feature.kind == "envelope"
    )
    with pytest.warns(SoftDeprecationWarning):
        pending_dimension.add_dimension(envelope, "width.length")
    before_views = pending_dimension.view_constraints
    with pytest.raises(ValueError, match=r"conflicts with add_dimension\(\)"):
        pending_dimension.take_over(
            dimensions="authored",
            principal_views="automatic",
            derived_views="authored",
        )
    assert pending_dimension.view_constraints == before_views
    assert set(pending_dimension.build().views) == {"front", "plan", "side", "iso", "section_aa"}

    all_automatic = Sheet.from_part(_counterbored_blind_part()).take_over(
        dimensions="automatic",
        principal_views="automatic",
        derived_views="automatic",
    )
    assert all_automatic.view_constraints.principal_source == "automatic"
    assert all_automatic.view_constraints.derived_source == "automatic"
    assert set(all_automatic.build().views) == {"front", "plan", "side", "iso", "section_aa"}


def _dimension_signature(sheet: Sheet):
    model = sheet.model()
    feature_indexes = {id(feature): index for index, feature in enumerate(model.features)}
    return tuple(
        (
            feature_indexes[id(request.feature)],
            request.role,
            request.discriminator,
            request.display_decimals,
        )
        for request in model.authored_dimensions
    )


def test_emitter_round_trips_the_adopted_sources_dimensions_and_feature_target():
    sheet = _adopted_sheet()
    sheet.section_view("A", through=_counterbore(sheet))
    direct = sheet.build()

    source = emit_sheet_script(
        sheet.model(),
        "part",
        "adopted",
        title="T",
        number="N",
        view_constraints=sheet.view_constraints,
    )
    namespace = {"part": _counterbored_blind_part()}
    body = source.replace("\npart\n", "\n", 1)
    exec(  # noqa: S102 - the generated public script is the behavior under test
        compile(body[: body.index("drawing = sheet.build()")], "<adopted-emit>", "exec"),
        namespace,
    )
    regenerated = namespace["sheet"]

    assert regenerated.view_constraints.principal_source == "automatic"
    assert regenerated.view_constraints.derived_source == "authored"
    assert [item.spec.name for item in regenerated.view_constraints.derived] == ["section_aa"]
    target = regenerated.view_constraints.derived[0].spec.target
    assert target[0] == "feature" and target[1].kind == "hole" and target[1].cbore is not None
    assert _dimension_signature(regenerated) == _dimension_signature(sheet)
    rebuilt = regenerated.build()
    assert set(rebuilt.views) == set(direct.views)
    assert [spec.name for spec in rebuilt.view_plan.of_kind("section")] == ["section_aa"]
    assert [(issue.code, issue.severity) for issue in rebuilt.lint()] == [
        (issue.code, issue.severity) for issue in direct.lint()
    ]


def test_emitter_preserves_authored_added_and_whole_view_constraints():
    sheet = _adopted_sheet()
    model = sheet.model()
    hole = next(feature for feature in model.features if feature.kind == "hole")
    constraints = ViewConstraints(
        principal_source="authored",
        principals=(
            ViewConstraint(ViewSpec("front", "principal")),
            ViewConstraint(ViewSpec("iso", "pictorial", scale_factor=0.75)),
        ),
        derived_source="authored",
        derived=(
            ViewConstraint(ViewSpec("section_aa", "section", target=("at", 0.0))),
            ViewConstraint(
                ViewSpec("detail_b", "detail", target=("feature", hole), scale_factor=2.0)
            ),
        ),
        relations=(
            ViewRelation("front", "left_of", "iso"),
            ViewRelation("front", "below", "iso", gap=3.0),
        ),
        pins=(ViewPin("front", (40.0, 50.0)),),
    )

    source = emit_sheet_script(
        model,
        "part",
        "views",
        title="T",
        number="N",
        view_constraints=constraints,
    )

    assert 'front_view = sheet.view("front")' in source
    assert 'iso_view = sheet.view("iso").scale(0.75)' in source
    assert 'section_aa_view = sheet.section_view("A", at=0.0)' in source
    assert 'detail_b_view = sheet.detail_view("B", around=hole1).scale(2.0)' in source
    assert 'front_view.left_of("iso")' in source
    assert 'front_view.below("iso", gap=3.0)' in source
    assert "front_view.pin((40.0, 50.0))" in source

    namespace = {"part": _counterbored_blind_part()}
    body = source.replace("\npart\n", "\n", 1)
    exec(  # noqa: S102 - exercise exact authored-relation reconstruction
        compile(body[: body.index("drawing = sheet.build()")], "<authored-layout-emit>", "exec"),
        namespace,
    )
    regenerated = namespace["sheet"].view_constraints
    assert [
        (relation.subject, relation.relation, relation.reference, relation.gap)
        for relation in regenerated.relations
    ] == [
        (relation.subject, relation.relation, relation.reference, relation.gap)
        for relation in constraints.relations
    ]

    augmenting = ViewConstraints(
        principal_source="automatic",
        added_principals=(ViewConstraint(ViewSpec("side", "principal")),),
        derived_source="automatic",
        added_derived=(ViewConstraint(ViewSpec("detail_c", "detail", target=("feature", hole))),),
    )
    augmenting_source = emit_sheet_script(
        model,
        "part",
        "views",
        title="T",
        number="N",
        view_constraints=augmenting,
    )
    assert 'side_view = sheet.add_view("side")' in augmenting_source
    assert 'detail_c_view = sheet.add_detail_view("C", around=hole1)' in augmenting_source


def test_emitter_round_trips_directional_relations_between_automatic_views():
    sheet = _adopted_sheet()
    sheet.row("front", "side", gap=2.0)
    sheet.column("front", "plan", gap=4.0)

    source = emit_sheet_script(
        sheet.model(),
        "part",
        "automatic-layout",
        title="T",
        number="N",
        view_constraints=sheet.view_constraints,
    )
    assert 'sheet.row("front", "side", gap=2.0)' in source
    assert 'sheet.column("front", "plan", gap=4.0)' in source

    namespace = {"part": _counterbored_blind_part()}
    body = source.replace("\npart\n", "\n", 1)
    exec(  # noqa: S102 - exercise the generated public Sheet source
        compile(body[: body.index("drawing = sheet.build()")], "<layout-emit>", "exec"),
        namespace,
    )
    regenerated = namespace["sheet"]
    assert [
        (relation.subject, relation.relation, relation.reference, relation.gap)
        for relation in regenerated.view_constraints.relations
    ] == [
        (relation.subject, relation.relation, relation.reference, relation.gap)
        for relation in sheet.view_constraints.relations
    ]


@pytest.mark.parametrize(
    ("constraints", "message"),
    [
        (
            ViewConstraints(
                principal_source="automatic",
                principals=(ViewConstraint(ViewSpec("front", "principal")),),
            ),
            "principal views with source 'automatic'",
        ),
        (
            ViewConstraints(
                principal_source="authored",
                principals=(
                    ViewConstraint(ViewSpec("front", "principal", camera=(0.0, 0.0, 1.0))),
                ),
            ),
            "do not express camera",
        ),
        (
            ViewConstraints(
                principal_source="authored",
                principals=(ViewConstraint(ViewSpec("front", "principal", target=("at", 0.0))),),
            ),
            "principal view 'front' with a target",
        ),
        (
            ViewConstraints(
                principal_source="authored",
                principals=(ViewConstraint(ViewSpec("front", "pictorial")),),
            ),
            "principal view 'front' with kind 'pictorial'",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(ViewConstraint(ViewSpec("front", "principal", target=("at", 0.0))),),
            ),
            "derived view 'front' with kind 'principal'",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(ViewConstraint(ViewSpec("detail_bad", "detail", target=None)),),
            ),
            "non-canonical name",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(ViewConstraint(ViewSpec("detail_b", "detail", target=None)),),
            ),
            "no semantic target",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(
                    ViewConstraint(ViewSpec("detail_b", "detail", target=("feature", object()))),
                ),
            ),
            "target feature has no script binding",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(ViewConstraint(ViewSpec("detail_b", "detail", target=("at", 0.0))),),
            ),
            "unsupported target",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(
                    ViewConstraint(ViewSpec("section_aa", "section", target=("at", float("inf")))),
                ),
            ),
            "at= target must be a finite numeric value",
        ),
        (
            ViewConstraints(
                derived_source="authored",
                derived=(ViewConstraint(ViewSpec("section_aa", "section", target=("at", True))),),
            ),
            "at= target must be a finite numeric value",
        ),
        (
            ViewConstraints(relations=(ViewRelation("front", "align_x", "plan"),)),
            "align_x relation for automatic view",
        ),
        (
            ViewConstraints(
                principal_source="authored",
                principals=(ViewConstraint(ViewSpec("front", "principal")),),
                relations=(ViewRelation("front", "align_x", "plan", gap=1.0),),
            ),
            "alignment verbs do not accept a gap",
        ),
        (
            ViewConstraints(pins=(ViewPin("front", (10.0, 20.0)),)),
            "pin for automatic view",
        ),
    ],
)
def test_emitter_fails_closed_when_a_view_constraint_has_no_public_script_form(
    constraints, message
):
    sheet = _adopted_sheet()
    with pytest.raises(ValueError, match=message):
        emit_sheet_script(
            sheet.model(),
            "part",
            "bad-view",
            title="T",
            number="N",
            view_constraints=constraints,
        )
