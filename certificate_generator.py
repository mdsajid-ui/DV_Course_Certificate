"""
certificate_generator.py
-------------------------
Handles rendering a participant's name onto a certificate template
(PNG or PDF) and saving the result as an individual PDF certificate.
"""

import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageStat

try:
    import fitz  # PyMuPDF - only needed if template is a PDF
    HAS_FITZ = True
except Exception:
    # Catch broadly, not just ImportError: on some hosting environments a
    # missing shared library or version mismatch raises other exception
    # types here, which was crashing the entire app on import instead of
    # just disabling PDF-template support.
    HAS_FITZ = False


def sanitize_filename(name: str) -> str:
    """Turn a person's name into a safe filename fragment."""
    name = str(name).strip()
    name = re.sub(r"[^\w\s-]", "", name)   # drop punctuation
    name = re.sub(r"\s+", "_", name)       # spaces -> underscores
    return name or "Participant"


def suggest_name_position(template_img: Image.Image) -> float:
    """
    Auto-detect the best vertical position (0.0-1.0) to draw the
    participant's name so it doesn't collide with text already baked into
    the certificate template (e.g. "This is to certify that ..." /
    "has successfully participated in ..."), instead of assuming a fixed
    50% center.

    Many certificate templates already contain printed text lines. If we
    always draw the name at a fixed 50% mark, it ends up stamped directly
    on top of whichever line happens to sit there — which is exactly the
    "name is not coming properly" / overlapping-text bug. To avoid that we
    scan horizontal strips of the template within a sensible name-placement
    zone (18%-72% down the certificate — skips the header/logo area and the
    footer/signature area) and score each strip by how "blank" it is: a row
    of mostly uniform background pixels scores high, a row containing dense
    dark/printed text scores low. We return the vertical center (as a
    fraction of image height) of the tallest sufficiently blank strip that
    can comfortably fit the name.
    """
    w, h = template_img.size
    gray = template_img.convert("L")

    zone_top = int(h * 0.18)
    zone_bottom = int(h * 0.72)
    strip_left = int(w * 0.12)
    strip_right = int(w * 0.88)

    row_step = max(1, h // 400)  # sample every few pixels for speed on large images
    row_scores = []  # (row_y, is_blank)
    for y in range(zone_top, zone_bottom, row_step):
        row = gray.crop((strip_left, y, strip_right, y + row_step))
        stat = ImageStat.Stat(row)
        mean = stat.mean[0]
        stddev = stat.stddev[0] if stat.stddev else 0.0
        # A row with real printed text has noticeably higher local contrast
        # (dark glyph strokes against a lighter background) than an empty
        # background row, which is why low stddev is a strong "blank" signal.
        is_blank = stddev < 18
        row_scores.append((y, is_blank, mean))

    # Collect every run of consecutive blank rows in the zone (a template can
    # have several: above the title, between "certify that" and the name
    # line, between the name line and the course title, etc).
    runs = []
    current_run = []
    for y, is_blank, mean in row_scores:
        if is_blank:
            current_run.append(y)
        else:
            if current_run:
                runs.append(current_run)
            current_run = []
    if current_run:
        runs.append(current_run)

    min_gap_px = h * 0.05  # need at least ~5% of the certificate height of clear space
    candidates = [r for r in runs if (r[-1] - r[0]) >= min_gap_px]

    if candidates:
        # Score each candidate blank band by size, but heavily favor ones
        # near the vertical middle of the certificate — the tallest blank
        # run is often empty header space above the title, not the actual
        # name line, so length alone picks the wrong spot. Certificates
        # consistently place the participant's name close to center, so
        # proximity to 50% is a much stronger signal than raw run length.
        def score(run):
            length_pct = (run[-1] - run[0]) / h * 100
            center_pct = ((run[0] + run[-1]) / 2) / h * 100
            distance_from_center = abs(center_pct - 50)
            return length_pct - 0.6 * distance_from_center

        best_run = max(candidates, key=score)
        center_y = (best_run[0] + best_run[-1]) / 2
        return round(center_y / h, 3)

    # Fallback: no sufficiently large blank band was found (e.g. a densely
    # worded template) — fall back to a slightly-below-center position,
    # which on most certificate layouts sits just under the "certify that"
    # line rather than directly on top of it.
    return 0.52


def suggest_text_style(template_img: Image.Image, y_position_pct: float = 0.5):
    """
    Recommend a font size and text color that will actually be visible on
    this specific template, instead of a fixed default. A fixed pixel size
    (e.g. 60px) is fine on a small template and nearly invisible on a large,
    high-resolution one — so we scale to the template's own height. We also
    sample the brightness of the band where the name will be drawn and pick
    a contrasting color (dark navy on light backgrounds, white on dark ones)
    so the name is never accidentally the same color as the background.
    """
    w, h = template_img.size
    font_size = max(28, min(260, round(h * 0.07)))

    band_top = max(0, int(h * y_position_pct - h * 0.06))
    band_bottom = min(h, int(h * y_position_pct + h * 0.06))
    band_left = int(w * 0.15)
    band_right = int(w * 0.85)
    if band_bottom <= band_top:
        band_bottom = band_top + 1

    region = template_img.crop((band_left, band_top, band_right, band_bottom)).convert("L")
    avg_brightness = ImageStat.Stat(region).mean[0]  # 0 (black) - 255 (white)

    text_color = (8, 8, 64) if avg_brightness > 150 else (255, 255, 255)
    return font_size, text_color


def load_template_as_image(template_path: str) -> Image.Image:
    """Load a PNG/JPG template, or rasterize page 1 of a PDF template."""
    ext = os.path.splitext(template_path)[1].lower()
    if ext == ".pdf":
        if not HAS_FITZ:
            raise RuntimeError(
                "PyMuPDF (pymupdf) is required to use a PDF certificate template. "
                "Install it with: pip install pymupdf"
            )
        doc = fitz.open(template_path)
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x for better resolution
        img_bytes = pix.tobytes("png")
        doc.close()
        from io import BytesIO
        return Image.open(BytesIO(img_bytes)).convert("RGB")
    else:
        return Image.open(template_path).convert("RGB")


BUNDLED_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "DejaVuSerif-Bold.ttf")


def get_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    """
    Load a TTF font. Tries, in order: an explicitly given font_path, the
    font bundled with this app (assets/DejaVuSerif-Bold.ttf — always
    present regardless of host OS), then a couple of common system font
    paths. Only falls back to PIL's tiny fixed-size default font if all of
    those fail, since that default silently ignores `size` and renders
    text that's effectively invisible on a real certificate.
    """
    candidates = []
    if font_path:
        candidates.append(font_path)
    candidates.append(BUNDLED_FONT_PATH)
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        try:
            if candidate and os.path.exists(candidate):
                return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_certificate_image(
    template_img: Image.Image,
    name: str,
    font_path: str = None,
    font_size: int = 60,
    text_color: tuple = (5, 3, 116),
    y_position_pct: float = 0.50,
    certificate_number: str = None,
    completion_date: str = None,
    qr_png_path: str = None,
) -> Image.Image:
    """
    Return a copy of the template image with `name` drawn centered
    horizontally at `y_position_pct` (0.0 = top, 1.0 = bottom) of the image.
    Optionally stamps QR code and details if provided.
    """
    img = template_img.copy()
    draw = ImageDraw.Draw(img)
    font = get_font(font_path, font_size)

    text = str(name).strip()
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (img.width - text_w) / 2
    y = (img.height * y_position_pct) - (text_h / 2)

    draw.text((x, y), text, font=font, fill=text_color)

    # Optional QR code overlay (bottom right)
    if qr_png_path and os.path.exists(qr_png_path):
        try:
            qr_img = Image.open(qr_png_path).convert("RGBA")
            qr_size = int(min(img.width, img.height) * 0.12)
            qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
            qr_x = int(img.width * 0.82) - (qr_size // 2)
            qr_y = int(img.height * 0.72)
            img.paste(qr_img, (qr_x, qr_y), qr_img if qr_img.mode == "RGBA" else None)
        except Exception:
            pass

    return img


def save_image_as_pdf(img: Image.Image, output_path: str):
    """Save a PIL image as a single-page PDF."""
    rgb_img = img.convert("RGB")
    rgb_img.save(output_path, "PDF", resolution=150.0)


def generate_certificate(
    template_img: Image.Image,
    name: str,
    output_dir: str,
    font_path: str = None,
    font_size: int = 60,
    text_color: tuple = (5, 3, 116),
    y_position_pct: float = 0.50,
    used_names: dict = None,
    certificate_number: str = None,
    completion_date: str = None,
    qr_png_path: str = None,
    custom_filename: str = None,
) -> str:
    """
    Generate one certificate for `name` and save it to `output_dir`.
    Returns the output file path. Handles duplicate names by suffixing _2, _3, etc.
    """
    os.makedirs(output_dir, exist_ok=True)
    used_names = used_names if used_names is not None else {}

    rendered = render_certificate_image(
        template_img,
        name,
        font_path=font_path,
        font_size=font_size,
        text_color=text_color,
        y_position_pct=y_position_pct,
        certificate_number=certificate_number,
        completion_date=completion_date,
        qr_png_path=qr_png_path,
    )

    if custom_filename:
        filename = custom_filename if custom_filename.endswith(".pdf") else f"{custom_filename}.pdf"
    else:
        base = sanitize_filename(name)
        used_names[base] = used_names.get(base, 0) + 1
        suffix = "" if used_names[base] == 1 else f"_{used_names[base]}"
        filename = f"{base}{suffix}_Certificate.pdf"

    output_path = os.path.join(output_dir, filename)
    save_image_as_pdf(rendered, output_path)

    # Apply digital encryption, permission lock & calculate SHA-256 seal
    try:
        from pdf_security import lock_and_protect_pdf
        lock_and_protect_pdf(output_path)
    except Exception:
        pass

    return output_path
