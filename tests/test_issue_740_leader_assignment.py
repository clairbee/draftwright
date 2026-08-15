"""#740 — bounded collect-then-assign for machined-feature leader callouts."""

import json
import random
from itertools import combinations, product
from math import hypot
from types import SimpleNamespace

import pytest
from build123d import Cylinder
from build123d_drafting.helpers import Draft, Leader

from draftwright import ScaleCompletenessWarning, build_drawing
from draftwright.annotations._common import _box_hits, annotation_obstacle_boxes
from draftwright.layout import _assign_leader_candidates
from draftwright.model import FilletFeature, Frame, GrooveFeature, PartModel


def test_pure_assignment_maximises_cardinality_before_leader_length():
    result = _assign_leader_candidates(
        ((20.0, 21.0), (20.0,)),
        ((0, 0, 1, 0),),
    )

    assert result.choices == (1, 0)
    assert result.optimal


def test_pure_assignment_minimises_length_at_equal_cardinality():
    result = _assign_leader_candidates(
        ((9.0, 1.0), (8.0, 2.0)),
        (),
    )

    assert result.choices == (1, 1)
    assert result.optimal


def test_sub_micron_cost_noise_reaches_stable_candidate_order_tie_break():
    result = _assign_leader_candidates(((10.0 + 1e-12, 10.0),), ())

    assert result.choices == (0,)


@pytest.mark.parametrize(
    ("costs", "conflicts", "max_states", "message"),
    (
        (((1.0,),), (), 0, "max_states"),
        (((-1.0,),), (), 1, "finite and non-negative"),
        (((float("nan"),),), (), 1, "finite and non-negative"),
        (((1.0,), (1.0,)), ((0, 0, 1),), 1, "four indices"),
        (((1.0,), (1.0,)), ((0, 0, 2, 0),), 1, "job index"),
        (((1.0,), (1.0,)), ((0, 1, 1, 0),), 1, "candidate index"),
    ),
)
def test_pure_assignment_rejects_malformed_numeric_inputs(costs, conflicts, max_states, message):
    with pytest.raises(ValueError, match=message):
        _assign_leader_candidates(costs, conflicts, max_states=max_states)


def test_same_job_conflict_is_redundant_with_one_candidate_per_job():
    result = _assign_leader_candidates(((1.0, 2.0),), ((0, 0, 0, 1),))

    assert result.choices == (0,)
    assert result.optimal
    assert result.states == 1


def test_bounded_solver_matches_exhaustive_lexicographic_oracle():
    rng = random.Random(740)
    for _case in range(250):
        costs = tuple(
            tuple(rng.randrange(0, 20) / 10 for _ in range(rng.randrange(4)))
            for _ in range(rng.randrange(1, 6))
        )
        conflicts = tuple(
            (left_job, left_candidate, right_job, right_candidate)
            for left_job in range(len(costs))
            for right_job in range(left_job + 1, len(costs))
            for left_candidate in range(len(costs[left_job]))
            for right_candidate in range(len(costs[right_job]))
            if rng.random() < 0.2
        )
        blocked = {
            ((left_job, left_candidate), (right_job, right_candidate))
            for left_job, left_candidate, right_job, right_candidate in conflicts
        }

        def score(choices):
            count = sum(choice is not None for choice in choices)
            cost = sum(
                int(round(costs[job][choice] * 1000))
                for job, choice in enumerate(choices)
                if choice is not None
            )
            tie = tuple(
                len(costs[job]) if choice is None else choice for job, choice in enumerate(choices)
            )
            return (-count, cost, tie)

        feasible = []
        domains = [(*range(len(job)), None) for job in costs]
        for choices in product(*domains):
            selected = [(job, choice) for job, choice in enumerate(choices) if choice is not None]
            if any(
                (left, right) in blocked
                for index, left in enumerate(selected)
                for right in selected[index + 1 :]
            ):
                continue
            feasible.append(choices)
        expected = min(feasible, key=score)

        result = _assign_leader_candidates(costs, conflicts)

        assert result.optimal
        assert result.choices == expected


def test_state_budget_retains_the_legacy_greedy_incumbent():
    result = _assign_leader_candidates(
        ((20.0, 21.0), (20.0,)),
        ((0, 0, 1, 0),),
        max_states=1,
    )

    assert result.choices == (0, None)
    assert not result.optimal
    assert result.states == 1


def test_production_state_budget_is_a_load_bearing_work_bound():
    rng = random.Random(1060)
    conflicts = [
        (left, 0, right, 0)
        for left in range(32)
        for right in range(left + 1, 32)
        if rng.random() < 0.15
    ]

    result = _assign_leader_candidates([(1.0,)] * 32, conflicts)

    assert not result.optimal
    assert result.states == 100_000
    assert sum(choice is not None for choice in result.choices) >= 1


def test_dense_conflicted_inventory_has_a_nonrecursive_greedy_floor():
    conflicts = [(index, 0, index + 1, 0) for index in range(256)]
    result = _assign_leader_candidates([(1.0,)] * 257, conflicts)

    assert sum(choice is not None for choice in result.choices) == 129
    assert not result.optimal
    assert result.states == 0


def test_real_leader_geometry_makes_the_counterexample_load_bearing():
    draft = Draft()
    first = Leader(tip=(10.0, 10.0, 0.0), elbow=(30.0, 10.0, 0.0), label="A", draft=draft)
    alternate = Leader(tip=(10.0, 30.0, 0.0), elbow=(31.0, 30.0, 0.0), label="A", draft=draft)
    constrained = Leader(tip=(50.0, 10.0, 0.0), elbow=(30.0, 10.0, 0.0), label="B", draft=draft)
    drawing = SimpleNamespace(draft=draft)

    assert _box_hits(constrained.label_bbox, annotation_obstacle_boxes(drawing, first))
    assert not _box_hits(
        constrained.label_bbox,
        annotation_obstacle_boxes(drawing, alternate),
    )
    lengths = tuple(
        sum(hypot(end[0] - start[0], end[1] - start[1]) for start, end in leader.segments)
        for leader in (first, alternate, constrained)
    )
    result = _assign_leader_candidates(
        ((lengths[0], lengths[1]), (lengths[2],)),
        ((0, 0, 1, 0),),
    )

    assert result.choices == (1, 0)


def _crowded_declared_grooves():
    shaft = Cylinder(10, 60)
    grooves = [
        GrooveFeature(Frame((0.0, 0.0, z), "z"), "z", 2.0, 14.0 + index)
        for index, z in enumerate((-2.0, 0.0, 2.0))
    ]
    return shaft, PartModel(shaft.bounding_box(), "z", grooves)


def _groove_leader_evidence(drawing):
    names = sorted(name for name in drawing.annotations() if name.startswith("m_groove"))
    lengths = {
        name: sum(
            hypot(end[0] - start[0], end[1] - start[1])
            for start, end in drawing.get_annotation(name).segments
        )
        for name in names
    }
    measurements = {name: drawing.measurement_keys(name) for name in names}
    return names, lengths, measurements


def test_public_render_uses_joint_minimum_length_and_pair_budget_is_legacy_floor(
    monkeypatch, tmp_path
):
    part, model = _crowded_declared_grooves()
    joint = build_drawing(part, model=model, page="A4")
    joint_names, joint_lengths, joint_measurements = _groove_leader_evidence(joint)
    joint_boxes = {name: joint.get_annotation(name).label_bbox for name in joint_names}

    # The three shortest independent choices would be horizontal and their
    # 2.25-mm-high labels would overlap at these 2-mm stations. The production
    # conflict lowering must make one leader diagonal while retaining all three.
    assert all(
        not _box_hits(joint_boxes[left], [joint_boxes[right]])
        for left, right in combinations(joint_names, 2)
    )
    assert (
        sum(
            abs(end[1] - start[1]) > 1e-6
            for name in joint_names
            for start, end in joint.get_annotation(name).segments[:1]
        )
        == 1
    )

    # Force the real public renderer through its deterministic pre-quadratic
    # fallback. This is the pre-#740 first-clear result, not a parallel test
    # implementation of it.
    monkeypatch.setattr(
        "draftwright.annotations.from_model._LEADER_ASSIGN_MAX_PAIR_PROBES",
        0,
    )
    trace_path = tmp_path / "legacy.json"
    legacy = build_drawing(part, model=model, page="A4", trace=trace_path)
    legacy_names, legacy_lengths, legacy_measurements = _groove_leader_evidence(legacy)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    event = next(item for item in trace["pass_events"] if item["label"] == "groove_callouts")

    assert joint_names == legacy_names == ["m_groove_z0", "m_groove_z1", "m_groove_z2"]
    assert joint_measurements == legacy_measurements
    assert all(joint.registry.feature_of(name) is not None for name in joint_names)
    assert sum(joint_lengths.values()) < sum(legacy_lengths.values())
    assert event["assignment"] == "greedy_pair_budget"
    assert event["optimal"] is False
    assert not [issue for issue in joint.lint() if issue.code == "groove_dropped"]
    assert not [issue for issue in legacy.lint() if issue.code == "groove_dropped"]

    # The pass-size bound fires before collect-all OCC construction. Lower the
    # production constant to make that branch load-bearing on the same public
    # fixture without manufacturing hundreds of CAD annotations in CI.
    monkeypatch.setattr("draftwright.annotations.from_model._LEADER_ASSIGN_MAX_JOBS", 2)
    job_trace_path = tmp_path / "legacy-job-budget.json"
    job_floor = build_drawing(part, model=model, page="A4", trace=job_trace_path)
    job_names, _job_lengths, job_measurements = _groove_leader_evidence(job_floor)
    job_trace = json.loads(job_trace_path.read_text(encoding="utf-8"))
    job_event = next(
        item for item in job_trace["pass_events"] if item["label"] == "groove_callouts"
    )

    assert job_names == legacy_names
    assert job_measurements == legacy_measurements
    assert job_event["assignment"] == "greedy_job_budget"
    assert job_event["optimal"] is False


def test_grouped_job_candidate_budget_precedes_occ_construction(monkeypatch, tmp_path):
    shaft = Cylinder(10, 20)
    fillets = [FilletFeature(Frame((10.0, 0.0, 10.0), "z"), "z", 1.0) for _index in range(257)]
    created = 0

    def counted_leader(*args, **kwargs):
        nonlocal created
        created += 1
        return Leader(*args, **kwargs)

    monkeypatch.setattr("draftwright.annotations.from_model.Leader", counted_leader)
    trace_path = tmp_path / "candidate-budget.json"
    drawing = build_drawing(
        shaft,
        model=PartModel(shaft.bounding_box(), "z", fillets),
        page="A4",
        trace=trace_path,
    )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    event = next(item for item in trace["pass_events"] if item["label"] == "fillet_callouts")
    annotation = drawing.get_annotation("m_fillet_z0")

    assert created == 1  # the legacy first-clear floor, not all 257 OCC alternatives
    assert annotation.label == "257× R1"
    assert len(drawing.measurement_keys("m_fillet_z0")) == 257
    assert event["assignment"] == "greedy_candidate_budget"
    assert event["optimal"] is False


def test_grouped_job_at_candidate_budget_still_uses_joint_assignment(monkeypatch, tmp_path):
    shaft = Cylinder(10, 20)
    fillets = [FilletFeature(Frame((10.0, 0.0, 10.0), "z"), "z", 1.0) for _index in range(2)]
    created = 0

    def counted_leader(*args, **kwargs):
        nonlocal created
        created += 1
        return Leader(*args, **kwargs)

    monkeypatch.setattr("draftwright.annotations.from_model._LEADER_ASSIGN_MAX_CANDIDATES", 2)
    monkeypatch.setattr("draftwright.annotations.from_model.Leader", counted_leader)
    trace_path = tmp_path / "candidate-budget-boundary.json"
    drawing = build_drawing(
        shaft,
        model=PartModel(shaft.bounding_box(), "z", fillets),
        page="A4",
        trace=trace_path,
    )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    event = next(item for item in trace["pass_events"] if item["label"] == "fillet_callouts")

    assert created == 2
    assert drawing.get_annotation("m_fillet_z0").label == "2× R1"
    assert event["assignment"] == "joint"
    assert event["optimal"] is True


def test_trace_identifies_a_joint_conflict_between_fixed_clear_candidates(tmp_path):
    shaft = Cylinder(10, 60)
    grooves = [
        GrooveFeature(Frame((0.0, 0.0, 0.0), "z"), "z", 2.0, 14.0 + index * 0.1)
        for index in range(6)
    ]
    trace_path = tmp_path / "joint-conflict.json"

    with pytest.warns(ScaleCompletenessWarning, match="groove_dropped"):
        build_drawing(
            shaft,
            model=PartModel(shaft.bounding_box(), "z", grooves),
            page="A4",
            scale=1,
            scale_policy="permissive",
            trace=trace_path,
        )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    event = next(item for item in trace["pass_events"] if item["label"] == "groove_callouts")
    dropped = [item for item in event["items"] if item["outcome"] == "dropped"]
    assert len(dropped) == 1
    assert dropped[0]["viable_candidates"] == 5
    assert dropped[0]["reason"] == "assignment_conflict"


def test_bounded_legacy_fallback_preserves_drop_diagnostic(monkeypatch, tmp_path):
    shaft = Cylinder(10, 60)
    grooves = [
        GrooveFeature(Frame((0.0, 0.0, 0.0), "z"), "z", 2.0, 14.0 + index * 0.1)
        for index in range(6)
    ]
    monkeypatch.setattr(
        "draftwright.annotations.from_model._LEADER_ASSIGN_MAX_PAIR_PROBES",
        0,
    )
    trace_path = tmp_path / "greedy-drop.json"

    with pytest.warns(ScaleCompletenessWarning, match="groove_dropped"):
        drawing = build_drawing(
            shaft,
            model=PartModel(shaft.bounding_box(), "z", grooves),
            page="A4",
            scale=1,
            scale_policy="permissive",
            trace=trace_path,
        )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    event = next(item for item in trace["pass_events"] if item["label"] == "groove_callouts")
    dropped = [item for item in event["items"] if item["outcome"] == "dropped"]
    issues = [issue for issue in drawing.registry.issues if issue.code == "groove_dropped"]

    assert len([name for name in drawing.annotations() if name.startswith("m_groove")]) == 5
    assert event["assignment"] == "greedy_pair_budget"
    assert event["optimal"] is False
    assert len(dropped) == 1
    assert dropped[0]["name"] == "m_groove_z5"
    assert dropped[0]["label"] == "2 WIDE × ø14.5"
    assert dropped[0]["candidates_tried"] == 8
    assert dropped[0]["reason"] == "no_clear_room"
    assert len(issues) == 1
    assert len(issues[0].measurement_ids) == 2
