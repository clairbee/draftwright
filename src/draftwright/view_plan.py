"""The views a drawing has, and where they sit — ADR 0018's representation slice.

Until now nothing owned the question *which views should exist*. The four orthographic views
were named at one site in `builder` with hardcoded cameras, their page positions came from
`Analysis` fields called `FV_X`/`PV_X`/`SV_X`, and `compose.choose_scale` did its layout
arithmetic from a docstring — "Layout columns: [front(x×z)] [side(y×z)] [iso] [title block]" —
rather than from anything a caller could inspect or change. The topology was real but implicit,
spread across three modules and stated in prose.

This module makes it a value. :class:`ViewSpec` is a semantic request — what a view shows, in
model terms, and nothing about the page. :class:`ResolvedViewPlan` is the immutable result — the
same specs plus the page geometry chosen for them. The split is ADR 0018 decision §1 ("one value
vocabulary, distinct request and result states"), and it is a split rather than one mutable
object because a resolved plan that can be edited in place is indistinguishable from a request,
which is how a layout comes to be silently relaxed.

**This slice changes no behaviour.** It describes the fixed front/plan/side/iso topology the
engine already builds, and the golden placement snapshots are the gate. Semantic view SELECTION
— dropping a view because nothing needs it, which is what the thin rotational plate in
`tests/test_issue_1130_view_planning_evidence.py` is waiting for — comes only once the
lifecycle, projection-convention and requirement-coverage invariants in ADR 0018's evidence list
are guarded. A representation nobody can yet vary is the point of the first slice: everything
above it stops reading the topology out of scattered fields, so the later change has one place
to happen.

Rank 0: this is a leaf. It describes views; it cannot reach the code that draws them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

#: The model axes a principal view projects onto the page, as ``(page_x, page_y)``.
#: Third-angle front shows model x across and z up; the plan shows x across and y up; the side
#: shows y across and z up. Held here rather than inferred from the camera because
#: `compose.choose_scale` needs to know which two model extents a view's block spans before any
#: geometry is projected, and deriving it from a camera vector at that point is how the mapping
#: came to be duplicated in a docstring in the first place.
_PRINCIPAL_PAGE_AXES = {
    "front": ("x", "z"),
    "plan": ("x", "y"),
    "side": ("y", "z"),
}


@dataclass(frozen=True)
class ViewSpec:
    """One view a drawing should contain, in model terms.

    Deliberately says nothing about the page: no position, no size, no scale. A spec is what a
    planner decides and a user may edit; where it lands is the resolver's answer, and mixing the
    two is what ADR 0018 §1 separates. `camera` and `up` are the projection request as
    `Drawing._add_view` already expresses it — a direction from the part and an up vector —
    while `page_axes` states which model extents the view's block spans, which is the fact
    layout arithmetic needs and cameras only imply.
    """

    name: str
    #: What the view is FOR. `principal` participates in projection-convention relationships and
    #: in the page/scale decision; `pictorial` (the iso) is orientation only and is fitted after
    #: the sheet is settled; `section` and `detail` are derived from another view. The kind is
    #: what makes "which views should exist" answerable — a principal view may be dropped only
    #: if nothing requires what it shows, and a pictorial one carries no requirements at all.
    kind: str
    camera: tuple[float, float, float] | None = None
    up: tuple[float, float, float] | None = None
    page_axes: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unknown view kind {self.kind!r}; expected one of {sorted(_KINDS)}")


_KINDS = frozenset({"principal", "pictorial", "section", "detail"})


@dataclass(frozen=True)
class ViewPlacement:
    """Where a resolved view's block sits on the page: centre and half-extents, in page mm."""

    cx: float
    cy: float
    hw: float
    hh: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.cx - self.hw, self.cy - self.hh, self.cx + self.hw, self.cy + self.hh)


@dataclass(frozen=True)
class ResolvedViewPlan:
    """The views a drawing has, their page geometry, and the sheet they were resolved onto.

    Immutable, and immutable on purpose: ADR 0018 §1 keeps the resolved result distinct from the
    editable request so a caller cannot mutate a snapshot and have it read as an authored
    constraint. Turning one back into constraints is an explicit conversion, not an attribute
    write.
    """

    specs: tuple[ViewSpec, ...]
    placements: Mapping[str, ViewPlacement]
    scale: float
    page: tuple[float, float]

    def __post_init__(self) -> None:
        names = [spec.name for spec in self.specs]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate view names in plan: {names}")
        object.__setattr__(self, "placements", MappingProxyType(dict(self.placements)))

    def spec(self, name: str) -> ViewSpec | None:
        return next((spec for spec in self.specs if spec.name == name), None)

    def of_kind(self, kind: str) -> tuple[ViewSpec, ...]:
        return tuple(spec for spec in self.specs if spec.kind == kind)

    @property
    def principal_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.specs if spec.kind == "principal")


def third_angle_principals() -> tuple[ViewSpec, ...]:
    """The front/plan/side set the engine has always built, as specs.

    Cameras are `None` here: they depend on the scaled part's centre and the projection
    distance, which only `builder` knows, so they are filled by :func:`resolve_from_analysis`'s
    caller. What this function fixes is the SET and its page-axis mapping — the part that was
    previously a sentence in `choose_scale`'s docstring.
    """
    return tuple(
        ViewSpec(name=name, kind="principal", page_axes=axes)
        for name, axes in _PRINCIPAL_PAGE_AXES.items()
    )


def principal_placements(analysis) -> dict[str, ViewPlacement]:
    """Where the principal view blocks sit, read from a finished `Analysis`.

    Split out from :func:`resolve_from_analysis` because the layout consumers need exactly this
    and nothing else. Building a whole plan for them would make them depend on `SCALE`,
    `PAGE_W` and `PAGE_H` as well — and it did: routing `compose._view_geom` through the full
    resolver broke a repack test that passes a minimal stub carrying only the position fields.
    The stub was right and the coupling was wrong; a consumer that needs placements should ask
    for placements.
    """
    return {
        "front": ViewPlacement(analysis.FV_X, analysis.FV_Y, analysis.fv_hw, analysis.fv_hh),
        "plan": ViewPlacement(analysis.PV_X, analysis.PV_Y, analysis.fv_hw, analysis.pv_hh),
        "side": ViewPlacement(analysis.SV_X, analysis.SV_Y, analysis.sv_hw, analysis.fv_hh),
    }


def resolve_from_analysis(analysis) -> ResolvedViewPlan:
    """Read the plan the engine has already decided out of a finished `Analysis`.

    The bridge for this slice, and the reason it changes no behaviour: `Analysis` already
    carries the resolved answer, spread over `FV_X`/`PV_X`/`SV_X`, the matching `Y` fields, and
    the `fv_hw`/`sv_hw`/`fv_hh`/`pv_hh` half-extents. Reading it into one value lets every
    consumer stop reaching for those fields individually, without changing what any of them
    compute. When view selection becomes a real decision, this function is replaced by a
    resolver that *chooses*, and its callers do not move.

    The iso is included as a `pictorial` spec with no placement: it is fitted after the sheet is
    settled (`projection._fit_iso_view`), so at resolve time it genuinely has no page geometry,
    and recording a placeholder would be a claim the engine cannot honour.
    """
    placements = principal_placements(analysis)
    specs = third_angle_principals() + (ViewSpec(name="iso", kind="pictorial"),)
    return ResolvedViewPlan(
        specs=specs,
        placements=placements,
        scale=analysis.SCALE,
        page=(analysis.PAGE_W, analysis.PAGE_H),
    )
