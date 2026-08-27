"""#1352: PDF export retains searchable text without changing visible drawing ink."""

from __future__ import annotations

import warnings
from pathlib import Path

import pypdfium2 as pdfium
from build123d import Align, Box, Cylinder, Pos
from PIL import Image, ImageChops

from draftwright import Sheet
from draftwright.drawing import Drawing


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
            text_page, extracted, "ø2.5 THRU M3x0.5", drawing.get_annotation(thread_name)
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
