"""#443 — GRM-03 must locate every turned shoulder on the automatic sheet."""

from pathlib import Path

from draftwright import build_drawing

_FIXTURE = Path(__file__).parent / "fixtures" / "grm03_thumbwheel_drive_screw.step"


def test_grm03_replans_optional_iso_for_truthful_step_lengths():
    drawing = build_drawing(_FIXTURE, title="PART")

    assert "iso" not in drawing.views
    assert drawing.scale == 5.0
    assert drawing.scale_decision["status"] == "automatic_replanned"
    assert drawing.scale_decision["attempted_scales"] == (2.0, 5.0, 5.0)
    assert [item["views"] for item in drawing.scale_decision["attempts"]] == [
        ("front", "plan", "side", "iso"),
        ("front", "plan", "side"),
        ("front", "plan", "side"),
    ]
    assert [item["status"] for item in drawing.scale_decision["attempts"]] == [
        "axial_coverage_incomplete",
        "scale_proposal",
        "complete",
    ]
    assert all(item["page"] == (297.0, 210.0) for item in drawing.scale_decision["attempts"])
    step_lengths = {
        drawing.get_annotation(name).label
        for name in drawing.annotations()
        if name.startswith("m_steplen")
    }
    assert {"0.5", "2", "3", "18"} <= step_lengths
    assert not [issue for issue in drawing.lint() if issue.code == "axial_length_missing"]


def test_axial_replan_is_disabled_without_automatic_dimensions():
    drawing = build_drawing(_FIXTURE, title="PART", auto_dims=False)

    assert "iso" in drawing.views
    assert drawing.scale_decision["attempts"] == ()
