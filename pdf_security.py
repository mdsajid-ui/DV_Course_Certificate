"""
pdf_security.py
=================
High-tight digital security, cryptographic locking, and anti-tampering protection
for all DV Analytics issued certificates.

Features:
1. AES-256 PDF Permission Locking:
   - Disallows editing, modifying text, replacing graphics, or altering content.
   - Disallows copying/extracting text and assets.
   - Disallows adding annotations, markups, or form filling.
   - Disallows page extraction, rotation, or document assembly.
   - Only printing and accessibility viewing are permitted.
2. Cryptographic SHA-256 Checksum:
   - Computes unique digital fingerprint of each issued certificate.
   - Embeds security metadata in the PDF header.
   - Verifiable against DV Analytics immutable certificate registry.
"""

import os
import hashlib
import secrets
from typing import Optional, Tuple

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
    from utils import get_secret
    master_key = get_secret("CERT_OWNER_KEY")
    if not master_key:
        master_key = secrets.token_hex(32)
    return str(master_key)


def compute_file_sha256(file_path: str) -> str:
    """Calculates the SHA-256 checksum of a file."""
    if not os.path.exists(file_path):
        return ""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def lock_and_protect_pdf(pdf_path: str, owner_password: Optional[str] = None) -> Tuple[str, bool]:
    """
    Applies high-security encryption and strict permission locks to prevent editing,
    copying, form-filling, or page extraction in Adobe Acrobat, Nitro, Foxit, and other editors.

    Returns:
        (sha256_checksum, is_encrypted_and_locked)
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    owner_pwd = owner_password or get_owner_password()
    is_locked = False

    if HAS_FITZ:
        try:
            doc = fitz.open(pdf_path)

            # 1. Update official digital provenance metadata
            meta = doc.metadata or {}
            meta["author"] = "DV Analytics"
            meta["creator"] = "DV Analytics Digital Certificate Engine"
            meta["producer"] = "DV Analytics Certificate Authority (Secured & Authenticated)"
            meta["subject"] = "Official Verified Course Completion Certificate · Tamper-Proof"
            meta["keywords"] = "DV Analytics, Verified Certificate, Tamper-Proof, AES-256"
            doc.set_metadata(meta)

            # 2. Strict Permissions: PRINT + ACCESSIBILITY ONLY (NO MODIFY, NO COPY, NO ANNOTATE, NO FORM)
            # fitz.PDF_PERM_PRINT: Allows high-quality printing
            # fitz.PDF_PERM_ACCESSIBILITY: Allows screen readers
            # Explicitly disallows: PDF_PERM_MODIFY, PDF_PERM_COPY, PDF_PERM_ANNOTATE, PDF_PERM_FORM, PDF_PERM_ASSEMBLE
            permissions = fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY

            # 3. Save with AES-256 encryption.
            # user_pw="" enables transparent opening without requiring a password from students.
            # owner_pw locks all permissions and prevents unauthorized modifications.
            encryption_mode = fitz.PDF_ENCRYPT_AES_256 if hasattr(fitz, "PDF_ENCRYPT_AES_256") else fitz.PDF_ENCRYPT_AES_128
            secured_bytes = doc.tobytes(
                encryption=encryption_mode,
                owner_pw=owner_pwd,
                user_pw="",
                permissions=permissions,
                deflate=True,
            )
            doc.close()

            with open(pdf_path, "wb") as f:
                f.write(secured_bytes)

            is_locked = True
        except Exception:
            pass

    # Compute final SHA-256 fingerprint
    sha256_digest = compute_file_sha256(pdf_path)
    return sha256_digest, is_locked
