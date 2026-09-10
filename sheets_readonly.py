"""
sheets_readonly.py
===================
Reads the student roster from a Google Sheet using an API key — no OAuth,
no service account.

IMPORTANT limitation (by the user's explicit choice, not a shortcut I took):
Google's Sheets API only allows API-key access to a spreadsheet that is
shared as "Anyone with the link -> Viewer". An API key carries no user
identity, so Google will not use it to authorize access to a private sheet.
This means:
  * Reading the roster: works, as long as the sheet is link-shared.
  * Writing anything back to the sheet (e.g. a "Certificate Sent" column):
    NOT possible with an API key. That's why cert_store.py exists as the
    local source of truth for certificate numbers and send status instead
    of a sheet column.

If the roster ever needs to stay private, the fix is switching this one
module to OAuth or a service account — sheets_readonly.get_roster() is the
only place that would need to change; nothing else in the app talks to
Google directly.

Column matching is header-based and fuzzy (case/space/punctuation
insensitive) so it survives the sheet owner renaming or reordering columns,
matching the pattern already used in utils.py for Excel uploads.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

import requests

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Same spirit as utils.py's COLUMN_ALIASES — flexible header matching.
COLUMN_ALIASES = {
    "name": ["name", "student name", "full name", "candidate name"],
    "email": ["email", "email address", "e-mail", "mail id", "email id"],
    "course": ["course", "course name", "program", "programme"],
    "completion_date": [
        "completion date",
        "date of completion",
        "date completed",
        "completed on",
    ],
    "status": ["status", "completion status", "course status"],
    "certificate_number": [
        "certificate number",
        "certificate no",
        "cert number",
        "cert no",
        "certificate registration number",
    ],
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").strip().lower()).strip()


def _match_columns(headers: List[str]) -> dict:
    normalized = {i: _norm_header(h) for i, h in enumerate(headers)}
    resolved = {}
    for field, aliases in COLUMN_ALIASES.items():
        alias_set = {_norm_header(a) for a in aliases}
        for idx, norm in normalized.items():
            if norm in alias_set:
                resolved[field] = idx
                break
    return resolved


@dataclass
class RosterRow:
    row_number: int  # 1-indexed sheet row, for reference/debugging only
    name: str
    email: str
    course: str
    completion_date: Optional[str]
    status: Optional[str]
    existing_certificate_number: Optional[str]


class SheetAccessError(RuntimeError):
    pass


def extract_spreadsheet_id(url_or_id: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def get_roster(
    spreadsheet_url_or_id: str,
    worksheet_name: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[RosterRow]:
    """
    Fetch and parse the roster. Raises SheetAccessError with a human-readable
    message on auth/sharing/format problems, so the UI can show it directly
    instead of a raw traceback.
    """
    try:
        import streamlit as st
        sec = st.secrets
    except Exception:
        sec = {}

    api_key = api_key or sec.get("GOOGLE_SHEETS_API_KEY", os.environ.get("GOOGLE_SHEETS_API_KEY"))
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url_or_id)

    if not api_key:
        # Direct CSV export fallback: works with any public Google Sheet without requiring a Google Cloud API key!
        csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"
        if worksheet_name:
            csv_url += f"&sheet={worksheet_name}"
        resp = requests.get(csv_url, timeout=15)
        if not resp.ok:
            raise SheetAccessError(
                "Could not fetch Google Sheet. Please confirm the sheet sharing is set to "
                "'Anyone with the link can view' (Viewer permission)."
            )
        import csv
        import io
        values = list(csv.reader(io.StringIO(resp.text)))
    else:
        rng = f"{worksheet_name}" if worksheet_name else "A1:Z"
        url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{rng}"
        resp = requests.get(url, params={"key": api_key}, timeout=15)
        if resp.status_code == 403:
            raise SheetAccessError(
                "Google returned 403 Forbidden. With an API key, the sheet must be "
                "shared as 'Anyone with the link — Viewer'."
            )
        if resp.status_code == 404:
            raise SheetAccessError("Sheet or worksheet not found. Check the URL/ID and worksheet name.")
        if not resp.ok:
            raise SheetAccessError(f"Google Sheets API error {resp.status_code}: {resp.text[:300]}")
        values = resp.json().get("values", [])
    if not values:
        return []

    headers = values[0]
    col_map = _match_columns(headers)
    missing = [f for f in ("name", "email") if f not in col_map]
    if missing:
        raise SheetAccessError(
            "Could not find required column(s): "
            + ", ".join(missing)
            + f". Detected headers: {headers}"
        )

    rows: List[RosterRow] = []
    for i, raw_row in enumerate(values[1:], start=2):
        def cell(field: str) -> Optional[str]:
            if field not in col_map:
                return None
            idx = col_map[field]
            return raw_row[idx].strip() if idx < len(raw_row) else None

        name = cell("name")
        email = cell("email")
        if not name or not email:
            continue

        rows.append(
            RosterRow(
                row_number=i,
                name=name,
                email=email,
                course=cell("course") or "Unknown Course",
                completion_date=cell("completion_date"),
                status=cell("status"),
                existing_certificate_number=cell("certificate_number"),
            )
        )

    return rows
