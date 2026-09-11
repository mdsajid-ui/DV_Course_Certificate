"""
sheets_writer.py
=================
Optional write-back to the Google Sheet using a service account, so the
sheet itself can hold Certificate Status / Certificate Number / Generated
Date / Email Status / Email Sent Date — as requested in the "keep everything
trackable from the sheet" requirement.

Why this is a separate module from sheets_readonly.py, and why it's
optional:
`sheets_readonly.py` uses an API key (or a public CSV export) because that
was the original, explicit choice — it needs no Google Cloud setup beyond
"get an API key" and no sharing of credentials files. An API key cannot
write cells; only a service account (or OAuth) can. So this module adds a
*second*, independent path that is only used when a service account is
actually configured (`GOOGLE_SERVICE_ACCOUNT_JSON` set). If it isn't
configured, the app falls back to exactly the previous behavior: read-only
access via sheets_readonly.py, and the "export CSV to paste back in
manually" button. Nothing about the read-only path changed.

Setup (only needed if you want the sheet to auto-update):
  1. Google Cloud Console -> create a service account -> create a JSON key.
  2. Share the Google Sheet with the service account's email address
     (found inside the JSON as "client_email") as an Editor. This does NOT
     require "Anyone with the link" sharing — the sheet can stay private.
  3. Set GOOGLE_SERVICE_ACCOUNT_JSON to the path of that JSON file (or set
     GOOGLE_SERVICE_ACCOUNT_JSON_CONTENTS to the raw JSON, for platforms
     like Streamlit Cloud where uploading a file isn't convenient — put it
     in Streamlit secrets, never in source control).

Safety: this module only ever writes to a fixed set of *status* columns
that it creates itself if missing (appended after the existing sheet
columns). It never touches Name/Email/Course or any other existing column,
and never deletes rows.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from sheets_readonly import extract_spreadsheet_id
from utils import get_secret

STATUS_COLUMNS = [
    "Certificate Number",
    "Certificate Status",
    "Generated Date",
    "Email Status",
    "Email Sent Date",
    "Verification URL",
]


class SheetWriteError(RuntimeError):
    pass


def _load_credentials():
    """Returns a google.oauth2.service_account.Credentials, or None if no
    service account is configured (caller should treat that as "write-back
    disabled, fall back to read-only")."""
    raw_json = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENTS")
    json_path = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not raw_json and not json_path:
        return None

    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if raw_json:
        info = json.loads(raw_json)
        return Credentials.from_service_account_info(info, scopes=scopes)
    if json_path and os.path.exists(json_path):
        return Credentials.from_service_account_file(json_path, scopes=scopes)
    raise SheetWriteError(f"GOOGLE_SERVICE_ACCOUNT_JSON path does not exist: {json_path}")


def is_configured() -> bool:
    try:
        return _load_credentials() is not None
    except Exception:
        return False


@dataclass
class _SheetHandle:
    worksheet: "object"
    header: list
    col_index: dict  # column name (normalized) -> 1-based index


def _open_worksheet(spreadsheet_url_or_id: str, worksheet_name: Optional[str]) -> _SheetHandle:
    import gspread

    creds = _load_credentials()
    if creds is None:
        raise SheetWriteError(
            "No service account configured (GOOGLE_SERVICE_ACCOUNT_JSON). "
            "Write-back is disabled; use the CSV export instead."
        )
    client = gspread.authorize(creds)
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)
    try:
        sh = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.APIError as e:
        raise SheetWriteError(
            "Google rejected the write request. Confirm the sheet is shared "
            "with the service account's client_email as an Editor. "
            f"Details: {e}"
        )
    ws = sh.worksheet(worksheet_name) if worksheet_name else sh.sheet1

    header = ws.row_values(1)
    changed = False
    for col in STATUS_COLUMNS:
        if col not in header:
            header.append(col)
            changed = True
    if changed:
        ws.update("A1", [header])

    col_index = {name: i + 1 for i, name in enumerate(header)}
    return _SheetHandle(worksheet=ws, header=header, col_index=col_index)


def _find_row_by_email(handle: _SheetHandle, email: str) -> Optional[int]:
    email_col_names = ["Email", "Email Address", "E-mail", "Mail ID", "Email ID"]
    email_col = next((handle.col_index[c] for c in email_col_names if c in handle.col_index), None)
    if email_col is None:
        raise SheetWriteError("Could not find an Email column in the sheet to match rows against.")
    values = handle.worksheet.col_values(email_col)
    target = (email or "").strip().lower()
    for i, v in enumerate(values[1:], start=2):  # skip header
        if (v or "").strip().lower() == target:
            return i
    return None


def update_student_status(
    spreadsheet_url_or_id: str,
    *,
    email: str,
    worksheet_name: Optional[str] = None,
    certificate_number: Optional[str] = None,
    certificate_status: Optional[str] = None,
    generated_date: Optional[str] = None,
    email_status: Optional[str] = None,
    email_sent_date: Optional[str] = None,
    verification_url: Optional[str] = None,
) -> None:
    """
    Writes only the fields passed (non-None) into that student's row,
    matched by email. Raises SheetWriteError with a human-readable message
    on any failure — callers should catch this and continue (a sheet
    write failing should never block certificate generation or sending,
    since cert_store.py remains the authoritative local record either way).
    """
    handle = _open_worksheet(spreadsheet_url_or_id, worksheet_name)
    row = _find_row_by_email(handle, email)
    if row is None:
        raise SheetWriteError(f"No row found with email '{email}' — was the sheet edited since the last fetch?")

    updates = {
        "Certificate Number": certificate_number,
        "Certificate Status": certificate_status,
        "Generated Date": generated_date,
        "Email Status": email_status,
        "Email Sent Date": email_sent_date,
        "Verification URL": verification_url,
    }
    for col_name, value in updates.items():
        if value is None:
            continue
        col = handle.col_index.get(col_name)
        if col is None:
            continue
        handle.worksheet.update_cell(row, col, value)
