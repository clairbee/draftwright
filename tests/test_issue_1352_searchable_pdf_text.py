"""#1352: PDF export retains searchable text without changing visible drawing ink."""

from __future__ import annotations

import math
import shutil
import warnings
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from build123d import Align, Box, Cylinder, Location, Pos
from build123d_drafting import Dimension
from PIL import Image, ImageChops

from draftwright import Sheet, build_drawing
from draftwright._core import _text_line_spacing_em
from draftwright.drawing import Drawing
from draftwright.export import _PDFTextRun, _render_pdf, _resolved_semantic_font_path
from draftwright.fonts import PLEX_MONO, PLEX_SANS_CONDENSED


def _manufacturing_drawing():
    part = Box(90, 60, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part -= Pos(-20, 0, 0) * Cylinder(1.25, 12)
    part -= Pos(20, 0, 0) * Cylinder(4, 12)

    sheet = Sheet(
        part,
        title="SEARCHABLE BRACKET",
        number="DWG-1352",
        material="AL 6061-T6",
        drawn_by="QA",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheet.auto_dimensions()
    sheet.hole(diameter=2.5, at=(-20, 0, 6), axis="z", through=True).thread("M3x0.5")
    sheet.hole(diameter=8, at=(20, 0, 6), axis="z", through=True).fit("H7")
    top_face = max(part.faces(), key=lambda face: face.center().Z)
    sheet.note("DEBURR ALL EDGES", top_face, view="front", side="above")
    drawing = sheet.build()
    drawing.note("INSPECT DATUM A", (160, 185), name="inspection_note")
    return drawing


def _pdf_text(path: str):
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[0]
        text_page = page.get_textpage()
        return pdf, text_page, text_page.get_text_range()
    except Exception:
        pdf.close()
        raise


def _assert_first_character_overlaps_annotation(text_page, extracted, text, annotation):
    first_char_box = text_page.get_charbox(extracted.index(text))
    label_box = annotation.label_bbox
    assert label_box is not None
    k = 72.0 / 25.4
    left, bottom, right, top = first_char_box
    x0, y0, x1, y1 = label_box
    assert left < x1 * k and right > x0 * k
    assert bottom < y1 * k and top > y0 * k


def test_pdf_extracts_dimensions_callouts_notes_and_title_block_values(tmp_path):
    drawing = _manufacturing_drawing()
    pdf_path = drawing.export(str(tmp_path / "semantic"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert "INSPECT DATUM A" in extracted
        assert "DEBURR ALL EDGES" in extracted
        assert "M3x0.5" in extracted
        assert "H7" in extracted
        assert "SEARCHABLE BRACKET" in extracted
        assert "DWG-1352" in extracted
        assert "AL 6061-T6" in extracted
        assert "QA / draftwright" in extracted

        dimension_name = next(
            name
            for name in drawing.annotations()
            if getattr(drawing.get_annotation(name), "label", None) == "65"
        )
        thread_name = next(
            name
            for name in drawing.annotations()
            if "M3x0.5" in (getattr(drawing.get_annotation(name), "label", "") or "")
        )
        _assert_first_character_overlaps_annotation(
            text_page, extracted, "65", drawing.get_annotation(dimension_name)
        )
        _assert_first_character_overlaps_annotation(
            text_page, extracted, "M3x0.5", drawing.get_annotation(thread_name)
        )
    finally:
        text_page.close()
        pdf.close()

    data = Path(pdf_path).read_bytes()
    assert b"/FontFile2" in data and b"/ToUnicode" in data
    assert b"IBMPlexMono-Regular" in data
    assert b"IBMPlexSansCond-Regular" in data


def test_semantic_text_layer_does_not_change_rendered_pixels(tmp_path, monkeypatch):
    drawing = _manufacturing_drawing()
    semantic = drawing.export(str(tmp_path / "semantic"), formats=("png",))["png"]

    monkeypatch.setattr(Drawing, "_pdf_text_runs", lambda _self: ())
    path_only = drawing.export(str(tmp_path / "path_only"), formats=("png",))["png"]

    semantic_image = Image.open(semantic).convert("RGBA")
    path_only_image = Image.open(path_only).convert("RGBA")
    assert ImageChops.difference(semantic_image, path_only_image).getbbox() is None


def _character_centre(text_page, index):
    left, bottom, right, top = text_page.get_charbox(index)
    return ((left + right) / 2.0, (bottom + top) / 2.0)


def _extracted_text_angle(text_page, extracted, value):
    start = extracted.index(value)
    x0, y0 = _character_centre(text_page, start)
    x1, y1 = _character_centre(text_page, start + len(value) - 1)
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def test_multiline_notes_and_title_values_retain_visible_line_pitch(tmp_path):
    drawing = build_drawing(
        Box(10, 10, 10),
        auto_dims=False,
        title="TOP\nBOTTOM",
        number="D\n2",
    )
    drawing.note("A\nB\nC\nD\nE\nF\nG", (100, 100), name="multiline")

    pdf_path = drawing.export(str(tmp_path / "multiline"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert "A\r\nB\r\nC\r\nD\r\nE\r\nF\r\nG" in extracted
        assert "TOP\r\nBOTTOM" in extracted
        expected_pitch_points = (
            _text_line_spacing_em(
                drawing.draft.font_size,
                drawing.draft.font_path,
                drawing.draft.font,
            )
            * drawing.draft.font_size
            * 72.0
            / 25.4
        )
        note_indices = [extracted.index(line) for line in tuple("ABCDEFG")]
        centres = [_character_centre(text_page, index) for index in note_indices]
        assert all(
            upper[1] - lower[1] == pytest.approx(expected_pitch_points, abs=0.15)
            for upper, lower in zip(centres, centres[1:], strict=False)
        )
    finally:
        text_page.close()
        pdf.close()


def test_structured_multiline_note_uses_renderer_line_pitch(tmp_path):
    part = Box(80, 50, 20)
    top = max(part.faces(), key=lambda face: face.center().Z)
    sheet = Sheet(part).auto_dimensions()
    sheet.note("A\nB\nC", top, view="front", side="above")
    drawing = sheet.build()

    pdf_path = drawing.export(str(tmp_path / "structured_note"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert "A\r\nB\r\nC" in extracted
        expected_pitch_points = (
            _text_line_spacing_em(
                drawing.draft.font_size,
                drawing.draft.font_path,
                drawing.draft.font,
            )
            * drawing.draft.font_size
            * 72.0
            / 25.4
        )
        centres = [_character_centre(text_page, extracted.index(line)) for line in "ABC"]
        assert all(
            math.dist(upper, lower) == pytest.approx(expected_pitch_points, abs=0.15)
            for upper, lower in zip(centres, centres[1:], strict=False)
        )
    finally:
        text_page.close()
        pdf.close()


def test_declared_gdt_values_and_datums_are_searchable(tmp_path):
    part = Box(80, 50, 20) - Pos(0, 0, 0) * Cylinder(6, 20)
    top = max(part.faces(), key=lambda face: face.center().Z)
    sheet = Sheet(part).auto_dimensions()
    hole = sheet.hole(Pos(0, 0, 0) * Cylinder(6, 20))
    sheet.finish("7.77", top, view="front", side="above")
    sheet.datum("Q", top, view="front", side="above")
    sheet.control(hole).position("0.123", to="Q", diameter=True, modifier="M")
    drawing = sheet.build()

    pdf_path = drawing.export(str(tmp_path / "gdt"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert "7.77" in extracted
        assert "Q" in extracted
        assert "0.123" in extracted
        assert "M" in extracted
    finally:
        text_page.close()
        pdf.close()


def test_semantic_order_tiebreak_and_basic_dimension_rotation_are_total(tmp_path):
    drawing = build_drawing(Box(10, 10, 10), auto_dims=False)
    for index, label in enumerate(("AA", "BB")):
        annotation = Dimension(
            (10, 10, 0),
            (50, 50, 0),
            (0, 1, 0),
            10,
            drawing.draft,
            label=label,
            basic=index == 1,
        )
        # Deliberate overlap exercises export robustness. Production feature
        # dimensions still enter through the verbs and placement solve.
        drawing.registry.add(annotation, f"same_box_{index}", view=None)
        drawing.items.append(annotation)

    pdf_path = drawing.export(str(tmp_path / "same_box"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert "AA" in extracted and "BB" in extracted
        assert _extracted_text_angle(text_page, extracted, "AA") == pytest.approx(45.0, abs=1.0)
        assert _extracted_text_angle(text_page, extracted, "BB") == pytest.approx(45.0, abs=1.0)
    finally:
        text_page.close()
        pdf.close()


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ((50, 10, 0), (10, 50, 0), -45.0),
        ((20, 50, 0), (20, 10, 0), 90.0),
    ],
)
def test_basic_dimension_semantic_text_is_normalised_upright(tmp_path, start, end, expected):
    drawing = build_drawing(Box(10, 10, 10), auto_dims=False)
    annotation = Dimension(start, end, (0, 1, 0), 10, drawing.draft, label="UPRIGHT", basic=True)
    drawing.registry.add(annotation, "upright", view=None)
    drawing.items.append(annotation)

    pdf_path = drawing.export(str(tmp_path / f"upright_{expected}"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert _extracted_text_angle(text_page, extracted, "UPRIGHT") == pytest.approx(
            expected, abs=1.0
        )
    finally:
        text_page.close()
        pdf.close()


def test_raw_helper_dimension_semantic_fallback_keeps_visible_units(tmp_path):
    drawing = build_drawing(Box(10, 10, 10), auto_dims=False)
    annotation = Dimension((10, 10, 0), (20, 10, 0), "above", 10, drawing.draft)
    drawing.registry.add(annotation, "raw_units", view=None)
    drawing.items.append(annotation)

    pdf_path = drawing.export(str(tmp_path / "raw_units"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert "10.0mm" in extracted
    finally:
        text_page.close()
        pdf.close()


def test_note_semantic_rotation_tracks_later_annotation_transform(tmp_path):
    drawing = build_drawing(Box(10, 10, 10), auto_dims=False)
    drawing.note("ROTATED", (100, 100), rotation=10, name="rotated")
    drawing.get_annotation("rotated").location = Location((0, 0, 0), (0, 0, 20))

    pdf_path = drawing.export(str(tmp_path / "rotated"), formats=("pdf",))["pdf"]
    pdf, text_page, extracted = _pdf_text(pdf_path)
    try:
        assert _extracted_text_angle(text_page, extracted, "ROTATED") == pytest.approx(
            30.0, abs=1.0
        )
    finally:
        text_page.close()
        pdf.close()


def test_named_font_opt_out_resolves_the_renderer_face_and_style():
    regular = Path(_resolved_semantic_font_path(None, "Arial", "REGULAR"))
    bold = Path(_resolved_semantic_font_path(None, "Arial", "BOLD"))
    assert regular.is_file() and bold.is_file()
    assert regular != bold


def test_non_ttfont_semantic_face_falls_back_once_without_losing_text(
    tmp_path, monkeypatch, caplog
):
    from reportlab.pdfbase import ttfonts

    svg_path = tmp_path / "blank.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
        'viewBox="0 0 100 100"><path d="M0 0 L1 1"/></svg>',
        encoding="utf-8",
    )
    unsupported = tmp_path / "unsupported.otf"
    shutil.copyfile(PLEX_SANS_CONDENSED, unsupported)
    real_ttfont = ttfonts.TTFont

    class RejectNonTTFont(real_ttfont):
        def __init__(self, name, path, *args, **kwargs):
            if Path(path) == unsupported:
                raise ValueError("CFF-style font is not supported by ReportLab TTFont")
            super().__init__(name, path, *args, **kwargs)

    monkeypatch.setattr(ttfonts, "TTFont", RejectNonTTFont)
    pdf_path = tmp_path / "fallback.pdf"
    _render_pdf(
        str(svg_path),
        str(pdf_path),
        text_runs=tuple(
            _PDFTextRun(f"FALLBACK{index}", 10, 10 + index * 5, 3, font_path=str(unsupported))
            for index in range(3)
        ),
    )

    pdf, text_page, extracted = _pdf_text(str(pdf_path))
    try:
        assert all(f"FALLBACK{index}" in extracted for index in range(3))
        assert Path(PLEX_MONO).is_file()
        assert sum("cannot be embedded" in record.message for record in caplog.records) == 1
    finally:
        text_page.close()
        pdf.close()
