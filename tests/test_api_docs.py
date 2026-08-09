import inspect

from draftwright.sheet import _Control

_CONTROL_CHARACTERISTICS = {
    "straightness",
    "flatness",
    "circularity",
    "cylindricity",
    "profile_line",
    "profile_surface",
    "angularity",
    "perpendicularity",
    "parallelism",
    "position",
    "concentricity",
    "symmetry",
    "circular_runout",
    "total_runout",
}


def test_every_gdt_characteristic_has_its_own_reference_docstring():
    """A class-level summary cannot populate IDE help or the rendered method entry."""
    public_methods = {
        name
        for name, value in vars(_Control).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }
    assert public_methods == _CONTROL_CHARACTERISTICS
    assert all(inspect.getdoc(getattr(_Control, name)) for name in public_methods)
