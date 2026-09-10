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
                send_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counters (
                bucket TEXT PRIMARY KEY,   -- e.g. "DVA|APIDS|2026"
                next_seq INTEGER NOT NULL
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


def _row_to_record(row: sqlite3.Row) -> CertificateRecord:
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


def _next_sequence(conn: sqlite3.Connection, bucket: str) -> int:
    row = conn.execute("SELECT next_seq FROM counters WHERE bucket = ?", (bucket,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO counters (bucket, next_seq) VALUES (?, 2)", (bucket,))
        return 1
    seq = row["next_seq"]
    conn.execute("UPDATE counters SET next_seq = ? WHERE bucket = ?", (seq + 1, bucket))
    return seq


def format_cert_number(institute_code: str, course_code: str, year: str, seq: int, width: int = 6) -> str:
    return f"{institute_code}-{course_code}-{year}-{str(seq).zfill(width)}"


def issue_or_get_certificate_number(
    *,
    name: str,
    email: str,
    course: str,
    completion_date: Optional[str],
    institute_code: str,
    course_code: str,
    year: str,
    existing_number: Optional[str] = None,
) -> CertificateRecord:
    """
    Idempotent: if this (email, course) already has a certificate number,
    return the existing record untouched. Otherwise atomically allocate the
    next sequence number for (institute_code, course_code, year) and persist
    a new record. This is what guarantees "same number on regenerate/resend".
    """
    key = student_key(email, course)
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
        if row:
            return _row_to_record(row)

        bucket = f"{institute_code}|{course_code}|{year}"
        if existing_number:
            cert_number = existing_number
        else:
            seq = _next_sequence(conn, bucket)
            cert_number = format_cert_number(institute_code, course_code, year, seq)
            
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
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE certificates
               SET last_sent_at = ?, send_count = send_count + 1
             WHERE cert_number = ?
            """,
            (datetime.now(timezone.utc).isoformat(), cert_number.strip()),
        )


init_db()
