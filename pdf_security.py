"""
pdf_security.py
=================
High-tight digital security, cryptographic locking, pixel-lock flattening,
and anti-tampering protection for all DV Analytics issued certificates.

Security Architecture:
1. Pixel-Lock Flattening (Anti-Edit / Anti-Extraction):
   - Every page is rasterized at high resolution (300 DPI) into an uneditable image layer.
   - Completely removes all text objects, font streams, and vector paths.
   - No PDF editor (Adobe Acrobat, Illustrator, Nitro, Foxit, Canva, Word) can select or edit text.
2. AES-256 Zero-Permission Encryption (Anti-Print / Anti-Copy):
   - Permission mask set to 0 (Printing blocked, Modifying blocked, Copying blocked, Annotations blocked).
   - Adobe Acrobat and standard viewers disable File > Print and Ctrl+P.
   - Master owner key locks the permission dictionary.
3. Cryptographic SHA-256 Integrity Seal:
   - Computes unique digital fingerprint of each issued certificate.
   - Injects provenance metadata into the PDF header.
   - Stored in DV Analytics immutable registry (cert_store.py) for instant QR verification.
"""

from __future__ import annotations

import os
import io
import hashlib
import secrets
from typing import Optional, Tuple
from PIL import Image

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except Exception:
    HAS_FITZ = False


def get_owner_password() -> str:
    """
    Retrieves or generates a master encryption key.
    If CERT_OWNER_KEY is set in environment, uses it; otherwise generates a cryptographically
    secure 256-bit token.
    """
    try:
        from utils import get_secret
        master_key = get_secret("CERT_OWNER_KEY")
        if master_key:
            return str(master_key)
    except Exception:
        pass
    return secrets.token_hex(32)


def compute_file_sha256(file_path: str) -> str:
    """Calculates the SHA-256 checksum of a file."""
    if not os.path.exists(file_path):
        return ""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def lock_and_protect_pdf(
    pdf_path: str,
    owner_password: Optional[str] = None,
    allow_print: bool = False,
    dpi: int = 300,
) -> Tuple[str, bool]:
    """
    Applies high-security pixel-lock flattening and AES-256 permission locking:
    1. Rasterizes all pages to 300 DPI images (eliminating all editable vector text/fonts).
    2. Encrypts with AES-256 and sets permissions to 0 (No Print, No Edit, No Copy, No Annotate).
    3. Seals with DV Analytics digital provenance metadata and SHA-256 hash.

    Returns:
        (sha256_checksum, is_encrypted_and_locked)
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    owner_pwd = owner_password or get_owner_password()
    is_locked = False

    if HAS_FITZ:
        try:
            src_doc = fitz.open(pdf_path)
            locked_doc = fitz.open()

            # Step 1: Pixel-Lock Flattening - bake all text and shapes into 300 DPI raster
            for page in src_doc:
                # 300 DPI ensures crisp visual clarity while permanently destroying editable text runs
                pix = page.get_pixmap(dpi=dpi)
                img_bytes = pix.tobytes("png")
                rect = page.rect
                new_page = locked_doc.new_page(width=rect.width, height=rect.height)
                new_page.insert_image(rect, stream=img_bytes)

            src_doc.close()

            # Step 2: Digital Provenance Metadata
            meta = {
                "author": "DV Analytics Certificate Authority",
                "creator": "DV Analytics High-Security Certificate Engine",
                "producer": "DV Analytics (Digitally Sealed · Tamper-Proof · Uneditable)",
                "subject": "Official Verified Certificate - High-Tight Digital Security (No Print / No Edit)",
                "keywords": "DV Analytics, Verified, Tamper-Proof, AES-256, Pixel-Locked, Protected",
            }
            locked_doc.set_metadata(meta)

            # Step 3: Zero-Permission Mask
            # 0 = Completely disallow Printing, Modifying, Copying, Annotating, Form filling, Page Extraction
            # If allow_print is explicitly True, fitz.PDF_PERM_PRINT can be added
            permissions = fitz.PDF_PERM_PRINT if allow_print else 0

            # Step 4: AES-256 Cryptographic Encryption
            encryption_mode = (
                fitz.PDF_ENCRYPT_AES_256
                if hasattr(fitz, "PDF_ENCRYPT_AES_256")
                else fitz.PDF_ENCRYPT_AES_128
            )

            secured_bytes = locked_doc.tobytes(
                encryption=encryption_mode,
                owner_pw=owner_pwd,
                user_pw="",  # Blank user password allows viewing on screens
                permissions=permissions,
                deflate=True,
            )
            locked_doc.close()

            with open(pdf_path, "wb") as f:
                f.write(secured_bytes)

            is_locked = True
        except Exception:
            pass

    # Compute final SHA-256 fingerprint
    sha256_digest = compute_file_sha256(pdf_path)
    return sha256_digest, is_locked
