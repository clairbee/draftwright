"""#1155 — GRM-04 must use A4 and retain both Ø2.4 requirements."""

from pathlib import Path

from draftwright import build_drawing

_FIXTURE = Path(__file__).parent / "fixtures" / "grm04_drive_plate.step"


def _rect_union_area(rectangles):
    """Exact union area of axis-aligned page-space rectangles."""
    xs = sorted({x for x0, _y0, x1, _y1 in rectangles for x in (x0, x1)})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        spans = sorted((y0, y1) for rx0, y0, rx1, y1 in rectangles if rx0 < x1 and x0 < rx1)
        covered = 0.0
        lo = hi = None
        for y0, y1 in spans:
            if lo is None:
                lo, hi = y0, y1
            elif y0 <= hi:
                hi = max(hi, y1)
            else:
                covered += hi - lo
                lo, hi = y0, y1
        if lo is not None:
            covered += hi - lo
        area += (x1 - x0) * covered
    return area


def _occupied_ratio(drawing):
    rectangles = []
    for visible, hidden in drawing.views.values():
        for shape in (visible, hidden):
            if shape is not None:
                box = shape.bounding_box()
                rectangles.append((box.min.X, box.min.Y, box.max.X, box.max.Y))
    for name in drawing.annotations():
        box = drawing.get_annotation(name).bounding_box()
        rectangles.append((box.min.X, box.min.Y, box.max.X, box.max.Y))
    return _rect_union_area(rectangles) / (drawing.page_w * drawing.page_h)


def test_grm04_measured_replan_keeps_diameter_and_location_on_a4():
    drawing = build_drawing(_FIXTURE, title="GRM-04")

    assert (drawing.page_w, drawing.page_h) == (297.0, 210.0)
    assert drawing.scale == 5.0
    assert drawing.scale_decision["status"] == "automatic_replanned"
    assert _occupied_ratio(drawing) >= 0.25

    hole = next(
        feature
        for feature in drawing.model().features
        if feature.kind == "hole" and abs(feature.diameter - 2.4) < 1e-6
    )
    carried = {
        measurement.parameter
        for name in drawing.annotations()
        for measurement in drawing.registry.measurement_of(name)
        if measurement.feature is hole
    }
    assert {"bore.diameter", "location_off_axis.y", "location_off_axis.z"} <= carried
    assert any(
        "2.4" in str(getattr(drawing.get_annotation(name), "label", ""))
        for name in drawing.annotations()
    )
    assert not [
        issue
        for issue in drawing.lint()
        if issue.code.endswith("_dropped")
        or issue.code in {"annotation_overlap", "annotation_out_of_bounds", "view_overlap"}
    ]
