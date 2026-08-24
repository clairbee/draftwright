"""Executable honesty guards for the #1307 build profiler."""

import json
from pathlib import Path

import pytest

from draftwright._build_profile import _ProfileState, build_pytest_command, summarise_profiles


def _worker(path: Path, worker: str, collected: int, *, count: int = 2, seconds: float = 1.5):
    payload = {
        "worker_id": worker,
        "collected": collected,
        "exitstatus": 0,
        "calls": [
            {
                "nodeid": "tests/test_example.py::test_it",
                "seam": "builder.build_drawing",
                "count": count,
                "seconds": seconds,
            }
        ],
        "phases": [],
    }
    (path / f"profile-{worker}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_pytest_command_preserves_each_module_as_a_literal_argument(tmp_path):
    modules = ["tests/test_a.py", "tests/a module with spaces.py", "-n", "auto"]
    command = build_pytest_command(tmp_path, modules)
    assert command[-len(modules) :] == modules
    assert " ".join(modules) not in command


def test_summary_aggregates_workers_only_after_their_collection_counts_match(tmp_path):
    _worker(tmp_path, "gw0", 42)
    _worker(tmp_path, "gw1", 42, count=3, seconds=2.25)

    summary = summarise_profiles(tmp_path, 42)

    assert summary == {
        "expected_collected": 42,
        "workers": ["gw0", "gw1"],
        "seams": {"builder.build_drawing": {"count": 5, "seconds": 3.75}},
    }


@pytest.mark.parametrize("collected", (0, 41, None))
def test_summary_rejects_empty_partial_or_missing_collection_censuses(tmp_path, collected):
    _worker(tmp_path, "gw0", collected)
    with pytest.raises(ValueError, match=r"collected .* expected 42"):
        summarise_profiles(tmp_path, 42)


def test_worker_profile_contains_call_and_slow_phase_evidence(tmp_path, monkeypatch):
    import draftwright._build_profile as profile

    state = _ProfileState(tmp_path, "gw/unsafe")
    state.collected = 7
    monkeypatch.setattr(profile, "_CURRENT_NODEID", "tests/test_part.py::test_build")
    state.record_call("builder._build_drawing_once", 0.25)
    state.phases.append(
        {
            "nodeid": "tests/test_part.py::test_build",
            "phase": "call",
            "seconds": 0.5,
            "outcome": "passed",
        }
    )

    path = state.write(0)
    payload = json.loads(path.read_text())

    assert path.name == "profile-gw_unsafe.json"
    assert payload["collected"] == 7
    assert payload["calls"] == [
        {
            "count": 1,
            "nodeid": "tests/test_part.py::test_build",
            "seam": "builder._build_drawing_once",
            "seconds": 0.25,
        }
    ]
    assert payload["phases"][0]["seconds"] == 0.5
