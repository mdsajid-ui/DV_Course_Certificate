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

import hashlib
import logging
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

logger = logging.getLogger("cert_store")

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


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${key.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    if "$" in stored_hash:
        salt, key_hex = stored_hash.split("$", 1)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
        return secrets.compare_digest(expected, key_hex)
    return secrets.compare_digest(password, stored_hash)


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
        if "student_id" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN student_id TEXT")
        if "s3_key" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN s3_key TEXT")
        if "s3_bucket" not in existing_cols:
            conn.execute("ALTER TABLE certificates ADD COLUMN s3_bucket TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_student_id ON certificates(student_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_s3_key ON certificates(s3_key);")
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

        # Multi-user accounts table for team member access
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'creator',
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        # Seed default admin accounts if they do not exist
        now = datetime.now(timezone.utc).isoformat()
        existing_admin = conn.execute("SELECT username FROM users WHERE LOWER(username) = 'admin'").fetchone()
        if not existing_admin:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role, created_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                ("admin", _hash_password("cBi19rabI7Ogl8HFjJKjEZDH"), "Administrator", "admin", now),
            )
        existing_sk = conn.execute("SELECT username FROM users WHERE LOWER(username) = 'sk'").fetchone()
        if not existing_sk:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role, created_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                ("sk", _hash_password("cBi19rabI7Ogl8HFjJKjEZDH"), "SK Abdul Sajid", "admin", now),
            )

        # Persistent system settings (e.g. SMTP config, email sender parameters)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        default_settings = {
            "smtp_host": "smtp.office365.com",
            "smtp_port": "587",
            "smtp_username": "md.sajid@dvdataanalytics.com",
            "smtp_password": "Mdsajid@#$123",
            "smtp_sender_name": "DV Analytics Team",
        }
        for k, v in default_settings.items():
            conn.execute(
                "INSERT OR IGNORE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (k, v, now),
            )


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
    student_id: Optional[str] = None
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None


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
        student_id=row["student_id"] if "student_id" in keys else None,
        s3_key=row["s3_key"] if "s3_key" in keys else None,
        s3_bucket=row["s3_bucket"] if "s3_bucket" in keys else None,
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


def update_s3_metadata(
    cert_number: str,
    s3_key: str,
    s3_bucket: str,
    student_id: Optional[str] = None,
) -> None:
    """Records S3 object key, bucket, and optional student ID for an issued certificate."""
    with _lock, _connect() as conn:
        if student_id:
            conn.execute(
                """
                UPDATE certificates
                   SET s3_key = ?, s3_bucket = ?, student_id = COALESCE(student_id, ?)
                 WHERE cert_number = ?
                """,
                (s3_key.strip(), s3_bucket.strip(), student_id.strip(), cert_number.strip()),
            )
        else:
            conn.execute(
                """
                UPDATE certificates
                   SET s3_key = ?, s3_bucket = ?
                 WHERE cert_number = ?
                """,
                (s3_key.strip(), s3_bucket.strip(), cert_number.strip()),
            )


def verify_student_authorization(
    cert_number: str,
    student_id: Optional[str] = None,
    email: Optional[str] = None,
) -> bool:
    """
    Strict authorization check: verifies whether the provided student_id or email
    matches the owner of the given certificate.
    Prevents student A from viewing or downloading student B's certificate.
    """
    rec = get_by_cert_number(cert_number)
    if rec is None or rec.status != "VALID":
        return False

    matches = False
    if email and str(email).strip().lower() == str(rec.email).strip().lower():
        matches = True
    if student_id and rec.student_id and str(student_id).strip().lower() == str(rec.student_id).strip().lower():
        matches = True
    # If student_id was not set explicitly, allow checking against email username prefix
    if student_id and not rec.student_id:
        email_prefix = rec.email.split("@")[0].lower()
        if str(student_id).strip().lower() == email_prefix:
            matches = True

    return matches


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
    seq = max(int(row["next_seq"]), int(start_seq))
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


def _allocate_next_available_cert_number(
    conn: sqlite3.Connection,
    bucket: str,
    institute_code: str,
    batch_prefix: str,
    course_code: str,
    format_style: str,
    start_seq: int = 2075,
) -> str:
    """
    Finds and allocates the next strictly unused, collision-free certificate number.
    Checks the certificates table in real time to prevent UNIQUE constraint collisions.
    """
    row = conn.execute("SELECT next_seq FROM counters WHERE bucket = ?", (bucket,)).fetchone()
    current_next = row["next_seq"] if row else start_seq
    candidate_seq = max(int(current_next), int(start_seq))

    while True:
        candidate_number = format_cert_number(
            institute_code=institute_code,
            batch_prefix=batch_prefix,
            seq=candidate_seq,
            course_code=course_code,
            format_style=format_style,
        )
        exists = conn.execute(
            "SELECT 1 FROM certificates WHERE cert_number = ?", (candidate_number,)
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO counters (bucket, next_seq) VALUES (?, ?)
                ON CONFLICT(bucket) DO UPDATE SET next_seq = excluded.next_seq
                """,
                (bucket, candidate_seq + 1),
            )
            return candidate_number
        candidate_seq += 1


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
    student_id: Optional[str] = None,
    s3_key: Optional[str] = None,
    s3_bucket: Optional[str] = None,
) -> CertificateRecord:
    """
    Idempotent: if this (email, course) already has a certificate number,
    return the existing record untouched. Otherwise atomically allocate the
    next sequence number (e.g. 202505DVA2075) and persist a new record without collision.
    """
    key = student_key(email, course)
    effective_prefix = (batch_prefix or year or "202505").strip()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
        if row:
            if (student_id and not row["student_id"]) or (s3_key and not row["s3_key"]):
                conn.execute(
                    """
                    UPDATE certificates
                       SET student_id = COALESCE(student_id, ?),
                           s3_key = COALESCE(s3_key, ?),
                           s3_bucket = COALESCE(s3_bucket, ?)
                     WHERE student_key = ?
                    """,
                    (student_id, s3_key, s3_bucket, key),
                )
                row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
            return _row_to_record(row)

        if format_style == "LEGACY":
            bucket = f"{institute_code}|{course_code}|{effective_prefix}"
        else:
            bucket = f"{institute_code}|GLOBAL|{effective_prefix}"

        if existing_number and str(existing_number).strip():
            candidate = str(existing_number).strip()
            existing_row = conn.execute(
                "SELECT * FROM certificates WHERE cert_number = ?", (candidate,)
            ).fetchone()
            if existing_row:
                if existing_row["student_key"] == key:
                    cert_number = candidate
                else:
                    logger.warning(
                        "Certificate number %s is already assigned to %s (%s). Allocating next available number.",
                        candidate, existing_row["name"], existing_row["email"]
                    )
                    cert_number = _allocate_next_available_cert_number(
                        conn=conn,
                        bucket=bucket,
                        institute_code=institute_code,
                        batch_prefix=effective_prefix,
                        course_code=course_code,
                        format_style=format_style,
                        start_seq=start_seq,
                    )
            else:
                cert_number = candidate
        else:
            cert_number = _allocate_next_available_cert_number(
                conn=conn,
                bucket=bucket,
                institute_code=institute_code,
                batch_prefix=effective_prefix,
                course_code=course_code,
                format_style=format_style,
                start_seq=start_seq,
            )

        now = datetime.now(timezone.utc).isoformat()
        for attempt in range(5):
            try:
                conn.execute(
                    """
                    INSERT INTO certificates
                        (student_key, cert_number, name, email, course, completion_date,
                         status, created_at, last_sent_at, send_count, student_id, s3_key, s3_bucket)
                    VALUES (?, ?, ?, ?, ?, ?, 'VALID', ?, NULL, 0, ?, ?, ?)
                    """,
                    (key, cert_number, name, email, course, completion_date, now, student_id, s3_key, s3_bucket),
                )
                break
            except sqlite3.IntegrityError as ie:
                if "cert_number" in str(ie) or "UNIQUE" in str(ie):
                    logger.warning(
                        "Integrity collision on cert_number %s (attempt %d). Allocating next sequence: %s",
                        cert_number, attempt, ie
                    )
                    cert_number = _allocate_next_available_cert_number(
                        conn=conn,
                        bucket=bucket,
                        institute_code=institute_code,
                        batch_prefix=effective_prefix,
                        course_code=course_code,
                        format_style=format_style,
                        start_seq=start_seq,
                    )
                else:
                    raise

        row = conn.execute("SELECT * FROM certificates WHERE student_key = ?", (key,)).fetchone()
        return _row_to_record(row)


def delete_certificate(cert_number: str) -> bool:
    """Deletes a certificate record from the registry (e.g. for correcting errors or removing test records)."""
    with _lock, _connect() as conn:
        cursor = conn.execute("DELETE FROM certificates WHERE cert_number = ?", (cert_number.strip(),))
        deleted = cursor.rowcount > 0
    if deleted:
        try:
            export_public_json()
        except Exception:
            pass
    return deleted


def delete_test_certificates() -> int:
    """Removes sample/test certificates (e.g. sample.student@... or 'Sample Student')."""
    with _lock, _connect() as conn:
        cursor = conn.execute(
            """
            DELETE FROM certificates
             WHERE email LIKE '%sample%'
                OR email LIKE '%test%'
                OR name LIKE '%Sample Student%'
                OR name LIKE '%Test Student%'
            """
        )
        count = cursor.rowcount
    if count > 0:
        try:
            export_public_json()
        except Exception:
            pass
    return count


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


def list_all_certificates() -> list[CertificateRecord]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM certificates ORDER BY created_at DESC").fetchall()
        return [_row_to_record(r) for r in rows]


def search_certificates(query: str = "") -> list[CertificateRecord]:
    """Search certificates across name, email, cert_number, or course."""
    if not query or not str(query).strip():
        return list_all_certificates()
    q = f"%{str(query).strip().lower()}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM certificates
             WHERE LOWER(name) LIKE ?
                OR LOWER(email) LIKE ?
                OR LOWER(cert_number) LIKE ?
                OR LOWER(course) LIKE ?
             ORDER BY created_at DESC
            """,
            (q, q, q, q),
        ).fetchall()
        return [_row_to_record(r) for r in rows]


def list_skipped_rows() -> list:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM skipped_rows ORDER BY row_number ASC").fetchall()
        return [dict(r) for r in rows]


init_db()


def export_public_json(output_path: str = "certificates.json") -> int:
    """Exports all valid certificates from the SQLite database to a public JSON
    registry for GitHub Pages static verification."""
    import json
    with _connect() as conn:
        rows = conn.execute(
            "SELECT cert_number, name, course, completion_date, status, pdf_hash FROM certificates WHERE status = 'VALID'"
        ).fetchall()

    registry = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    registry.update(existing)
        except Exception:
            pass

    for r in rows:
        registry[r["cert_number"]] = {
            "cert_number": r["cert_number"],
            "name": r["name"],
            "course": r["course"],
            "completion_date": r["completion_date"],
            "expiry": "Lifetime",
            "status": "Active" if r["status"] == "VALID" else r["status"],
            "pdf_hash": r["pdf_hash"] or "",
        }

    # Ensure baseline template certificates exist if database is fresh
    if "202505DVA2073" not in registry:
        registry["202505DVA2073"] = {
            "cert_number": "202505DVA2073",
            "name": "Abhishek Singhal",
            "course": "Advanced Program in Industrial Data Science (APIDS)",
            "completion_date": "2026-09-07",
            "expiry": "Lifetime",
            "status": "Active",
            "pdf_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        }
    if "202505DVA2057" not in registry:
        registry["202505DVA2057"] = {
            "cert_number": "202505DVA2057",
            "name": "Priya Nair",
            "course": "Advanced Program in Data Analytics (APDA)",
            "completion_date": "2026-08-04",
            "expiry": "Lifetime",
            "status": "Active",
            "pdf_hash": "a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a",
        }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)

    alt_path = os.path.join(os.path.dirname(output_path) or ".", "verify", "certificates.json")
    try:
        os.makedirs(os.path.dirname(alt_path), exist_ok=True)
        with open(alt_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
    except Exception:
        pass

    try:
        import s3_service
        s3 = s3_service.get_s3_storage()
        if s3.is_configured():
            s3.get_client().put_object(
                Bucket=s3.bucket,
                Key="registry/certificates.json",
                Body=json.dumps(registry, indent=2).encode("utf-8"),
                ContentType="application/json",
                ACL="public-read",
            )
    except Exception:
        pass

    return len(registry)


# ---------------------------------------------------------------------------
# Multi-User Account Management & Authentication
# ---------------------------------------------------------------------------

def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Authenticates a user against the users table.
    Returns user dict on success, None on failure.
    """
    init_db()
    u_clean = (username or "").strip()
    p_clean = (password or "").strip()
    if not u_clean or not p_clean:
        return None

    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (u_clean,)).fetchone()
        if not row:
            return None
        if not row["is_active"]:
            logger.warning("User '%s' is deactivated and cannot log in.", u_clean)
            return None
        if _verify_password(p_clean, row["password_hash"]):
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE users SET last_login_at = ? WHERE username = ?", (now, row["username"]))
            return {
                "username": row["username"],
                "full_name": row["full_name"] or row["username"],
                "role": row["role"],
                "created_at": row["created_at"],
                "last_login_at": now,
            }
    return None


def create_user(
    username: str,
    password: str,
    full_name: str = "",
    role: str = "creator",
) -> Tuple[bool, str]:
    """
    Creates a new user account.
    Roles: 'admin' (can manage users and full system) or 'creator' (can generate & send certificates).
    """
    init_db()
    u_clean = (username or "").strip()
    p_clean = (password or "").strip()
    r_clean = (role or "creator").strip().lower()
    if r_clean not in ("admin", "creator"):
        r_clean = "creator"

    if len(u_clean) < 3:
        return False, "Username must be at least 3 characters long."
    if not re.match(r"^[a-zA-Z0-9_\-\.@]+$", u_clean):
        return False, "Username may only contain letters, numbers, dots, hyphens, and underscores."
    if len(p_clean) < 6:
        return False, "Password must be at least 6 characters long."

    with _lock, _connect() as conn:
        existing = conn.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(?)", (u_clean,)).fetchone()
        if existing:
            return False, f"User '{u_clean}' already exists."

        pwd_hash = _hash_password(p_clean)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO users (username, password_hash, full_name, role, created_at, last_login_at, is_active)
            VALUES (?, ?, ?, ?, ?, NULL, 1)
            """,
            (u_clean, pwd_hash, (full_name or "").strip(), r_clean, now),
        )
    return True, f"User '{u_clean}' created successfully with role '{r_clean}'."


def list_users() -> List[Dict[str, Any]]:
    """Returns list of all registered users."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username, full_name, role, created_at, last_login_at, is_active FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_user(username: str, current_user: str = "") -> Tuple[bool, str]:
    """
    Deletes a user account. Safeguards against deleting current user or last admin.
    """
    init_db()
    u_clean = (username or "").strip()
    if not u_clean:
        return False, "Invalid username."
    if u_clean.lower() == (current_user or "").strip().lower():
        return False, "You cannot delete your own active account."

    with _lock, _connect() as conn:
        user_row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (u_clean,)).fetchone()
        if not user_row:
            return False, f"User '{u_clean}' not found."

        if user_row["role"] == "admin":
            admin_cnt = conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()["cnt"]
            if admin_cnt <= 1:
                return False, "Cannot delete the only remaining administrator account."

        res = conn.execute("DELETE FROM users WHERE LOWER(username) = LOWER(?)", (u_clean,))
        if res.rowcount > 0:
            return True, f"User '{u_clean}' deleted successfully."
        return False, f"User '{u_clean}' not found."


def update_user_password(username: str, new_password: str) -> Tuple[bool, str]:
    """Resets or updates a user's password."""
    init_db()
    u_clean = (username or "").strip()
    p_clean = (new_password or "").strip()
    if len(p_clean) < 6:
        return False, "Password must be at least 6 characters long."
    pwd_hash = _hash_password(p_clean)
    with _lock, _connect() as conn:
        res = conn.execute("UPDATE users SET password_hash = ? WHERE LOWER(username) = LOWER(?)", (pwd_hash, u_clean))
        if res.rowcount > 0:
            return True, f"Password updated for '{u_clean}'."
        return False, f"User '{u_clean}' not found."


def toggle_user_status(username: str, is_active: bool, current_user: str = "") -> Tuple[bool, str]:
    """Enables or disables a user account."""
    init_db()
    u_clean = (username or "").strip()
    if u_clean.lower() == (current_user or "").strip().lower() and not is_active:
        return False, "You cannot deactivate your own account."
    val = 1 if is_active else 0
    with _lock, _connect() as conn:
        res = conn.execute("UPDATE users SET is_active = ? WHERE LOWER(username) = LOWER(?)", (val, u_clean))
        if res.rowcount > 0:
            status_txt = "activated" if is_active else "deactivated"
            return True, f"User '{u_clean}' {status_txt}."
        return False, f"User '{u_clean}' not found."


def get_system_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieves a persistent system configuration setting from SQLite."""
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        if row and row["value"] is not None:
            return row["value"]
    return default


def set_system_setting(key: str, value: str) -> None:
    """Saves or updates a persistent system configuration setting in SQLite."""
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, str(value), now),
        )


def set_system_settings_bulk(settings: Dict[str, str]) -> None:
    """Saves multiple system settings at once atomically."""
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        for k, v in settings.items():
            conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (k, str(v), now),
            )


def get_all_system_settings() -> Dict[str, str]:
    """Returns all system settings as a key-value dictionary."""
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


