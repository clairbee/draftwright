"""#1299 — automatic axial recovery may escalate to a larger standard sheet."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from build123d import Align, Cylinder, Pos, Rotation

import draftwright.builder as builder
from draftwright import build_drawing

GRM03 = Path("/Users/paul/steps/GRM-03_thumbwheel_drive_screw_AP242_PMI.step")
GRM03_SHA256 = "4b6462b9cc9f0d419250933bd77fb305f9cfebb7ec2b3f377008732876010a21"


def _five_step_grm_profile():
    align = (Align.CENTER, Align.CENTER, Align.MIN)
    segments = [
        Pos(0, 0, station) * Cylinder(radius, length, align=align)
        for station, radius, length in (
            (-3.2, 2.0, 3.2),
            (0.0, 3.0, 0.5),
            (0.5, 5.0, 2.0),
            (2.5, 2.5, 3.0),
            (5.5, 1.5, 20.0),
        )
    ]
    shaft = segments[0]
    for segment in segments[1:]:
        shaft += segment
    shaft -= Pos(0, 0, -3.2) * Cylinder(0.8, 8.0, align=align)
    return Rotation(0, 90, 0) * shaft


def test_incomplete_same_page_no_iso_recovery_escalates_to_complete_a3():
    drawing = build_drawing(_five_step_grm_profile(), pmi="off")

    assert (drawing.page_w, drawing.page_h) == (420.0, 297.0)
    assert drawing.scale == 5.0
    assert "iso" not in drawing.views
    assert drawing.scale_decision["status"] == "automatic_replanned"
    assert [
        (
            attempt["page"],
            attempt["status"],
            attempt["reason"],
            attempt.get("rejection"),
        )
        for attempt in drawing.scale_decision["attempts"]
    ] == [
        ((297.0, 210.0), "axial_coverage_incomplete", "remove_optional_iso", None),
        ((297.0, 210.0), "rejected", "remove_optional_iso", "axial_coverage_incomplete"),
        ((420.0, 297.0), "complete", "page_escalation_after_optional_iso", None),
    ]
    assert drawing.scale_decision["attempted_scales"] == (2.0, 2.0, 5.0)
    assert {
        drawing.get_annotation(name).label
        for name in drawing.annotations()
        if name.startswith("m_steplen")
    } == {"3.2", "0.5", "2", "3", "20"}
    assert not [
        issue
        for issue in drawing.lint()
        if issue.severity == "error"
        or issue.code
        in {
            "axial_length_missing",
            "annotation_overlap",
            "annotation_out_of_bounds",
            "view_overlap",
        }
        or issue.code.endswith("_dropped")
    ]


def test_no_iso_proposal_on_different_page_reselects_scale_for_original_page(monkeypatch):
    """A proposal's scale belongs to its own page, not to the original sheet."""

    calls = []

    class FakeDrawing:
        def __init__(self, *, page, scale, include_iso):
            self.page_w, self.page_h = page
            self.scale = scale
            self.views = {"front": object()}
            if include_iso:
                self.views["iso"] = object()
            self.solve_trace = None

        def model(self):
            return SimpleNamespace(authored_dimensions=None)

        def lint(self, *, physical=False):
            return ()

    def fake_one_pass(
        _step_file,
        *,
        scale,
        page,
        _include_iso,
        _analysis_sink,
        **_kwargs,
    ):
        calls.append({"scale": scale, "page": page, "include_iso": _include_iso})
        _analysis_sink(
            SimpleNamespace(
                arrangement=builder.ARRANGEMENTS[0],
                part=object(),
                prof=object(),
            )
        )
        if _include_iso:
            return FakeDrawing(page=(297.0, 210.0), scale=2.0, include_iso=True)
        if page is None:
            return FakeDrawing(page=(420.0, 297.0), scale=5.0, include_iso=False)
        assert page == (297.0, 210.0)
        return FakeDrawing(page=page, scale=2.0, include_iso=False)

    monkeypatch.setattr(builder, "_build_drawing_once", fake_one_pass)
    monkeypatch.setattr(
        builder,
        "lint_axial_coverage",
        lambda _part, drawing, *, prof: ("gap",) if "iso" in drawing.views else (),
    )

    drawing = builder.build_drawing(object())

    fixed_page_calls = [
        call for call in calls if not call["include_iso"] and call["page"] == (297.0, 210.0)
    ]
    assert fixed_page_calls == [{"scale": None, "page": (297.0, 210.0), "include_iso": False}]
    assert (drawing.page_w, drawing.page_h, drawing.scale) == (297.0, 210.0, 2.0)
    assert [
        (attempt["status"], attempt["reason"], attempt.get("rejection"))
        for attempt in drawing.scale_decision["attempts"]
    ] == [
        ("axial_coverage_incomplete", "remove_optional_iso", None),
        ("scale_proposal", "remove_optional_iso", None),
        ("complete", "remove_optional_iso", None),
    ]


def test_expected_larger_page_build_failure_is_recorded_before_next_page(monkeypatch):
    class FakeDrawing:
        def __init__(self, *, page, include_iso):
            self.page_w, self.page_h = page
            self.scale = 2.0
            self.views = {"front": object()}
            if include_iso:
                self.views["iso"] = object()
            self.solve_trace = None

        def model(self):
            return SimpleNamespace(authored_dimensions=None)

        def lint(self, *, physical=False):
            return ()

    def fake_one_pass(
        _step_file,
        *,
        page,
        _include_iso,
        _analysis_sink,
        **_kwargs,
    ):
        _analysis_sink(
            SimpleNamespace(
                arrangement=builder.ARRANGEMENTS[0],
                part=object(),
                prof=object(),
            )
        )
        if page == "A3":
            raise ValueError("drawing geometry degenerates on speculative A3")
        dimensions = {
            None: (297.0, 210.0),
            "A2": (594.0, 420.0),
        }[page]
        return FakeDrawing(page=dimensions, include_iso=_include_iso)

    monkeypatch.setattr(builder, "_build_drawing_once", fake_one_pass)
    monkeypatch.setattr(
        builder,
        "lint_axial_coverage",
        lambda _part, drawing, *, prof: ("gap",) if drawing.page_w == 297.0 else (),
    )

    drawing = builder.build_drawing(object())

    assert (drawing.page_w, drawing.page_h) == (594.0, 420.0)
    assert [
        (
            attempt["page"],
            attempt["status"],
            attempt["reason"],
            attempt.get("error"),
        )
        for attempt in drawing.scale_decision["attempts"]
    ] == [
        ((297.0, 210.0), "axial_coverage_incomplete", "remove_optional_iso", None),
        ((297.0, 210.0), "rejected", "remove_optional_iso", None),
        (
            (420.0, 297.0),
            "error",
            "page_escalation_after_optional_iso",
            "drawing geometry degenerates on speculative A3",
        ),
        ((594.0, 420.0), "complete", "page_escalation_after_optional_iso", None),
    ]

    def unexpected_one_pass(*args, page, **kwargs):
        if page == "A3":
            raise ValueError("invalid declared model")
        return fake_one_pass(*args, page=page, **kwargs)

    monkeypatch.setattr(builder, "_build_drawing_once", unexpected_one_pass)
    with pytest.raises(ValueError, match="invalid declared model"):
        builder.build_drawing(object())


def test_explicit_a4_remains_fixed_instead_of_escalating():
    drawing = build_drawing(_five_step_grm_profile(), page="A4", pmi="off")

    assert (drawing.page_w, drawing.page_h) == (297.0, 210.0)
    assert drawing.scale_decision["status"] == "automatic"
    assert all(attempt["page"] == (297.0, 210.0) for attempt in drawing.scale_decision["attempts"])
    assert [issue for issue in drawing.lint() if issue.code == "axial_length_missing"]


@pytest.mark.skipif(not GRM03.exists(), reason="local exact GRM-03 AP242 file absent")
def test_exact_grm03_recovers_all_axial_stations_on_a3_with_pmi_off():
    assert hashlib.sha256(GRM03.read_bytes()).hexdigest() == GRM03_SHA256
    drawing = build_drawing(GRM03, pmi="off")

    assert (drawing.page_w, drawing.page_h) == (420.0, 297.0)
    assert drawing.scale == 5.0
    assert "iso" not in drawing.views
    assert {
        drawing.get_annotation(name).label
        for name in drawing.annotations()
        if name.startswith("m_steplen")
    } == {"3.2", "0.5", "2", "3", "20"}
    assert not [
        issue
        for issue in drawing.lint()
        if issue.code == "axial_length_missing" or issue.code.endswith("_dropped")
    ]
