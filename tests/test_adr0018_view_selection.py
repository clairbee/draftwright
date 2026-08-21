"""ADR 0018: building a CHOSEN set of principal views, and what it costs.

The ADR's headline. Its delivery gate names two evidence items this module answers:

- *"Removing a truly redundant view retains every requirement and reduces the selected
  footprint."*
- *"Removing a visually similar but semantically necessary view is rejected by an asymmetric
  counterexample."*

Three things had to be true before either could be asked. A view's space had to be reclaimed
when it is dropped, or a smaller view set costs its annotations and stays on the same paper.
An extent had to be able to move to another view, because the overall width was pinned to
plan and vanished with it. And the decision had to be carried through every rebuild.

What this does NOT do is choose automatically: `_views` is an engine seam, not a public
option, and nothing yet drops a view on its own. The reason is measured below — on the ADR's
own case study the smaller view set reaches the target sheet and loses six annotations doing
it, so a gate weighing it would refuse. Naming what remains is the point of that test.
"""

import math

import pytest
from build123d import Box, Cylinder, Pos, Rot

from draftwright import build_drawing
from draftwright.compose import _layout_geometry
from draftwright.drawing import ViewNotPlanned
from draftwright.view_plan import VIEW_AXES, VIEWS_SHOWING, views_showing

ALL_THREE = ("front", "plan", "side")


def _z_hole():
    """A part whose only feature reads face-on in PLAN — so plan is necessary."""
    return Box(90, 60, 25) - Pos(20, 15, 0) * Cylinder(4, 30)


def _x_hole():
    """The asymmetric twin: same box, same one hole, drilled along X instead of Z.

    Visually similar and semantically opposite — here SIDE carries the feature and plan
    carries nothing that another view could not.
    """
    return Box(90, 60, 25) - Rot(0, 90, 0) * Cylinder(5, 120)


def _lint(drawing):
    return {issue.code for issue in drawing.lint()}


class TestTheObservabilityModel:
    """Which views COULD carry a requirement — the question droppability needs."""

    def test_every_view_lays_out_two_distinct_axes(self):
        for view, (horizontal, vertical) in VIEW_AXES.items():
            assert horizontal != vertical, view
            assert {horizontal, vertical} <= {"x", "y", "z"}

    def test_the_three_views_between_them_show_every_axis_twice(self):
        seen = [axis for axes in VIEW_AXES.values() for axis in axes]
        assert {axis: seen.count(axis) for axis in "xyz"} == {"x": 2, "y": 2, "z": 2}

    def test_views_showing_agrees_with_the_page_axes(self):
        # The derived map may not drift from the primitive it is derived from.
        for axis, views in VIEWS_SHOWING.items():
            assert set(views) == {v for v, axes in VIEW_AXES.items() if axis in axes}

    def test_the_horizontal_filter_excludes_a_view_that_shows_the_axis_vertically(self):
        # The distinction that matters for a below-strip extent dim: plan CONTAINS y, but
        # lays it out vertically, and dimensioning it there horizontally collapses the span
        # to zero length — measured as a degenerate-border ValueError.
        assert "plan" in VIEWS_SHOWING["y"]
        # Unfiltered, plan is a legitimate answer — it genuinely shows the y extent.
        assert views_showing("y", ("plan",)) == "plan"
        # Filtered, it is not, and that difference is the whole reason the flag exists.
        assert views_showing("y", ("plan",), horizontal=True) is None
        assert views_showing("y", ALL_THREE, horizontal=True) == "side"

    def test_it_prefers_the_view_each_extent_has_always_used(self):
        # Consulting the model may not move anything while all three principals are planned.
        assert views_showing("x", ALL_THREE, horizontal=True) == "plan"
        assert views_showing("y", ALL_THREE, horizontal=True) == "side"

    def test_it_falls_back_when_the_preferred_view_is_gone(self):
        assert views_showing("x", ("front", "side"), horizontal=True) == "front"


class TestTheLayoutReclaimsADroppedView:
    def test_dropping_the_plan_view_frees_its_height(self):
        # Without this the whole exercise is pointless: the drawing loses a view and stays on
        # the same paper.
        full = _layout_geometry(90.0, 60.0, 25.0, 1.0, 297.0, 210.0, 120.0, None, 0)
        two = _layout_geometry(
            90.0, 60.0, 25.0, 1.0, 297.0, 210.0, 120.0, None, 0, views=("front", "side")
        )
        assert two.FV_Y > full.FV_Y, "the front view did not move into the reclaimed band"

    def test_the_default_is_unchanged(self):
        explicit = _layout_geometry(
            90.0, 60.0, 25.0, 1.0, 297.0, 210.0, 120.0, None, 0, views=ALL_THREE
        )
        implied = _layout_geometry(90.0, 60.0, 25.0, 1.0, 297.0, 210.0, 120.0, None, 0)
        assert explicit.FV_Y == implied.FV_Y
        assert explicit.auto_fits == implied.auto_fits


class TestTheAsymmetricCounterexample:
    """Same box, same single hole, different axis — opposite verdicts."""

    def test_a_view_the_features_need_is_refused(self):
        with pytest.raises(ViewNotPlanned) as caught:
            build_drawing(_z_hole(), _views=("front", "side"))
        assert caught.value.view == "plan"

    def test_the_same_view_is_droppable_when_the_feature_turns(self):
        # The asymmetry: identical geometry apart from the hole's axis. Dropping plan is
        # refused above and clean here, so the verdict tracks what the view CARRIES rather
        # than what it looks like.
        drawing = build_drawing(_x_hole(), _views=("front", "side"))
        assert sorted(drawing.views) == ["front", "iso", "side"]
        assert not [code for code in _lint(drawing) if code.endswith("_dropped")]

    def test_dropping_the_view_the_x_hole_needs_is_refused_in_turn(self):
        # The other half of the asymmetry, so neither result is an accident of which view
        # happens to be named: for this part SIDE is the necessary one.
        with pytest.raises(ViewNotPlanned) as caught:
            build_drawing(_x_hole(), _views=("front", "plan"))
        assert caught.value.view == "side"


class TestAnExtentMovesOrIsReported:
    def test_the_overall_width_re_homes_to_the_front_when_plan_goes(self):
        # It was pinned to plan and would have vanished with it.
        drawing = build_drawing(_x_hole(), _views=("front", "side"))
        assert "m_env_width" in drawing.annotations()
        assert "m_env_depth" in drawing.annotations()

    def test_an_extent_no_planned_view_can_show_is_reported_not_dropped(self):
        # Depth reads horizontally ONLY in side. Without it the extent cannot be drawn, and
        # ADR 0016 Amdt 6 says it must be reported against its measurement rather than
        # disappear — which is also the signal a requirement gate weighs.
        drawing = build_drawing(Box(90, 60, 25), _views=("front", "plan"))
        assert "m_env_depth" not in drawing.annotations()
        assert "overall_dim_withheld" in _lint(drawing)
        assert "m_env_width" in drawing.annotations(), "the width must still be drawn"


class TestTheDecisionSurvivesEveryRebuild:
    def test_a_rebuild_does_not_revert_the_view_set(self):
        # The arrangement gate's fallback rebuild silently restored four views on a larger
        # sheet, because it re-entered the builder without the view set. Same defect class
        # as the carried arrangement, one stage further out.
        drawing = build_drawing(_x_hole(), _views=("front", "side"))
        assert "plan" not in drawing.views
        assert len(drawing.arrangement_decision["attempts"]) >= 1


class TestTheCaseStudy:
    """ADR 0018's motivating part, measured rather than asserted from the ADR's prose."""

    @staticmethod
    def _plate():
        part = Rot(0, 90, 0) * Cylinder(108.5, 12)
        part += Rot(0, 90, 0) * Pos(0, 0, 12) * Cylinder(45, 18)
        part += Rot(0, 90, 0) * Pos(0, 0, 28.75) * Cylinder(28, 15.5)
        part -= Rot(0, 90, 0) * Cylinder(16, 60)
        part -= Pos(30, 0, 0) * Box(60, 8, 20)
        for index in range(6):
            angle = index * math.pi / 3
            part -= (
                Rot(0, 90, 0)
                * Pos(85 * math.cos(angle), 85 * math.sin(angle), 0)
                * Cylinder(6, 40)
            )
        for index in range(4):
            angle = index * math.pi / 2 + math.pi / 4
            part -= (
                Rot(0, 90, 0)
                * Pos(60 * math.cos(angle), 60 * math.sin(angle), 0)
                * Cylinder(4.5, 40)
            )
        return part

    @pytest.mark.slow
    def test_the_smaller_view_set_reaches_a2_and_what_it_costs(self):
        part = self._plate()
        full = build_drawing(part)
        reduced = build_drawing(part, _views=("front", "side"))

        # The ADR's failure: the fixed four-view topology drives A1 at 1:1.
        assert (full.page_w, full.page_h) == (841.0, 594.0)
        assert full.scale == 1.0

        # Dropping the redundant plan reaches the ADR's target sheet at the same scale.
        assert (reduced.page_w, reduced.page_h) == (594.0, 420.0)
        assert reduced.scale == full.scale

        # And this is why nothing selects it automatically yet. The smaller sheet loses
        # annotations, so a requirement gate weighing this candidate would reject it. The
        # remaining work is re-homing those to the axial view — not the layout, which now
        # does its part. This test is written to change shape when that lands.
        assert len(reduced.annotations()) < len(full.annotations())
        assert {"callout_dropped", "annotation_out_of_bounds"} & _lint(reduced)

    @pytest.mark.slow
    def test_dropping_the_front_view_refuses_by_name_rather_than_crashing(self):
        # The diameter row is anchored under the front elevation and unpacked
        # `view_bounds("front")` directly — safe under a fixed four-view topology, a
        # `TypeError: cannot unpack non-iterable NoneType` the moment a view set omits it.
        # `view_bounds` has documented `None` for an absent view since #28.
        #
        # This part is the cheapest thing that reaches that code with the front view gone:
        # it needs enough diameters for the row to be attempted at all, and the parts small
        # enough to be fast return early on an empty item list. The distinction the
        # assertion draws is TypeError (crashed inside a pass) vs ViewNotPlanned (refused,
        # naming the view) — a view set must be REFUSABLE for a gate to weigh it.
        with pytest.raises(ViewNotPlanned) as caught:
            build_drawing(self._plate(), _views=("plan", "side"))
        assert caught.value.view == "front"
