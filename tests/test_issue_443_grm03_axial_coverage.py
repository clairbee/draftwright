"""#443 — GRM-03 must locate every turned shoulder on the automatic sheet."""

from pathlib import Path

from draftwright import build_drawing

_FIXTURE = Path(__file__).parent / "fixtures" / "grm03_thumbwheel_drive_screw.step"


def test_grm03_replans_optional_iso_for_truthful_step_lengths():
    drawing = build_drawing(_FIXTURE, title="PART")

    assert "iso" not in drawing.views
    assert drawing.scale == 5.0
    assert drawing.scale_decision["status"] == "automatic_replanned"
    step_lengths = {
        drawing.get_annotation(name).label
        for name in drawing.annotations()
        if name.startswith("m_steplen")
    }
    assert {"0.5", "2", "3", "18"} <= step_lengths
    assert not [issue for issue in drawing.lint() if issue.code == "axial_length_missing"]
