"""Executable honesty guards for the #1307 build profiler."""

import json
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize(
    ("worker_input", "worker_id"),
    (({"workerid": "gw0"}, "gw0"), (None, "main")),
)
def test_plugin_profiles_every_build_binding_and_test_phase(
    tmp_path, monkeypatch, worker_input, worker_id
):
    import draftwright
    import draftwright._build_profile as profile
    import draftwright.builder as builder
    import draftwright.sheet as sheet

    monkeypatch.setattr(profile, "_STATE", None)
    monkeypatch.setattr(profile, "_CURRENT_NODEID", "<collection>")
    monkeypatch.setattr(builder, "build_drawing", lambda value: ("builder", value))
    monkeypatch.setattr(builder, "_build_drawing_once", lambda value: ("once", value))
    monkeypatch.setattr(sheet, "build_drawing", lambda value: ("sheet", value))
    monkeypatch.setattr(draftwright, "build_drawing", builder.build_drawing)
    config = SimpleNamespace(
        workerinput=worker_input,
        option=SimpleNamespace(numprocesses=None),
        getoption=lambda _name: str(tmp_path),
    )

    profile.pytest_configure(config)
    profile.pytest_collection_finish(SimpleNamespace(items=[object(), object()]))
    profile.pytest_runtest_logstart("tests/test_part.py::test_build", ("test_part.py", 1, ""))
    assert draftwright.build_drawing("public") == ("builder", "public")
    assert builder.build_drawing("builder") == ("builder", "builder")
    assert sheet.build_drawing("sheet") == ("sheet", "sheet")
    assert builder._build_drawing_once("once") == ("once", "once")
    profile.pytest_runtest_logreport(
        SimpleNamespace(
            duration=0.25,
            nodeid="tests/test_part.py::test_build",
            when="call",
            outcome="passed",
        )
    )
    profile.pytest_runtest_logreport(
        SimpleNamespace(
            duration=0.001,
            nodeid="tests/test_part.py::test_build",
            when="teardown",
            outcome="passed",
        )
    )
    profile.pytest_runtest_logfinish("tests/test_part.py::test_build", ("test_part.py", 1, ""))
    profile.pytest_sessionfinish(SimpleNamespace(), 0)

    payload = json.loads((tmp_path / f"profile-{worker_id}.json").read_text())
    assert payload["worker_id"] == worker_id
    assert payload["collected"] == 2
    assert {(call["seam"], call["count"]) for call in payload["calls"]} == {
        ("builder.build_drawing", 2),
        ("sheet.build_drawing", 1),
        ("builder._build_drawing_once", 1),
    }
    assert payload["phases"] == [
        {
            "nodeid": "tests/test_part.py::test_build",
            "phase": "call",
            "seconds": 0.25,
            "outcome": "passed",
        }
    ]


def test_plugin_stays_inactive_without_output_or_in_the_xdist_controller(tmp_path, monkeypatch):
    import draftwright._build_profile as profile

    monkeypatch.setattr(profile, "_STATE", None)
    no_output = SimpleNamespace(getoption=lambda _name: None)
    profile.pytest_configure(no_output)
    assert profile._STATE is None

    controller = SimpleNamespace(
        option=SimpleNamespace(numprocesses=4),
        getoption=lambda _name: str(tmp_path),
    )
    profile.pytest_configure(controller)
    assert profile._STATE is None


def test_plugin_registers_its_output_option():
    import draftwright._build_profile as profile

    options = []
    group = SimpleNamespace(addoption=lambda *args, **kwargs: options.append((args, kwargs)))
    parser = SimpleNamespace(
        getgroup=lambda name: group if name == "draftwright-build-profile" else None
    )

    profile.pytest_addoption(parser)

    assert options == [
        (
            ("--build-profile-dir",),
            {"help": "write one Draftwright build profile JSON file per pytest-xdist worker"},
        )
    ]


def test_summary_rejects_a_directory_without_worker_profiles(tmp_path):
    with pytest.raises(ValueError, match="no worker profiles were written"):
        summarise_profiles(tmp_path, 42)
