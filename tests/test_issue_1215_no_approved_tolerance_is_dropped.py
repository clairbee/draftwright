"""Every tolerance the compiler approves must reach the annotation that claims it.

`tests/test_compiled_plan_boundary.py` enforces one direction of ADR 0016 Amdt 1 — a renderer
must not emit what the plan withheld. Nothing enforced the converse: **a renderer must emit
everything the plan approved.**

#1215 was one instance of the converse, and six review rounds found it one site at a time —
envelope extents, the overall-height ladder, the turned-step chain, two public `Drawing` verbs,
the deferred corridor route, prismatic step rungs, the detail-view redraw, the short-rise escape,
step shoulders, and pattern pitch. Each round's fix was correct and each round's sweep was scoped
to the shape of the site it had just seen.

This is the general guard. It decorates **every parameter of every feature** on a set of parts,
through **both** spellings of a `decorations=` key, builds, and joins what the compiler approved
against what the claiming annotation actually renders. It found three live sites in a single run
— the ones round 6 was still discovering by hand — and it fails on any new one.

Why the join is sound: `registry.measurement_of(name)` is the ADR 0010 seam, so an annotation
that claims a `DimensionId` is asserting it draws that measurement. If the compiler attached a
tolerance to that id and the label carries no suffix, the drawing states a requirement less
precisely than the author wrote it — silently, which is the whole failure mode.

It asserts two things, because "the suffix is missing" was only the half of the converse that
had been looked at (#1216 review r9):

1. every annotation carries one occurrence of the suffix per approved id it claims — counted,
   since a compound callout claims several and one ± satisfied a substring test for all of them;
2. every approved measurement is claimed by SOME annotation, or its absence is reported. Two
   were neither: a mandatory overall extent starved out of a full strip by a leader, and a step
   rung the legibility gate discarded — each left the drawing short a dimension with the lint
   perfectly clean.
"""

from __future__ import annotations

from collections import Counter

import pytest
from build123d import Axis, Box, Cylinder, Pos, Rot

from draftwright._core import _tol_suffix
from draftwright.builder import build_drawing
from draftwright.model.compiled import compile_dimensions

_TOL = 0.05

#: The draft the suffix is formatted against. `_tol_suffix` rounds to `decimal_precision`, so
#: the expected text must come from the same draft the renderer used — a different precision
#: would make the comparison a guess again.
_DRAFT = build_drawing(Box(20, 20, 20), title="T", number="N").draft


def _staircase():
    return Box(120, 60, 15) + Pos(-20, 0, 15) * Box(80, 60, 15) + Pos(-40, 0, 30) * Box(40, 60, 15)


def _crowded_staircase():
    """Tiers 3 mm apart: the legibility gate moves rungs into an enlarged DETAIL view.

    The detail is the case that matters most — those rungs are dimensioned *only* there, so a
    tolerance dropped in the redraw is absent from the drawing entirely while its siblings on
    the main view show theirs.
    """
    part = Pos(0, 0, 3) * Box(20, 16, 6)
    z = 6
    for w in (16, 13, 10, 7, 5):
        part += Pos(0, 0, z + 1.5) * Box(w, 12, 3)
        z += 3
    return part


def _linear_pattern():
    part = Box(140, 60, 12)
    for x in (-40, -20, 0, 20, 40):
        part -= Pos(x, 0, 0) * Cylinder(3, 40)
    return part


def _turned_shaft():
    return Rot(0, 90, 0) * (Cylinder(8, 30) + Pos(0, 0, 30) * Cylinder(5, 20))


def _short_first_rise():
    """A 1 mm first rise: too short to dimension in the right strip, so it escapes to the LEFT
    one (`_build_left`). That branch is live — instrumenting it records 18 hits across the fast
    tier — but no fixture anywhere toleranced a part that reaches it, so the escape dropped its
    suffix unobserved (#1234 review r6)."""
    from build123d import BuildPart, BuildSketch, Plane, Polygon, extrude

    with BuildPart() as part:
        with BuildSketch(Plane.XZ):
            Polygon((0, 0), (50, 0), (50, 1), (25, 1), (25, 20), (0, 20))
        extrude(amount=30)
    return part.part


def _counterbored_plate():
    """A counterbored through hole: the compound callout, whose recess terms are separate
    parameters. Only the BORE's tolerance was threaded, so `⌀8 ±0.1 THRU ⌴ ⌀14` showed one ±
    and silently lost the other (#1234 review r7)."""
    from build123d import Cone

    part = Box(140, 60, 12)
    # Counterbored.
    part -= Pos(-35, 0, 0) * Cylinder(4, 40)
    part -= Pos(-35, 0, 3) * Cylinder(7, 6)
    # Countersunk — the csink terms are separate parameters again, and a fixture without one
    # leaves `csink_dia_tol` / `csink_angle_tol` unswept. This cone geometry is the one
    # `tests/test_issue_1143_hole_completeness.py` uses; my first attempt built a cone the
    # recogniser did not see as a countersink at all, so the sweep silently covered nothing.
    part -= Pos(35, 0, 0) * Cylinder(3, 40)
    part -= Pos(35, 0, 4) * Cone(3, 7, 4)
    return part


def _chamfered_block():
    """Chamfers label as `C3` and fillets as `4× R5` — letters then digits, which the guard's
    second predicate matched as if it were a fit class. Deleting the chamfer renderer's suffix
    left the authored ± off the sheet with the guard green (#1234 review r7)."""
    from build123d import chamfer

    part = Box(60, 40, 20)
    return chamfer(part.edges().filter_by(Axis.Z), 3)


def _blind_holes():
    """BLIND holes: `HoleFeature.parameters()` emits the depth role only when a hole is not
    through, so a corpus of through holes leaves `bore.depth` unswept — which is how a reader
    for `depth_tol` shipped against a key the spec never wrote (#1234 review r8)."""
    part = Box(80, 60, 12)
    for x in (-20, 20):
        part -= Pos(x, 0, 5) * Cylinder(5, 4)
    return part


def _plate_with_holes():
    return Box(90, 60, 12) - Pos(-25, 12, 0) * Cylinder(4, 40) - Pos(25, -12, 0) * Cylinder(4, 40)


def _hole_grid():
    """A 3x2 rectangular grid: two pitch dims, one per lattice axis.

    `_add_grid_pitch_dims` handed `_pitch_text` `members[lo:hi+1]` — a slice of the IR's
    member ORDER, which walks a grid in neither lattice direction. The consecutive gaps in
    that slice mix row and column spacing, so a perfectly uniform grid read as jittered and
    every grid pitch withheld its authored tolerance (#1216 review r9)."""
    part = Box(140, 100, 12)
    for x in (-40, 0, 40):
        for y in (-25, 25):
            part -= Pos(x, y, 0) * Cylinder(4, 40)
    return part


def _uniform_staircase():
    """Four equal 12 mm rises: the one part that collapses to a `N x rise` REPRESENTATIVE.

    Without it `_DELIBERATELY_BARE` was inert — neither name in it occurred anywhere in this
    corpus, so the set excluded nothing and the deliberately-bare rule it documents was
    asserted by nothing (#1216 review r9)."""
    part = Box(160, 50, 12)
    for i in range(1, 4):
        part += Pos(-i * 10, 0, i * 12) * Box(160 - i * 20, 50, 12)
    return part


def _uniform_stepped_shaft():
    """Three equal 25 mm turned steps — the turned counterpart, `m_steplen_typ`."""
    shaft = None
    for i in range(3):
        seg = Pos(0, 0, i * 25 + 12.5) * Cylinder((30 - i * 5) / 2, 25)
        shaft = seg if shaft is None else shaft + seg
    return Rot(0, 90, 0) * shaft


_PARTS = {
    "staircase": _staircase,
    "crowded_staircase": _crowded_staircase,
    "linear_pattern": _linear_pattern,
    "short_first_rise": _short_first_rise,
    "turned_shaft": _turned_shaft,
    "blind_holes": _blind_holes,
    "chamfered_block": _chamfered_block,
    "counterbored_plate": _counterbored_plate,
    "plate_with_holes": _plate_with_holes,
    "hole_grid": _hole_grid,
    "uniform_staircase": _uniform_staircase,
    "uniform_stepped_shaft": _uniform_stepped_shaft,
}

#: The two shapes a `decorations=` key takes. BOTH are swept, because they are not the same
#: experiment: the role key tolerances one parameter, while the bare `(feature, kind)` key —
#: the public spelling in ADR 0011 — tolerances every role of that kind at once. Only the
#: second produces a label that must carry the SAME suffix twice (a counterbored callout's
#: bore and its recess), which is exactly what the old substring predicate could not tell
#: apart from carrying it once (#1216 review r9).
_KEY_MODES = ("role", "kind")

#: Parameters whose mark deliberately states no tolerance, with the reason. A collapsed
#: representative is the case: `N× rise` stands for levels that merely fall within 10% of each
#: other, so a ± would claim the author's tolerance of values that differ. (A pattern's `N× pitch`
#: is NOT here — its gaps are identical by construction, so the ± applies to each one.)
_DELIBERATELY_BARE = {"dim_step_typ", "m_steplen_typ"}


def _approved_with_tolerance(plan):
    approved = {}
    for group in plan.groups:
        for dim in group.dims:
            if dim.tolerance is not None and dim.id is not None:
                approved[dim.id] = dim
    for ladder in plan.ladders:
        for rung in ladder.rungs:
            if rung.tolerance is not None and rung.id is not None:
                approved[rung.id] = rung
    return approved


def _rendered_text(registry, name) -> str:
    """Everything this annotation puts on the page.

    A `label` for a dimension or callout — and a TABLE's cells, which have no label at all.
    Reading only `label` made both hole-table routes invisible to this sweep: a table claims
    `bore.diameter` through the same ADR 0010 seam a leader does, and printed the bare number
    while the guard read its empty label and passed (#1216 review r9).
    """
    obj = registry.named(name)
    label = getattr(obj, "label", None)
    if label:
        return str(label)
    rows = getattr(obj, "table_rows", None)
    if rows:
        return " ".join(str(cell) for row in rows for cell in row)
    return ""


def _missing(text: str, approved) -> list[str]:
    """The suffixes *text* owes and does not carry — counted, not searched for.

    ONE OCCURRENCE PER APPROVED ID. Every predicate before this one asked "does the label
    contain a tolerance", and each was green over a live drop:

    * "contains a space" — every collapsed `4× 20` label has one;
    * a regex for the three `_tol_suffix` shapes — its fit-class alternative (letters then
      digits) matches `C3` on every chamfer and `4× R5` on every fillet;
    * `_tol_suffix(...) in label` — one term's suffix stands in for another's on a compound
      callout that claims several ids.

    The third was measured, because "it could be satisfied by the wrong term" is the kind of
    claim that reads true and is not: suppressing `csink_dia_tol` in `callout_from_spec` makes
    `hc_plan0` print `⌀6 ±0.1 THRU ⌵ ⌀14 × 90°` while still claiming both the bore and the
    countersink, and `counterbored_plate-kind` PASSES on the substring predicate and FAILS on
    this one. The isolation matters: a coarser mutation that suppressed the counterbore term as
    well is caught by both, because the second callout then loses its only suffix — so the
    differential exists but only for a single-term drop (#1216 review r9).

    The plan holds the tolerance, so the expected text is computable exactly rather than
    guessed — which is also the ADR 0016 Amdt 1 shape: compare to the compiler, not to a
    pattern.
    """
    want = Counter(_tol_suffix(dim.tolerance, _DRAFT) for dim in approved)
    return [f"{n}x{sfx!r}" for sfx, n in sorted(want.items()) if text.count(sfx) < n]


#: A build issue whose code ends any of these ways is the engine SAYING a measurement did not
#: reach the sheet — `step_dim_dropped`, `step_dim_withheld`, `placement_unsatisfiable`,
#: `axial_length_missing`. Matched by SUFFIX rather than by an enumerated vocabulary, for the
#: reason `linting/quality.py` gives for the same choice: a list has to be remembered, and a
#: new omission code should count on the day it is written rather than on the day someone
#: notices. A code that reports an absence some other way will read as silence here — which
#: fails safe: the guard's complaint is "nothing said anything", and the fix is to say it.
_REPORTED_ABSENCE = ("_dropped", "_withheld", "_unsatisfiable", "_missing")


def _absence_reported(drawing) -> list[str]:
    return [i.code for i in drawing.registry.issues if i.code.endswith(_REPORTED_ABSENCE)]


def _sweep(part_name, feature, param, mode):
    """Build with exactly one decoration and return ``(drops, unreported_absences)``."""
    base = build_drawing(_PARTS[part_name](), title="T", number="N")
    model = base.model()
    target = next((f for f in model.features if f.kind == feature.kind and f == feature), None)
    if target is None:
        return [], []
    key = (target, param.kind, param.role) if mode == "role" else (target, param.kind)
    drawing = build_drawing(
        _PARTS[part_name](),
        model=model,
        decorations={key: _TOL},
        title="T",
        number="N",
    )
    approved = _approved_with_tolerance(compile_dimensions(drawing.model()))
    if not approved:
        return [], []
    where = f"{part_name}/{feature.kind}.{param.role}[{mode}]"
    dropped = []
    claimed_anywhere: set = set()
    for name in sorted(drawing.registry.names()):
        claimed = drawing.registry.measurement_of(name)
        if not claimed:
            continue
        claimed_anywhere |= set(claimed)
        if name in _DELIBERATELY_BARE:
            continue
        text = _rendered_text(drawing.registry, name)
        owed = _missing(text, [approved[m] for m in claimed if m in approved])
        if owed:
            dropped.append(f"{where}: {name}={text!r} owes {', '.join(owed)}")
    # The other direction. A measurement the compiler approved and NO annotation claims never
    # reached the drawing at all — which is worse than a missing suffix, and the sweep was
    # blind to it because it only ever looked at annotations that existed. Two live cases
    # (#1216 review r9): a mandatory overall extent starved out of a full strip, and a step
    # rung the legibility gate discarded — both lint-clean with the dimension absent.
    #
    # The assertion is "not silently", not "always drawn": whether a leader may starve an
    # overall extent, and whether a rung too short to dimension should escalate, are placement
    # policy (ADR 0014) and are not settled here. Reporting is not contingent on settling them.
    unreported = []
    if any(m not in claimed_anywhere for m in approved) and not _absence_reported(drawing):
        missing = sorted(str(m.parameter) for m in approved if m not in claimed_anywhere)
        unreported.append(f"{where}: {missing} approved, drawn by nothing, reported by nothing")
    return dropped, unreported


@pytest.mark.parametrize("mode", _KEY_MODES)
@pytest.mark.parametrize("part_name", sorted(_PARTS))
def test_no_approved_tolerance_is_dropped_by_a_renderer(part_name, mode):
    base = build_drawing(_PARTS[part_name](), title="T", number="N")
    dropped: list[str] = []
    unreported: list[str] = []
    for feature in base.model().features:
        for param in feature.parameters():
            got_dropped, got_unreported = _sweep(part_name, feature, param, mode)
            dropped += got_dropped
            unreported += got_unreported
    assert not dropped, (
        f"{dropped}\n\nThe compiler approved a tolerance on these measurements and the "
        "annotation claiming them renders no suffix, so the drawing states the requirement "
        "less precisely than the author wrote it. Compose `_tol_suffix` into the label at the "
        "renderer — helpers discard a forwarded `tolerance=` whenever a label is present."
    )
    assert not unreported, (
        f"{unreported}\n\nThe compiler approved these measurements, no annotation claims "
        "them, and the build recorded nothing about it — so the requirement is absent from "
        "the drawing and absent from the lint. Draw it, or record an issue saying it was not "
        "drawn; vanishing is not one of the options."
    )


def test_the_sweep_actually_decorates_something():
    """The precondition. A sweep that approves no toleranced dimension asserts nothing, and
    every part above must contribute — otherwise a fixture silently stops covering its site."""
    for part_name in sorted(_PARTS):
        base = build_drawing(_PARTS[part_name](), title="T", number="N")
        model = base.model()
        seen = 0
        for feature in model.features:
            for param in feature.parameters():
                drawing = build_drawing(
                    _PARTS[part_name](),
                    model=model,
                    decorations={(feature, param.kind, param.role): _TOL},
                    title="T",
                    number="N",
                )
                seen += len(_approved_with_tolerance(compile_dimensions(drawing.model())))
        assert seen, f"{part_name} approves no toleranced dimension; it guards nothing"


def test_the_deliberately_bare_names_are_reachable():
    """`_DELIBERATELY_BARE` must exclude something that OCCURS.

    It listed `dim_step_typ` and `m_steplen_typ` against a corpus containing neither, so the
    exclusion was inert: the collapse rule it documents — `N x rise` states one value for a
    whole run, so a ± there would claim the author's tolerance of every level at once — was
    asserted nowhere, and the rule could have been broken in either direction with this file
    green (#1216 review r9).
    """
    seen: set[str] = set()
    for part_name in ("uniform_staircase", "uniform_stepped_shaft"):
        drawing = build_drawing(_PARTS[part_name](), title="T", number="N")
        seen |= set(drawing.registry.names())
    assert _DELIBERATELY_BARE <= seen, (
        f"{sorted(_DELIBERATELY_BARE - seen)} never occur in this corpus, so excluding them "
        "excludes nothing"
    )
    for part_name in ("uniform_staircase", "uniform_stepped_shaft"):
        drawing = build_drawing(_PARTS[part_name](), title="T", number="N")
        for name in _DELIBERATELY_BARE & set(drawing.registry.names()):
            label = str(getattr(drawing.registry.named(name), "label", ""))
            assert label.startswith(("3\u00d7", "4\u00d7")), (
                f"{name}={label!r} is not a collapsed `N x` representative, so the reason "
                "this name is excluded no longer holds"
            )


# --------------------------------------------------------------------------------------
# Sites the sweep above cannot reach, each with the fixture that reaches it.
# --------------------------------------------------------------------------------------

#: Sixteen irregular perimeter bores — `_TABULATE_MIN_HOLES`, so the engine escalates the
#: scattered callouts into a hole table by itself. Copied from
#: `tests/test_issue_1144_transactional_hole_table.py` rather than imported: this file must
#: keep working when that one's fixtures change, and a shared constant would make a coverage
#: gap here look like an edit there.
_PERIMETER = (
    (-42.7, -27.4),
    (-15.1, -31.9),
    (11.0, -28.7),
    (44.8, -27.9),
    (-46.0, 32.2),
    (-16.8, 32.4),
    (16.8, 29.3),
    (45.3, 31.5),
    (-56.5, -17.6),
    (-51.6, -7.9),
    (-51.6, 7.5),
    (-51.2, 16.7),
    (50.7, -15.6),
    (56.4, -6.4),
    (50.8, 3.6),
    (55.1, 16.3),
)


def _tabulated_plate():
    part = Box(120, 80, 12)
    for index, (x, y) in enumerate(_PERIMETER):
        part -= Pos(x, y, 0) * Cylinder(1.0 + index * 0.15, 20)
    return part


def _toleranced_bore(part_fn, *, role="bore", kind="diameter"):
    """Build *part_fn* twice: once to get the model, once with one bore toleranced."""
    base = build_drawing(part_fn(), page="A3", title="T", number="N")
    model = base.model()
    feature, param = next(
        (f, p)
        for f in model.features
        if f.kind == "hole"
        for p in f.parameters()
        if p.role == role and p.kind == kind
    )
    drawing = build_drawing(
        part_fn(),
        page="A3",
        model=model,
        decorations={(feature, param.kind, param.role): _TOL},
        title="T",
        number="N",
    )
    approved = _approved_with_tolerance(compile_dimensions(drawing.model()))
    assert approved, "precondition: the decoration approved no toleranced dimension"
    return drawing, approved


def _table_text(drawing, name) -> str:
    table = drawing.registry.named(name)
    assert table is not None, f"precondition: {name} is not on the drawing"
    return " ".join(str(cell) for row in table.table_rows for cell in row)


def test_an_escalated_hole_table_prints_the_authored_tolerance():
    """Density must not cost a requirement.

    When sixteen scattered bores push the engine past `_TABULATE_MIN_HOLES` it withdraws the
    callouts and tabulates them — and the table's cells came from the plan's `value_text` with
    the tolerance left behind, so the SAME part printed `⌀2 ±0.1` beside a leader on a sparser
    sheet and a bare `ø2` in the table on a denser one (#1216 review r9). The sweep above could
    not see it twice over: no fixture there is dense enough to escalate, and its predicate read
    `label`, which a table does not have.
    """
    drawing, approved = _toleranced_bore(_tabulated_plate)
    text = _table_text(drawing, "hole_table_plan")
    claimed = drawing.registry.measurement_of("hole_table_plan")
    owed = _missing(text, [approved[m] for m in claimed if m in approved])
    assert not owed, f"hole_table_plan={text!r} owes {owed}"
    # The precondition, asserted rather than assumed: the table really is claiming the
    # measurement whose tolerance we just checked for.
    assert any(m in approved for m in claimed), (
        "precondition: the table claims none of the approved-toleranced measurements, so the "
        "assertion above is vacuous"
    )


def test_the_public_hole_table_verb_prints_the_authored_tolerance():
    """`add_hole_table()` is the same table by the other door.

    It formatted its own cells off the recognised geometry with `_fmt`, so it dropped the
    tolerance AND minted a value the compiler had already formatted — the ADR 0016 boundary in
    both directions at one site.
    """
    drawing, approved = _toleranced_bore(_plate_with_holes)
    assert drawing.add_hole_table("plan", balloons=False) is not None
    text = _table_text(drawing, "hole_table_plan")
    claimed = drawing.registry.measurement_of("hole_table_plan")
    assert any(m in approved for m in claimed), "precondition: the table claims nothing approved"
    owed = _missing(text, [approved[m] for m in claimed if m in approved])
    assert not owed, f"hole_table_plan={text!r} owes {owed}"


def _starved_extent_plate():
    """An 80x80 plate with a hexagonal boss.

    The A/F callout's leader runs the full depth of the plan view's below corridor, so
    `m_env_width` — force-kept, mandatory priority — solves to `strip_full` and the part's
    width is not dimensioned at all.
    """
    from build123d import BuildPart, BuildSketch, Plane, RegularPolygon, extrude

    plate = Box(80, 80, 10)
    with BuildPart() as boss:
        with BuildSketch(Plane.XY.offset(5)):
            RegularPolygon(20, 6)
        extrude(amount=10)
    return plate + boss.part


def test_a_starved_overall_extent_is_reported():
    """The overall extents were the only dimensions in the engine whose drop said nothing.

    Their corridor candidate carried `on_drop=lambda _nm: None` while every neighbouring pass
    recorded `placement_unsatisfiable`, so a starved strip removed the part's width from the
    sheet and the build issues, the lint and the score all stayed clean (#1216 review r9).

    This asserts the REPORT, not the placement. Whether a feature leader may starve a mandatory
    extent is an ADR 0014 question and is filed separately; it cannot be looked at at all while
    the drop is invisible.
    """
    drawing = build_drawing(_starved_extent_plate(), title="T", number="N")
    # The precondition: this fixture really does lose the width dimension.
    assert "m_env_width" not in drawing.registry.names(), (
        "precondition: this part now places its overall width, so the fixture no longer "
        "reaches the starved-strip path"
    )
    reported = [i for i in drawing.lint() if i.code == "placement_unsatisfiable"]
    assert any("width" in str(i.message) for i in reported), (
        f"the overall width never reached the sheet and nothing said so: {[i.code for i in reported]}"
    )
    # And it names what filled the strip, which is the whole point of reporting it.
    assert any("occupied by" in str(i.message) for i in reported)
