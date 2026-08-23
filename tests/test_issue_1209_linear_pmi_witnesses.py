"""Regression coverage for truthful AP242 linear-reference witnesses (#1209)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from draftwright import extract_pmi_report
from draftwright.annotations.from_model import _pmi_witness_from_bbox
from draftwright.pmi import _linear_reference_stations

CTC04 = Path(__file__).parent / "fixtures" / "nist_ctc_04_asme1_ap242.stp"


@pytest.mark.parametrize(
    "value, stations",
    [
        (3.2, ((-3.2, 0.0, 0.0), (0.0, 0.0, 0.0))),
        (0.5, ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0))),
        (2.0, ((0.5, 0.0, 0.0), (2.5, 0.0, 0.0))),
        (3.0, ((2.5, 0.0, 0.0), (5.5, 0.0, 0.0))),
        (20.0, ((5.5, 0.0, 0.0), (25.5, 0.0, 0.0))),
    ],
)
def test_grm03_coaxial_end_faces_establish_their_x_station_span(value, stations):
    points, axis, blockers = _linear_reference_stations(stations, value)

    assert points == stations
    assert axis == "X"
    assert blockers == ()
    assert abs(points[1][0] - points[0][0]) == pytest.approx(value)


def test_an_oblique_or_one_sided_relationship_fails_closed_without_nominal_guessing():
    points, axis, blockers = _linear_reference_stations(
        ((0.0, 149.98174079291, -70.32125981157614), (0.0, 141.5491012236, -52.1456568216)),
        20.0,
    )
    assert len(points) == 2
    assert axis == "?"
    assert blockers and "not principal-axis aligned" in blockers[0]

    points, axis, blockers = _linear_reference_stations(
        ((0.0, 149.98174079291, -70.32125981157614), None), 25.0
    )
    assert len(points) == 1
    assert axis == "?"
    assert blockers == ("linear dimension needs two measurable authored reference groups",)

    points, axis, blockers = _linear_reference_stations(((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)), 20.0)
    assert len(points) == 2
    assert axis == "X"
    assert blockers == ("linear reference-station span 10 mm differs from nominal 20 mm",)


def test_ctc04_uses_authored_groups_and_reports_the_two_untruthful_records():
    report = extract_pmi_report(CTC04)
    records = {record.source_id: record for record in report.records if record.kind == "linear"}

    truthful = records["dimension:0:1:4:22"]
    assert truthful.value == 75.0
    assert truthful.dominant_axis == "Y"
    assert truthful.ref_pts == ((230.0, 285.0, 13.5), (230.0, 210.0, 13.5))
    assert truthful.lowering_blockers == ()

    oblique = records["dimension:0:1:4:26"]
    assert oblique.dominant_axis == "?"
    assert "not principal-axis aligned" in oblique.lowering_blockers[0]

    one_sided = records["dimension:0:1:4:29"]
    assert one_sided.dominant_axis == "?"
    assert len(one_sided.ref_pts) == 1
    assert one_sided.lowering_blockers == (
        "linear dimension needs two measurable authored reference groups",
    )

    outcomes = {source.source_id: source for source in report.sources}
    assert outcomes[truthful.source_id].outcome == "extracted"
    assert outcomes[oblique.source_id].outcome == "partially_extracted"
    assert outcomes[one_sided.source_id].outcome == "partially_extracted"


def test_linear_witness_uses_stations_while_bbox_supplies_only_transverse_support():
    def identity(value):
        return value

    analysis = SimpleNamespace(
        proj=SimpleNamespace(
            front_x=identity,
            front_z=identity,
            side_x=identity,
            side_z=identity,
            plan_x=identity,
            plan_y=identity,
        )
    )
    record = SimpleNamespace(
        dominant_axis="Y",
        ref_pts=((230.0, 285.0, 13.5), (230.0, 210.0, 13.5)),
        # The old witness used this outer Y span: 292 - 203 = 89, contradicting label 75.
        ref_bbox=(223.0, 203.0, 0.0, 237.0, 292.0, 27.0),
    )

    p1, p2, support = _pmi_witness_from_bbox(record, "side", analysis)

    assert abs(p2[0] - p1[0]) == 75.0
    assert support == 13.5

    short = SimpleNamespace(
        dominant_axis="X",
        ref_pts=((0.0, 0.0, 0.0), (0.5, 0.0, 0.0)),
        ref_bbox=(0.0, -5.0, -5.0, 0.5, 5.0, 5.0),
    )
    p1, p2, _support = _pmi_witness_from_bbox(short, "front", analysis)
    assert abs(p2[0] - p1[0]) == 0.5
