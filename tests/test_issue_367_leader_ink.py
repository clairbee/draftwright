"""Regression coverage for #367's rendered leader-ink collision model."""

import math

import pytest
from build123d import HeadType, Vector
from build123d_drafting.helpers import ArrowHead, Draft, Leader

from draftwright._geometry import (
    _convex_polygon_overlaps_box,
    _leader_ink_crosses_box,
    _segment_crosses_box,
)
from draftwright.annotations.holes import _leader_hits


def _leader(draft, elbow=(20.0, 0.0)):
    tip = (0.0, 0.0)
    side = "right" if elbow[0] > 0 else "left"
    leader = Leader(tip=tip, elbow=elbow, label="X", draft=draft, text_side=side)
    return leader, tip, elbow, side


@pytest.mark.parametrize("head_type", tuple(HeadType))
@pytest.mark.parametrize("angle", (0.0, 35.0, -35.0, 145.0))
def test_arrowhead_flare_is_collision_evidence_beyond_the_idealised_segment(angle, head_type):
    draft = Draft(head_type=head_type)
    radians = math.radians(angle)
    unit = (math.cos(radians), math.sin(radians))
    normal = (-unit[1], unit[0])
    elbow = (20.0 * unit[0], 20.0 * unit[1])
    tip = (0.0, 0.0)
    sample = (
        unit[0] * draft.arrow_length * 0.83 + normal[0] * draft.arrow_length * 0.23,
        unit[1] * draft.arrow_length * 0.83 + normal[1] * draft.arrow_length * 0.23,
    )
    obstacle = (sample[0] - 0.05, sample[1] - 0.05, sample[0] + 0.05, sample[1] + 0.05)

    assert not _segment_crosses_box(tip, elbow, obstacle), (
        "fixture must miss the old zero-width centreline test"
    )
    arrow = ArrowHead(
        size=draft.arrow_length,
        head_type=head_type,
        rotation=angle + 180.0,
    )
    assert any(face.is_inside(Vector(sample[0], sample[1], 0.0)) for face in arrow.faces()), (
        f"fixture must intersect the real rendered {head_type.name.lower()} arrowhead"
    )
    assert _leader_ink_crosses_box(
        tip,
        elbow,
        obstacle,
        arrow_length=draft.arrow_length,
        line_width=draft.line_width,
    )


def test_annotation_side_leader_check_uses_the_rendered_arrow_ink():
    draft = Draft()
    leader, tip, elbow, side = _leader(draft)
    obstacle = (2.44, 0.64, 2.54, 0.74)

    assert not _segment_crosses_box(tip, elbow, obstacle)
    assert _leader_hits(leader, tip, elbow, side, (obstacle,), draft)


def test_arrowhead_clearance_is_local_to_the_tip_not_the_whole_shaft():
    draft = Draft()
    leader, tip, elbow, side = _leader(draft)
    obstacle = (9.9, 0.6, 10.1, 0.8)

    assert not any(face.is_inside(Vector(10.0, 0.7, 0.0)) for face in leader.faces())
    assert not _leader_hits(leader, tip, elbow, side, (obstacle,), draft)


def test_heavy_shaft_width_is_collision_evidence_beyond_the_centreline():
    draft = Draft(line_width=4.0, arrow_length=1.0)
    leader, tip, elbow, side = _leader(draft)
    obstacle = (9.9, 1.4, 10.1, 1.6)

    assert not _segment_crosses_box(tip, elbow, obstacle), (
        "fixture must miss the old zero-width centreline test"
    )
    assert any(face.is_inside(Vector(10.0, 1.5, 0.0)) for face in leader.faces()), (
        "fixture must intersect the real rendered shaft"
    )
    assert _leader_hits(leader, tip, elbow, side, (obstacle,), draft)


def test_zero_length_leader_uses_its_local_ink_extent():
    assert _leader_ink_crosses_box(
        (5.0, 5.0),
        (5.0, 5.0),
        (5.5, 4.9, 5.6, 5.1),
        arrow_length=3.0,
        line_width=0.5,
    )
    assert not _leader_ink_crosses_box(
        (5.0, 5.0),
        (5.0, 5.0),
        (6.1, 4.9, 6.2, 5.1),
        arrow_length=3.0,
        line_width=0.5,
    )


def test_arrow_and_shaft_components_can_be_disabled_independently():
    # Keep the two footprint branches independently load-bearing.  A zero style value is
    # a supported boundary for the pure geometry helper even though ordinary Draft values
    # render both components.
    assert _leader_ink_crosses_box(
        (0.0, 0.0),
        (20.0, 0.0),
        (2.4, 0.6, 2.6, 0.8),
        arrow_length=3.0,
        line_width=0.0,
    )
    assert _leader_ink_crosses_box(
        (0.0, 0.0),
        (20.0, 0.0),
        (9.9, 0.4, 10.1, 0.6),
        arrow_length=0.0,
        line_width=2.0,
    )
    assert not _leader_ink_crosses_box(
        (0.0, 0.0),
        (20.0, 0.0),
        (9.9, -0.1, 10.1, 0.1),
        arrow_length=0.0,
        line_width=0.0,
    )


def test_convex_overlap_ignores_a_repeated_polygon_vertex():
    polygon = ((0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
    assert _convex_polygon_overlaps_box(polygon, (1.0, 1.0, 3.0, 3.0))
