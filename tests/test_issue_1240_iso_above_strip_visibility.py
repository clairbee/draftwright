"""#1240 — the above strips and the iso view must see each other.

`strip_obstacles` is annotations-only by documented design (views enter
`late_furniture_obstacles`), so strip placement never saw the iso; and `_fit_iso_view`
re-scales the iso AFTER `_auto_annotate` from the compose-time zone, so the fit never saw
annotations. Two blindnesses, one per direction. The right strips have been iso-clamped since
the zone carve; the above strips had only the per-pass `m_locy` special case.

**No natural fixture reaches the collision** — this was hunted hard, in the #1239 review
(forced-fallthrough sweep over six synthetic parts and all ten CTC fixtures) and again when
this was fixed (deep-Y parts, wide-X parts, pinned pages, forced starvation): compose plus
page/scale selection kept the iso zone horizontally separated from every populated above strip
every time. So these tests construct the geometry at the seam instead — a planted iso bbox for
the clamp, a planted obstacle box for the grow cap — and each carries a control proving the
un-fixed behaviour differs, since a sweep that finds nothing cannot (#1216's lesson) be told
apart from a sweep that tests nothing.
"""

from __future__ import annotations

import math

from build123d import Box, Cylinder, Pos

from draftwright._core import _iso_bbox
from draftwright.builder import build_drawing
from draftwright.projection import _iso_grow_cap


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _plate_with_locations():
    """Holes at distinct x/y so location dims populate the plan/side above strips."""
    part = Box(120, 70, 12)
    for x, y in ((-40, 20), (-10, -15), (25, 5), (45, -25)):
        part -= Pos(x, y, 0) * Cylinder(3.5, 40)
    return part


def test_the_grow_cap_geometry():
    """`_iso_grow_cap` — pure interval arithmetic, hand-checked.

    bb (90,90)-(110,110) about centre (100,100): each edge is 10 from the centre.
    """
    bb = (90.0, 90.0, 110.0, 110.0)
    # No obstacles: unbounded.
    assert _iso_grow_cap(bb, 100, 100, []) == math.inf
    # A box whose left edge is 30 right of centre: x-onset at f=3; y straddles → onset 0.
    assert _iso_grow_cap(bb, 100, 100, [(130, 90, 140, 110)]) == 3.0
    # Same box, but y-separated too (above by 20 → y-onset f=2): overlap needs BOTH, so the
    # cap is max(3, 2) = 3 — the later axis governs.
    assert _iso_grow_cap(bb, 100, 100, [(130, 120, 140, 130)]) == 3.0
    # A box straddling the centre on both axes: no growth at all.
    assert _iso_grow_cap(bb, 100, 100, [(95, 95, 105, 105)]) == 0.0
    # Below the centre: y-onset (100-80)/(100-90) = 2; x straddles → cap 2.
    assert _iso_grow_cap(bb, 100, 100, [(90, 70, 110, 80)]) == 2.0
    # Several obstacles: the nearest governs.
    assert _iso_grow_cap(bb, 100, 100, [(130, 90, 140, 110), (90, 70, 110, 80)]) == 2.0


def test_iso_growth_is_capped_by_a_planted_annotation_box(monkeypatch):
    """The fit must not grow onto ink the caller reports — and must still grow up to it.

    The box is planted from MEASURED geometry, not guessed: a spy on the fit captures the
    pre-fit bbox, the control build gives the grown one, and the box goes at the midpoint of
    the growth corridor with its y-range straddling the iso centre (so the x onset alone
    governs). The first version of this test planted "just inside the grown corner", which
    OVERLAPPED the pre-fit bbox — the cap correctly refused all growth and the test read
    that as a failure.
    """
    from draftwright import builder as builder_mod
    from draftwright import projection as projection_mod

    part = Box(40, 30, 8) - Pos(-10, 5, 0) * Cylinder(3, 20) - Pos(10, -5, 0) * Cylinder(3, 20)

    prefit: list = []
    real_fit = projection_mod._fit_iso_view

    def spy_fit(dwg, a, obstacles=()):
        prefit.append(_iso_bbox(dwg))
        return real_fit(dwg, a, obstacles=obstacles)

    monkeypatch.setattr(builder_mod, "_fit_iso_view", spy_fit)

    control = build_drawing(part, title="T", number="N")
    grown = _iso_bbox(control)
    pre = prefit[0]
    cx, cy = (grown[0] + grown[2]) / 2, (grown[1] + grown[3]) / 2  # scaling preserves centre
    control_factor = (cx - grown[0]) / (cx - pre[0])
    assert control_factor > 1.15, (
        f"precondition: the control iso grew only {control_factor:.2f}x, leaving no corridor "
        "to plant an obstacle in"
    )
    # Midpoint of the growth corridor in factor space, thin, y-straddling the centre.
    fx_target = (1 + control_factor) / 2
    planted_right = cx - fx_target * (cx - pre[0])
    planted = (planted_right - 3.0, cy - 2.0, planted_right, cy + 2.0)
    assert _overlap(planted, grown) and not _overlap(planted, pre), (
        f"precondition: the box {planted} is not strictly inside the growth corridor "
        f"(pre {pre}, grown {grown})"
    )

    real = builder_mod.strip_obstacles

    def with_planted(dwg, *args, **kwargs):
        return list(real(dwg, *args, **kwargs)) + [planted]

    monkeypatch.setattr(builder_mod, "strip_obstacles", with_planted)
    prefit.clear()
    capped = build_drawing(part, title="T", number="N")
    capped_bb = _iso_bbox(capped)
    assert not _overlap(planted, capped_bb), (
        f"the fit grew onto a reported obstacle: iso={capped_bb} obstacle={planted}"
    )
    assert capped_bb[0] >= planted[2] - 1e-6, (
        f"the iso's left edge {capped_bb[0]:.2f} crossed the obstacle's right edge "
        f"{planted[2]:.2f}"
    )
    # And the cap allowed growth rather than giving up: strictly wider than pre-fit, strictly
    # narrower than the unobstructed control.
    assert capped_bb[0] < prefit[0][0] - 0.25, (
        f"no growth at all (left edge {capped_bb[0]:.2f} vs pre-fit {prefit[0][0]:.2f}) — the "
        "cap is behaving as a veto, or the margins swallowed the corridor"
    )
    assert capped_bb[0] > grown[0], "the cap did not bind — the obstacle was not the constraint"


def test_the_above_strip_is_clamped_below_an_overlapping_iso(monkeypatch):
    """Strip placement must not stack under an iso that horizontally overlaps its view.

    A fake iso bbox is planted directly over the plan view, low enough that the location
    dims' natural stack would enter it (the control asserts they DO without the clamp —
    the defect, reproduced). With the clamp, nothing may be placed inside it.
    """
    from draftwright.annotations import orchestrator as orch
    from draftwright.annotations._common import annotation_obstacle_boxes

    part = _plate_with_locations()

    # Geometry first: where does the plan's above stack sit unclamped?
    base = build_drawing(part, title="T", number="N")
    pv = base.view_bounds("plan")
    assert pv is not None
    # The fake iso spans the plan's x-range with its bottom between the natural stack's
    # second and third tiers (measured: tier tops sit ~11/21/30/40 mm above the view top).
    # The clamp (bottom - 4) then admits tier 1 and refuses tier 3+ — so the un-clamped
    # control MUST enter the box (precondition) while a clamped build keeps a live,
    # non-empty strip below it (the last assertion, which a bottom set too low turns into
    # "the clamp emptied the strip", the first version's failure).
    fake = (pv[0] + 5, pv[3] + 24, pv[2] - 5, pv[3] + 70)

    real = orch._iso_bbox

    def fake_iso(dwg):
        return fake

    monkeypatch.setattr(orch, "_iso_bbox", fake_iso)
    clamped = build_drawing(part, title="T", number="N")
    monkeypatch.setattr(orch, "_iso_bbox", real)

    def boxes_in(drawing, region):
        hits = []
        for name, obj in drawing.iter_annotations():
            if getattr(obj, "is_sheet_frame", False) or getattr(obj, "is_zone_grid", False):
                continue
            for box in annotation_obstacle_boxes(drawing, obj):
                if _overlap(box, region):
                    hits.append(name)
        return sorted(set(hits))

    # The precondition, on the UN-clamped build: the natural stack enters the fake region —
    # otherwise the clamp assertion below is vacuous.
    assert boxes_in(base, fake), (
        f"precondition: no annotation enters {fake} even without the clamp, so this fixture "
        "does not reach the defect"
    )
    assert not boxes_in(clamped, fake), (
        f"annotations placed under the (planted) iso despite the clamp: {boxes_in(clamped, fake)}"
    )
    # The clamp must not have simply emptied the strip: something still placed below it.
    band = (pv[0], pv[3], pv[2], fake[1])
    assert boxes_in(clamped, band), (
        "nothing placed in the above strip at all — the clamp killed the strip rather than "
        "bounding it, or the fixture stopped using it"
    )
