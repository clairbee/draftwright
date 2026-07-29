"""The compiled dimension plan — the only thing a dimensional renderer may draw from.

ADR 0016's boundary rule: **renderers may emit dimensional content only from the compiled
plan.** A renderer receives approved entries and decides *where* and *how* to draw them; it
does not decide *what*, and it is not given the feature inventory or the bounding box it
would need to decide differently.

The rule exists because the previous arrangement made honouring suppression a convention.
`plan_dimensions` marked a `PlannedDimension` suppressed, handed the whole group to a
renderer that also held the `PartModel` and the `Analysis`, and trusted it to check. Eight
adversarial review rounds on #921 found eight renderers that did not — the height ladder and
step positions rebuilding their marks from the feature and `a.bb`, the entire turned family
selecting parameters with no suppression check at all. Each was a real omission reaching a
real drawing, and each was fixed locally, which is how the fourth mechanism for saying the
same thing got added.

The structural answer is that **suppression is not a flag renderers check, it is content
they never receive**:

- :class:`ApprovedDimension` has no ``suppressed`` field. There is nothing to forget.
- What was *not* approved leaves through :attr:`RenderableDimensionPlan.diagnostics`.
  Omission stays inspectable — ADR 0016's "marked, not filtered" is preserved — but it is
  not on the path a renderer walks.

  **Nothing consumes diagnostics yet, and this is deliberately not claimed otherwise.**
  The consumer arrives with #921: an authored set is the first source of omissions that
  coverage must tell apart from a measurement simply missed, which is what
  ``Omission.authored`` exists for. Until then every omission here is a planner rule the
  lint layer already understands by other means, so wiring a consumer now would be
  connecting a channel to nothing. The owner is `linting/coverage.py`, at the #921 rebase.
- Correlated sets (a step-height ladder, a shoulder chain) arrive as explicit
  :class:`ApprovedLadder` groups, so a renderer never reconstructs one from a feature.

Where the boundary does NOT yet reach, stated so the exceptions cannot be mistaken for
completeness:

- **Location dimensions** are dimensions and belong inside it; `plan_locations` returns a
  flat cross-feature list that never enters a `DimensionGroup`, so they are sequenced later
  in this work rather than carved out (#883).
- **Raw AP242 PMI** is a documented non-generated exception: `PmiFeature.parameters()` is
  empty by design and the record is rendered verbatim, so there is no compiled content for
  it to come from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from draftwright._geometry import _fmt
from draftwright.model.ir import (
    EnvelopeFeature,
    Feature,
    PartModel,
    Point,
    RotationalFeature,
    StepLevelFeature,
)
from draftwright.model.planner import DimensionId, plan_dimensions

_AUTHORED_OMISSION = "not in the authored dimension set"


class FeatureRef:
    """An **opaque** provenance handle for the feature a dimension came from.

    Carrying the `Feature` itself on an approved entry would have left the whole bypass
    one attribute access away: a renderer could read `.levels`, `.base` or `.shoulders`
    off it and rebuild exactly the content the compiler withheld (#923 review). The AST
    guard proved only that today's renderer does not; the type still permitted it, and a
    boundary that relies on renderers not doing the thing they can trivially do is the
    convention this work exists to replace.

    So the handle exposes identity and category — enough for provenance tagging
    (ADR 0010), escalation grouping, and equality — and no measurement at all. The two
    consumers that legitimately need the object (the corridor provenance seam and the
    escalation resolver) call :func:`resolve_feature` where the object is the point.

    Python cannot make this airtight, and it is not pretending to: ``ref._feature`` still
    exists. What changes is that reading content now requires an obviously-wrong private
    access that the boundary guard greps for, rather than an innocuous ``.feature.levels``
    nobody would flag in review.
    """

    __slots__ = ("_feature",)

    _feature: Feature

    def __init__(self, feature: Feature) -> None:
        object.__setattr__(self, "_feature", feature)

    @property
    def kind(self) -> str:
        """The feature's category — ``"step_level"``, ``"envelope"``. Not a measurement."""
        return getattr(self._feature, "kind", "?")

    def __eq__(self, other) -> bool:
        return isinstance(other, FeatureRef) and other._feature is self._feature

    def __hash__(self) -> int:
        return id(self._feature)

    def __repr__(self) -> str:
        return f"FeatureRef({self.kind})"


def resolve_feature(ref):
    """The `Feature` behind a :class:`FeatureRef` — for provenance and escalation ONLY.

    Called at the seams where the feature object itself is the point: the corridor's
    ADR 0010 provenance map, and the escalation resolver's grouping. A dimensional
    renderer calling this is a boundary violation, and the guard says so."""
    if ref is None or not isinstance(ref, FeatureRef):
        return ref
    return ref._feature


@dataclass(frozen=True)
class ApprovedDimension:
    """One measurement the compiler approved for drawing.

    Deliberately has **no** ``suppressed`` field: this type exists only for dimensions that
    are drawn. A renderer holding one has nothing to decide about whether to draw it.

    ``span`` is in PART space; the renderer projects it. That is the split — the compiler
    says "this measurement, this value, between these two points"; the renderer says which
    view, which strip, which side, and what happens when it does not fit.
    """

    id: DimensionId | None
    label: str
    value: float
    span: tuple[Point, Point] | None
    ref: FeatureRef | None = None


@dataclass(frozen=True)
class ApprovedLadder:
    """A correlated set approved as a whole (ADR 0016 identity tier 3).

    A step-height ladder or shoulder chain is ONE addressable dimension holding N members,
    so it is approved or omitted whole — never half a staircase. Arriving as an explicit
    group is what stops a renderer rebuilding the members from `StepLevelFeature.levels`
    and the bounding box, which is exactly what `render_height_ladder` did.
    """

    kind: str  # "step_height" | "step_position" | "overall_height"
    rungs: tuple[ApprovedDimension, ...]
    ref: FeatureRef | None = None
    #: A uniform staircase collapsed to a single ``n× rise`` mark. The COLLAPSE is a
    #: content decision and is made here; the renderer only needs to know so it can name
    #: the mark (``dim_step_typ`` rather than ``dim_step_0``) and skip the per-rung
    #: legibility gate, which has nothing to filter when there is one representative rung.
    representative: bool = False


@dataclass(frozen=True)
class Omission:
    """A measurement the compiler did not approve, and why.

    ``authored`` separates the author's own omission from a planner rule's suppression (a
    square footprint, an X-turned extent). Only the first makes an empty result the script's
    doing, and only the first is recoverable by adding a `dimension(...)` line — a
    distinction three attempts at predicting renderer behaviour in #921 kept blurring.
    """

    feature: Feature | None
    parameter_id: str
    value: float | None
    reason: str

    @property
    def authored(self) -> bool:
        return self.reason == _AUTHORED_OMISSION


@dataclass(frozen=True)
class RenderableDimensionPlan:
    """Everything approved for drawing, plus what was not and why.

    Grows one renderer at a time: :attr:`ladders` covers the height ladder and shoulder
    chain (the first migrated slice). Renderers not yet migrated keep consuming
    `plan_dimensions` directly, and the migration is finished when none do.

    :attr:`diagnostics` is produced but not yet consumed — see the module docstring. It is
    an output with a named owner and a date, not a claim about today's behaviour.
    """

    ladders: tuple[ApprovedLadder, ...] = ()
    diagnostics: tuple[Omission, ...] = field(default=())

    def ladder(self, kind: str) -> ApprovedLadder | None:
        """The approved ladder of *kind*, or ``None`` if it was not approved."""
        return next((lad for lad in self.ladders if lad.kind == kind), None)

    def omitted(self, kind: str) -> tuple[Omission, ...]:
        """Diagnostics whose parameter belongs to *kind* — what a lint pass reports."""
        return tuple(o for o in self.diagnostics if o.parameter_id.startswith(f"{kind}."))


def _step_repeat(levels, base: float, top: float, tol_frac: float = 0.10):
    """``(n, rise)`` if *levels* form a uniform staircase, else ``None``.

    A uniform staircase has all inter-step rises (including from *base* to the first step)
    within *tol_frac* of their mean; ``n`` counts the top gap too when it matches. Requires
    ≥3 interior steps to avoid false positives.

    Lives in the compiler because collapsing five rungs into one ``5× 10`` mark is a
    decision about WHAT the drawing says, not where it goes. It was in the renderer beside
    the legibility gate, which reads similarly and is genuinely a placement decision (it
    depends on the scale) — the two moved apart here on purpose.
    """
    if len(levels) < 3:
        return None
    ordered = sorted(levels)
    rises = [ordered[0] - base] + [ordered[i + 1] - ordered[i] for i in range(len(ordered) - 1)]
    mean = sum(rises) / len(rises)
    if mean <= 0 or not all(abs(r - mean) / mean <= tol_frac for r in rises):
        return None
    return len(rises) + (1 if abs((top - ordered[-1]) - mean) / mean <= tol_frac else 0), mean


def _suppressed_dims(model: PartModel, groups=None):
    """``{(feature, parameter_id): (value, reason)}`` for every dimension the planner
    marked — the compiler's input for what NOT to approve.

    *groups* lets a caller that has already planned pass the result in. The engine plans
    once per build (ADR 0008 Amdt 5); a compiler that re-planned would both cost a second
    pass and create two products that can drift while the migration is partial (#923
    review)."""
    out = {}
    for group in groups if groups is not None else plan_dimensions(model):
        for pd in group.dims:
            if pd.suppressed:
                out[(id(group.feature), pd.param.parameter_id)] = (
                    pd.param.value,
                    pd.reason or "suppressed",
                )
    return out


def _dim_id(feature, parameter_id: str) -> DimensionId | None:
    """The ADR 0016 identity for an approved entry.

    Minted here rather than left ``None``: `DimensionId` is already the stable addressable
    identity the ADR defines, and a renderer-facing result that discards it would create
    identity debt on the very boundary meant to remove it — provenance, edits, diagnostics
    and later de-duplication all key on it (#923 review)."""
    if feature is None:
        return None
    return DimensionId(feature, parameter_id)


def _compile_step_ladders(model: PartModel, marked) -> tuple[list[ApprovedLadder], list[Omission]]:
    """The prismatic height rungs and shoulder chain, approved as whole sets."""
    step = next((f for f in model.features if isinstance(f, StepLevelFeature)), None)
    if step is None:
        return [], []
    approved: list[ApprovedLadder] = []
    omissions: list[Omission] = []
    bb: Any = model.bbox  # build123d BoundBox
    x, y = float(bb.max.X), float(bb.min.Y)
    step_ref = FeatureRef(step)

    heights = [
        ApprovedDimension(
            id=_dim_id(step, "step_height.length"),
            label=_fmt(z - step.base),
            value=z - step.base,
            span=((x, y, step.base), (x, y, z)),
            ref=step_ref,
        )
        for z in sorted(step.levels)
    ]
    height_marks = [
        (pid, v, why)
        for (fid, pid), (v, why) in marked.items()
        if fid == id(step) and pid.startswith("step_height.")
    ]
    if heights and not height_marks:
        rep = _step_repeat(list(step.levels), step.base, float(bb.max.Z))
        if rep is not None:
            n, rise = rep
            first = sorted(step.levels)[0]
            heights = [
                ApprovedDimension(
                    id=_dim_id(step, "step_height.length"),
                    label=f"{n}× {_fmt(rise)}",
                    value=rise,
                    span=((x, y, step.base), (x, y, first)),
                    ref=step_ref,
                )
            ]
        approved.append(
            ApprovedLadder(
                "step_height", tuple(heights), ref=step_ref, representative=rep is not None
            )
        )
    else:
        omissions += [Omission(step, pid, v, why) for pid, v, why in height_marks]

    _di = {"x": 0, "y": 1, "z": 2}

    def _shoulder_span(axis: str, pos: float):
        """A shoulder's span, from its datum to its position along its own axis.

        Carried rather than left ``None`` so consumers never go back to the feature for the
        station: the detail crop needs the X positions to frame the crowded band, and
        `render_step_positions` will need both ends when it migrates. The varying
        coordinate also tells a consumer which axis it runs along, without a second field
        to keep in step."""
        lo = list(step.datum)
        hi = list(step.datum)
        hi[_di[axis]] = pos
        return (tuple(lo), tuple(hi))

    shoulders = [
        ApprovedDimension(
            id=_dim_id(step, "step_position.length"),
            label=_fmt(abs(pos - step.datum[_di[axis]])),
            value=abs(pos - step.datum[_di[axis]]),
            span=_shoulder_span(axis, pos),
            ref=step_ref,
        )
        for axis, pos in sorted(step.shoulders)
    ]
    pos_marks = [
        (pid, v, why)
        for (fid, pid), (v, why) in marked.items()
        if fid == id(step) and pid.startswith("step_position.")
    ]
    if shoulders and not pos_marks:
        approved.append(ApprovedLadder("step_position", tuple(shoulders), ref=step_ref))
    else:
        omissions += [Omission(step, pid, v, why) for pid, v, why in pos_marks]
    return approved, omissions


def _compile_overall_height(
    model: PartModel, marked, *, include_overall: bool
) -> tuple[ApprovedLadder | None, list[Omission]]:
    """The part's overall height — the envelope's ``height`` parameter, drawn in the
    front-view right strip rather than below a view, which is why it rides the ladder.

    Every reason it might not be drawn is settled here, in one place. They used to be split:
    the planner suppressed it for a Z-turned part while the renderer independently suppressed
    it for that AND an X/Y rotational OD AND `include_overall`, and neither knew about the
    other. ``include_overall`` is drawing state (the finalize drain's explicit-envelope-height
    request), so it arrives as an argument rather than being read off the model.

    A model with no `EnvelopeFeature` — a round body, or a `Sheet` that never called
    `.envelope()` — has no parameter naming its height, and the value falls back to the
    bounding box. The COMPILER may do that; a renderer may not, which is the whole point.
    """
    env = next((f for f in model.features if isinstance(f, EnvelopeFeature)), None)
    bb: Any = model.bbox  # build123d BoundBox
    rot = next((f for f in model.features if isinstance(f, RotationalFeature)), None)
    if not include_overall:
        return None, []
    if model.orientation == "z":
        return None, [
            Omission(
                env,
                "height.length",
                float(bb.size.Z),
                "Z-turned (the step chain tiles the height)",
            )
        ]
    if rot is not None and rot.frame.axis in ("x", "y"):
        return None, [
            Omission(
                env,
                "height.length",
                float(bb.size.Z),
                f"rotational OD ({rot.frame.axis}-axis) conveys the height",
            )
        ]
    if env is not None:
        mark = marked.get((id(env), "height.length"))
        if mark is not None:
            return None, [Omission(env, "height.length", mark[0], mark[1])]
    value = float(env.height) if env is not None else float(bb.size.Z)
    env_ref = FeatureRef(env) if env is not None else None
    x, y = float(bb.max.X), float(bb.min.Y)
    return (
        ApprovedLadder(
            "overall_height",
            (
                ApprovedDimension(
                    id=_dim_id(env, "height.length"),
                    label=_fmt(value),
                    value=value,
                    span=((x, y, float(bb.min.Z)), (x, y, float(bb.max.Z))),
                    ref=env_ref,
                ),
            ),
            ref=env_ref,
        ),
        [],
    )


def compile_dimensions(
    model: PartModel, *, include_overall: bool = True, groups=None
) -> RenderableDimensionPlan:
    """Compile *model* into the dimensions that will be drawn, and the ones that will not.

    One pass, one policy. Everything a renderer needs to know about WHAT to draw is decided
    here; everything about WHERE stays in the renderer.

    *groups* accepts a `plan_dimensions` result the caller already has, so the engine's
    plan-once invariant holds through the migration instead of the compiler quietly
    re-planning behind it (#923 review).
    """
    marked = _suppressed_dims(model, groups)
    ladders, omissions = _compile_step_ladders(model, marked)
    overall, height_omissions = _compile_overall_height(
        model, marked, include_overall=include_overall
    )
    if overall is not None:
        ladders.append(overall)
    return RenderableDimensionPlan(
        ladders=tuple(ladders), diagnostics=tuple(omissions + height_omissions)
    )
