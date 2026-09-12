"""
cert_store.py
=============
Local source of truth for certificate numbers and send status.

Why this exists (read this before ripping it out):
Google Sheets access in this project uses a read-only API key (by design —
see README "Google Sheets access" section). A read-only API key can list
rows but cannot write cells back to the sheet. That means the spreadsheet
itself cannot be where we persist "the certificate number we already issued
to this student" — if we tried, every regenerate/resend would either
duplicate-write or silently fail.

So this module is the durable, authoritative record for:
  * the certificate number issued to a given (email, course) pair — once
    issued, it never changes, satisfying "same number on
    download/regenerate/resend"
  * send history (so we can block accidental double-sends)
  * the data the public /verify/{number} service reads (name, course,
    status) — deliberately NOT phone numbers or anything not needed for
    verification

It's a single-file SQLite database. That's enough for an institute-scale
student list and it means the verification microservice (verify_service/)
can open the same file read-only without standing up a second database.

If you later switch Google Sheets auth to a service account or OAuth
(both support writing), you can add a "sync_to_sheet()" call after
`issue_or_get_certificate_number` without changing anything else here.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("CERT_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "certificates.db"))

_lock = threading.Lock()  # SQLite + Streamlit's multi-session threads: cheap insurance


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def _connect():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS certificates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_key TEXT UNIQUE NOT NULL,   -- normalized email|course
                cert_number TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                course TEXT NOT NULL,
                completion_date TEXT,
                status TEXT NOT NULL DEFAULT 'VALID',   -- VALID / REVOKED
                created_at TEXT NOT NULL,
                last_sent_at TEXT,
                send_count INTEGER NOT NULL DEFAULT 0,
                email_status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING / SENT / FAILED
                last_error TEXT,
                last_attempt_at TEXT,
                pdf_hash TEXT,
                is_locked INTEGER NOT NULL DEFAULT 1,
                security_level TEXT NOT NULL DEFAULT 'AES-256-READONLY'
            );
            """
        )
        # Additive migration for DBs created before new columns existed.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(certificates)").fetchall()}
        if "email_status" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN email_status TEXT NOT NULL DEFAULT 'PENDING'")
        if "last_error" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN last_error TEXT")
        if "last_attempt_at" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN last_attempt_at TEXT")
        if "pdf_hash" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN pdf_hash TEXT")
        if "is_locked" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 1")
        if "security_level" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN security_level TEXT NOT NULL DEFAULT 'AES-256-READONLY'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counters (
                bucket TEXT PRIMARY KEY,   -- e.g. "DVA|APIDS|2026"
                next_seq INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            """
            -- Rows the automation loop could not even attempt to process (no email,
            -- duplicate certificate number clash, etc). Keyed by sheet row number so
            -- a later poll overwrites the same row's entry instead of piling up.
            CREATE TABLE IF NOT EXISTS skipped_rows (
                row_number INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT,
                reason TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cert_number ON certificates(cert_number);")


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def student_key(email: str, course: str) -> str:
    return f"{_normalize(email)}|{_normalize(course)}"


@dataclass
class CertificateRecord:
    cert_number: str
    name: str
    email: str
    course: str
    completion_date: Optional[str]
    status: str
    created_at: str
    last_sent_at: Optional[str]
    send_count: int
    email_status: str = "PENDING"
    last_error: Optional[str] = None
    last_attempt_at: Optional[str] = None
    pdf_hash: Optional[str] = None
    is_locked: int = 1
    security_level: str = "AES-256-READONLY"


def _row_to_record(row: sqlite3.Row) -> CertificateRecord:
    keys = row.keys()
    return CertificateRecord(
        cert_number=row["cert_number"],
        name=row["name"],
        email=row["email"],
        course=row["course"],
        completion_date=row["completion_date"],
        status=row["status"],
        created_at=row["created_at"],
        last_sent_at=row["last_sent_at"],
        send_count=row["send_count"],
        email_status=row["email_status"] if "email_status" in keys else "PENDING",
        last_error=row["last_error"] if "last_error" in keys else None,
        last_attempt_at=row["last_attempt_at"] if "last_attempt_at" in keys else None,
        pdf_hash=row["pdf_hash"] if "pdf_hash" in keys else None,
        is_locked=row["is_locked"] if "is_locked" in keys else 1,
        security_level=row["security_level"] if "security_level" in keys else "AES-256-READONLY",
    )


def store_pdf_security_hash(cert_number: str, pdf_hash: str) -> None:
    """Records the cryptographic SHA-256 integrity seal for an issued certificate."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE certificates
               SET pdf_hash = ?, is_locked = 1
             WHERE cert_number = ?
            """,
            (str(pdf_hash), cert_number.strip()),
        )


def get_by_student(email: str, course: str) -> Optional[CertificateRecord]:
    key = student_key(email, course)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
        return _row_to_record(row) if row else None


def get_by_cert_number(cert_number: str) -> Optional[CertificateRecord]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM certificates WHERE cert_number = ?", (cert_number.strip(),)
        ).fetchone()
        return _row_to_record(row) if row else None


def _next_sequence(conn: sqlite3.Connection, bucket: str, start_seq: int = 2075) -> int:
    row = conn.execute("SELECT next_seq FROM counters WHERE bucket = ?", (bucket,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO counters (bucket, next_seq) VALUES (?, ?)", (bucket, start_seq + 1))
        return start_seq
    seq = row["next_seq"]
    conn.execute("UPDATE counters SET next_seq = ? WHERE bucket = ?", (seq + 1, bucket))
    return seq


def set_sequence_counter(bucket: str, next_seq: int) -> None:
    """Sets the next sequence counter value for a bucket."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO counters (bucket, next_seq) VALUES (?, ?)
            ON CONFLICT(bucket) DO UPDATE SET next_seq = excluded.next_seq
            """,
            (bucket, next_seq),
        )


def format_cert_number(
    institute_code: str = "DVA",
    batch_prefix: str = "202505",
    seq: int = 2075,
    course_code: str = "",
    format_style: str = "COMPACT",
) -> str:
    """
    Formats certificate sequence number.
    Default COMPACT style produces exact sequence: 202505DVA2075, 202505DVA2076...
    """
    prefix = (batch_prefix or "202505").strip()
    inst = (institute_code or "DVA").strip()
    if format_style == "LEGACY" and course_code:
        return f"{inst}-{course_code}-{prefix}-{str(seq).zfill(6)}"
    return f"{prefix}{inst}{seq}"


def issue_or_get_certificate_number(
    *,
    name: str,
    email: str,
    course: str,
    completion_date: Optional[str] = None,
    institute_code: str = "DVA",
    course_code: str = "APIDS",
    year: str = "2025",
    batch_prefix: Optional[str] = None,
    start_seq: int = 2075,
    format_style: str = "COMPACT",
    existing_number: Optional[str] = None,
) -> CertificateRecord:
    """
    Idempotent: if this (email, course) already has a certificate number,
    return the existing record untouched. Otherwise atomically allocate the
    next sequence number (e.g. 202505DVA2075) and persist a new record.
    """
    key = student_key(email, course)
    effective_prefix = (batch_prefix or year or "202505").strip()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
        if row:
            return _row_to_record(row)

        bucket = f"{institute_code}|{course_code}|{effective_prefix}"
        if existing_number:
            cert_number = existing_number.strip()
        else:
            seq = _next_sequence(conn, bucket, start_seq=start_seq)
            cert_number = format_cert_number(
                institute_code=institute_code,
                batch_prefix=effective_prefix,
                seq=seq,
                course_code=course_code,
                format_style=format_style,
            )
            
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO certificates
                (student_key, cert_number, name, email, course, completion_date,
                 status, created_at, last_sent_at, send_count)
            VALUES (?, ?, ?, ?, ?, ?, 'VALID', ?, NULL, 0)
            """,
            (key, cert_number, name, email, course, completion_date, now),
        )
        row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
        return _row_to_record(row)


def mark_sent(cert_number: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE certificates
               SET last_sent_at = ?, send_count = send_count + 1,
                   email_status = 'SENT', last_error = NULL, last_attempt_at = ?
             WHERE cert_number = ?
            """,
            (now, now, cert_number.strip()),
        )


def mark_send_failed(cert_number: str, error: str) -> None:
    """Records a failed send attempt without touching send_count/last_sent_at,
    so the dashboard can show 'FAILED' and the next automation poll will retry it."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE certificates
               SET email_status = 'FAILED', last_error = ?, last_attempt_at = ?
             WHERE cert_number = ?
            """,
            (str(error)[:500], datetime.now(timezone.utc).isoformat(), cert_number.strip()),
        )


def record_skip(row_number: int, name: str, email: str, reason: str) -> None:
    """Logs a sheet row the automation loop couldn't even attempt (no email,
    duplicate cert-number clash, etc). Overwrites any prior entry for that row."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO skipped_rows (row_number, name, email, reason, detected_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(row_number) DO UPDATE SET
                name=excluded.name, email=excluded.email,
                reason=excluded.reason, detected_at=excluded.detected_at
            """,
            (row_number, name, email, reason, datetime.now(timezone.utc).isoformat()),
        )


def clear_skip(row_number: int) -> None:
    """Called once a previously-skipped row is processed successfully."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM skipped_rows WHERE row_number = ?", (row_number,))


def list_all_certificates() -> list:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM certificates ORDER BY created_at DESC").fetchall()
        return [_row_to_record(r) for r in rows]


def list_skipped_rows() -> list:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM skipped_rows ORDER BY row_number ASC").fetchall()
        return [dict(r) for r in rows]


init_db()
