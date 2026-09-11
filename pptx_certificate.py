"""
pptx_certificate.py
====================
Fills the official DV Analytics certificate template (a .pptx, not a flat
image) with a student's Name / Certificate Number / Date, embeds the QR
code, and renders the result to PDF.

Why edit the .pptx instead of stamping text onto a flattened PNG (which is
what the existing certificate_generator.py does for the Excel-upload flow)?
Inspecting the actual template showed its whole decorative design (logos,
signatures, ribbon, borders) is one flattened background picture, with a
single editable text box holding the "This is to certify that [ ]..." and
"Certificate Registration Number: [ ] Date of Completion: [ ]" paragraphs.
Editing the real text runs in that box — rather than rasterizing and
re-drawing text on top — keeps the certificate texts vector-crisp and
guarantees pixel-for-pixel fidelity to the original design, per the "do not
redesign, preserve the original" requirement.

Placeholder replacement strategy
---------------------------------
The bracket placeholders ("[ ]") are sometimes split across multiple text
runs by PowerPoint (verified by inspecting both the blank and a
manually-filled sample of this exact template — the run boundaries differed
between the two files even though they use the same template). So this
module does NOT assume fixed run indices. Instead, for each paragraph it:
  1. Concatenates all run texts to get the paragraph's full text and each
     run's [start, end) offset within it.
  2. Finds the bracket span with a regex anchored to a label ("certify
     that", "Certificate Registration Number:", "Date of Completion:").
  3. Replaces exactly the text between (and including) the brackets,
     splicing across as many runs as the span touches, and leaves every
     other run in the paragraph untouched — so unrelated formatting
     elsewhere in the same paragraph survives.

QR placement
------------
The template's background is a single flattened image, so shape-level
collision detection isn't possible — the safe zone below was found by
scanning the rasterized template for a blank rectangle in the bottom-right
quadrant (see project notes / README). It sits in the white space between
the "Date of Completion" line and the right-hand signature block. It's
deliberately modest in size (about 0.8in) because that's what the existing
design leaves free without moving the signature or the decorative corner —
if you want a larger, more reliably-scannable QR, the master template's
right signature block would need to move slightly to make room.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pptx import Presentation
from pptx.util import Inches

DEFAULT_TEMPLATE_PATH = os.environ.get(
    "CERTIFICATE_TEMPLATE_PPTX",
    os.path.join(os.path.dirname(__file__), "assets", "templates", "certificate_APIDS_blank.pptx"),
)

# Empirically-found blank rectangle common to BOTH course templates (inches
# from top-left of the slide) — re-measured after adding the real APIDS
# template, whose body copy runs one line longer than APDA's and pushes the
# "Certificate Registration Number / Date of Completion" line down to about
# y=5.0in (vs. ~4.7in on APDA). 5.05in clears that line on both templates
# with margin to spare before the signature block starts around y=6.6in.
# Overridable via env vars so a redesigned template doesn't require a code
# change.
QR_LEFT_IN = float(os.environ.get("CERTIFICATE_QR_LEFT_IN", 6.85))
QR_TOP_IN = float(os.environ.get("CERTIFICATE_QR_TOP_IN", 5.02))
QR_SIZE_IN = float(os.environ.get("CERTIFICATE_QR_SIZE_IN", 0.68))
QR_CAPTION_GAP_IN = 0.02
QR_CAPTION_HEIGHT_IN = 0.15


class TemplateFieldNotFound(RuntimeError):
    pass


@dataclass
class _RunSpan:
    run: "object"
    start: int
    end: int


def _paragraph_runs_with_offsets(paragraph) -> Tuple[str, List[_RunSpan]]:
    spans: List[_RunSpan] = []
    pos = 0
    for run in paragraph.runs:
        text = run.text or ""
        spans.append(_RunSpan(run=run, start=pos, end=pos + len(text)))
        pos += len(text)
    full_text = "".join(s.run.text or "" for s in spans)
    return full_text, spans


def _replace_span_across_runs(spans: List[_RunSpan], start: int, end: int, new_text: str) -> None:
    """Replace full_text[start:end] with new_text, editing only the runs
    that overlap that range. Runs entirely inside the range are emptied;
    the run containing `start` keeps its prefix + new_text; the run
    containing `end` keeps its suffix. Handles start==end run too."""
    if start == end:
        # Zero-width insertion point (e.g. a bracket whose interior was all
        # whitespace, greedily consumed by the regex before the capture
        # group). Prefer the run that ends exactly here so the new text is
        # appended to it; otherwise use the run that starts here.
        target = next((s for s in spans if s.end == start), None) or next(
            (s for s in spans if s.start == start), None
        )
        if target is None:
            return
        local = start - target.start
        text = target.run.text or ""
        target.run.text = text[:local] + new_text + text[local:]
        return

    touched = [s for s in spans if s.end > start and s.start < end]
    if not touched:
        return
    if len(touched) == 1:
        s = touched[0]
        local_start = start - s.start
        local_end = end - s.start
        text = s.run.text or ""
        s.run.text = text[:local_start] + new_text + text[local_end:]
        return

    first, last = touched[0], touched[-1]
    first_text = first.run.text or ""
    first.run.text = first_text[: start - first.start] + new_text
    for mid in touched[1:-1]:
        mid.run.text = ""
    last_text = last.run.text or ""
    last.run.text = last_text[end - last.start :]


def _replace_bracket_after_label(paragraph, label_pattern: str, new_value: str, field_desc: str) -> None:
    full_text, spans = _paragraph_runs_with_offsets(paragraph)
    # Capture the *entire* bracket interior (including any whitespace) rather
    # than trimming it outside the group — trimming outside meant an
    # all-whitespace interior (the common case for a blank placeholder)
    # collapsed to a zero-width match sitting exactly on a run boundary.
    pattern = re.compile(label_pattern + r"\s*\[(.*?)\]", re.IGNORECASE | re.DOTALL)
    m = pattern.search(full_text)
    if not m:
        raise TemplateFieldNotFound(
            f"Could not locate the '{field_desc}' placeholder in the template. "
            f"Expected a pattern like '<label> [ ... ]'. Paragraph text was: {full_text!r}"
        )
    _replace_span_across_runs(spans, m.start(1), m.end(1), f" {new_value} ")


def fill_certificate_text(prs: Presentation, *, name: str, certificate_number: str, completion_date: str) -> None:
    """Mutates `prs` in place, filling all three dynamic fields."""
    slide = prs.slides[0]
    text_frames = [shape.text_frame for shape in slide.shapes if shape.has_text_frame]
    if not text_frames:
        raise TemplateFieldNotFound("Template has no editable text box — is this the right file?")

    filled = {"name": False, "cert": False, "date": False}
    for tf in text_frames:
        for paragraph in tf.paragraphs:
            full_text, _ = _paragraph_runs_with_offsets(paragraph)
            if not filled["name"] and re.search(r"certify that", full_text, re.IGNORECASE):
                _replace_bracket_after_label(paragraph, r"certify that", name, "student name")
                filled["name"] = True
            if not filled["cert"] and re.search(r"Certificate Registration Number", full_text, re.IGNORECASE):
                _replace_bracket_after_label(
                    paragraph, r"Certificate Registration Number\s*:", certificate_number, "certificate number"
                )
                filled["cert"] = True
            if not filled["date"] and re.search(r"Date of Completion", full_text, re.IGNORECASE):
                _replace_bracket_after_label(paragraph, r"Date of Completion\s*:", completion_date, "completion date")
                filled["date"] = True

    missing = [k for k, v in filled.items() if not v]
    if missing:
        raise TemplateFieldNotFound(f"Could not find placeholder(s) for: {', '.join(missing)}")


def _add_qr_to_slide(prs: Presentation, qr_png_path: str, certificate_number: str) -> None:
    slide = prs.slides[0]
    slide.shapes.add_picture(
        qr_png_path,
        Inches(QR_LEFT_IN),
        Inches(QR_TOP_IN),
        width=Inches(QR_SIZE_IN),
        height=Inches(QR_SIZE_IN),
    )
    # Single short line only (no certificate number repeated here — it's
    # already printed in the certificate body above). Kept deliberately
    # small: the gap between the "Certificate Registration Number" line and
    # the right-hand signature scrawl is under 1 inch on the real template,
    # so every fraction of an inch here risks the caption overlapping the
    # signature again (see README "QR placement" notes).
    caption_top = QR_TOP_IN + QR_SIZE_IN + QR_CAPTION_GAP_IN
    box = slide.shapes.add_textbox(
        Inches(QR_LEFT_IN - 0.25),
        Inches(caption_top),
        Inches(QR_SIZE_IN + 0.5),
        Inches(QR_CAPTION_HEIGHT_IN),
    )
    from pptx.util import Pt
    from pptx.enum.text import PP_ALIGN

    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_top = 0
    tf.margin_bottom = 0
    p1 = tf.paragraphs[0]
    p1.text = "Scan to Verify"
    p1.alignment = PP_ALIGN.CENTER
    p1.runs[0].font.size = Pt(6)
    p1.runs[0].font.bold = True


def render_certificate_pdf(
    *,
    name: str,
    certificate_number: str,
    completion_date: str,
    qr_png_path: str,
    template_path: Optional[str] = None,
    output_pdf_path: str,
) -> str:
    """
    Fills the template and produces a final PDF at `output_pdf_path`.
    Requires LibreOffice (`soffice`) on PATH for the pptx->pdf conversion —
    same dependency the rest of this deployment already needs for nothing
    else, so document it in README/requirements if you deploy this
    separately from a machine that has it.
    """
    template_path = template_path or DEFAULT_TEMPLATE_PATH
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Certificate template not found: {template_path}")
    if shutil.which("soffice") is None:
        raise RuntimeError(
            "LibreOffice ('soffice') is required to convert the filled certificate "
            "to PDF but was not found on PATH. Install libreoffice (or "
            "libreoffice-impress) on the server."
        )

    prs = Presentation(template_path)
    fill_certificate_text(prs, name=name, certificate_number=certificate_number, completion_date=completion_date)
    _add_qr_to_slide(prs, qr_png_path, certificate_number)

    with tempfile.TemporaryDirectory() as tmpdir:
        filled_pptx = os.path.join(tmpdir, "filled.pptx")
        prs.save(filled_pptx)

        result = subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmpdir, filled_pptx],
            capture_output=True,
            text=True,
            timeout=120,
        )
        produced = os.path.join(tmpdir, "filled.pdf")
        if result.returncode != 0 or not os.path.exists(produced):
            raise RuntimeError(f"LibreOffice conversion failed: {result.stdout}\n{result.stderr}")

        os.makedirs(os.path.dirname(output_pdf_path) or ".", exist_ok=True)
        shutil.copyfile(produced, output_pdf_path)

    return output_pdf_path
