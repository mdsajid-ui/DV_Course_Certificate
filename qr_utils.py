"""
qr_utils.py
===========
Generates the verification QR code embedded inside each certificate.
"""

from __future__ import annotations

import os
from typing import Optional

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def verification_url(cert_number: str, base_url: Optional[str] = None) -> str:
    base_url = (base_url or os.environ.get("CERTIFICATE_VERIFICATION_BASE_URL", "http://localhost:8000")).rstrip("/")
    return f"{base_url}/verify/{cert_number}"


def make_qr_image_bytes(data: str, box_size: int = 10, border: int = 2) -> bytes:
    """Returns PNG bytes of a QR code encoding `data`."""
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,  # tolerates being printed/scanned off a certificate
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
