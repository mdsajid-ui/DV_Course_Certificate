"""
utils.py
--------
Shared helpers: Excel validation, logging setup, and report building.
"""

import logging
import os
from datetime import datetime

import pandas as pd

REQUIRED_COLUMNS = ["Name", "Mobile Number", "Email ID"]

LOG_PATH = "email_log.txt"


def get_secret(name: str, default=None):
    """
    Reads a config value from Streamlit secrets first, falling back to an
    environment variable, then `default`.

    st.secrets.get(...) raises StreamlitSecretNotFoundError (not a KeyError)
    when no secrets.toml exists at all — which is the normal case for a
    deployment that only uses a .env file / plain environment variables, as
    this project's own setup instructions describe. Calling st.secrets.get()
    directly therefore crashes the whole app (including the login screen) on
    any such deployment. This wrapper is the one place that risk is handled;
    every other module should call this instead of touching st.secrets
    directly.
    """
    try:
        import streamlit as st
        val = st.secrets.get(name)
        if val not in (None, ""):
            return val
    except Exception:
        pass
    return os.environ.get(name, default)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("cert_email_app")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        logger.addHandler(fh)
    return logger


def log_event(recipient: str, status: str, error: str = ""):
    logger = setup_logger()
    detail = f"Recipient={recipient} | Status={status}"
    if error:
        detail += f" | Error={error}"
    logger.info(detail)


# Keywords used to recognize each required field, in priority order.
# Real-world files use all sorts of headers (STU_NAME, MOBILE-1, EMAIL ID, etc.)
# so we match by keyword/substring rather than requiring an exact name.
COLUMN_KEYWORDS = {
    "Name": ["name"],
    "Mobile Number": ["mobile", "phone", "contact", "whatsapp", "cell"],
    "Email ID": ["email", "e-mail", "mail"],
}


def _normalize(s: str) -> str:
    """Lowercase and strip everything except letters/digits for loose matching."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def find_matching_column(columns, required: str):
    """
    Find the column that best matches a required field by keyword.
    Tries, in order: exact normalized match, then substring/keyword match.
    """
    keywords = COLUMN_KEYWORDS.get(required, [required.lower()])
    norm_cols = {col: _normalize(col) for col in columns}

    # 1) Exact normalized match against the required field name itself
    req_norm = _normalize(required)
    for col, norm in norm_cols.items():
        if norm == req_norm:
            return col

    # 2) Substring match against any recognized keyword for this field
    for col, norm in norm_cols.items():
        if any(kw.replace(" ", "").replace("-", "") in norm for kw in keywords):
            return col

    return None


def validate_excel_columns(df: pd.DataFrame):
    """
    Confirms Name, Mobile Number, and Email ID columns exist (flexibly matched
    by keyword, so headers like STU_NAME / MOBILE-1 / EMAIL ID are recognized).
    Returns (is_valid, column_map, missing_columns).
    """
    column_map = {}
    missing = []
    for required in REQUIRED_COLUMNS:
        match = find_matching_column(df.columns, required)
        if match:
            column_map[required] = match
        else:
            missing.append(required)
    return (len(missing) == 0), column_map, missing


def normalize_records(df: pd.DataFrame, column_map: dict):
    """Return a list of dicts with clean, standardized keys."""
    records = []
    for _, row in df.iterrows():
        name = str(row[column_map["Name"]]).strip()
        mobile = str(row[column_map["Mobile Number"]]).strip()
        email = str(row[column_map["Email ID"]]).strip()
        if mobile.lower() == "nan":
            mobile = ""
        if name.lower() == "nan" or not name:
            continue
        records.append({"Name": name, "Mobile Number": mobile, "Email ID": email})
    return records


def build_report_dataframe(results: list) -> pd.DataFrame:
    """
    results: list of dicts with keys:
        Name, Mobile Number, Email ID, Certificate Generated, Email Sent,
        Sent Date & Time, Error Message
    """
    columns = [
        "Name",
        "Mobile Number",
        "Email ID",
        "Certificate Generated",
        "Email Sent",
        "Sent Date & Time",
        "Error Message",
    ]
    df = pd.DataFrame(results)
    for c in columns:
        if c not in df.columns:
            df[c] = ""
    return df[columns]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
