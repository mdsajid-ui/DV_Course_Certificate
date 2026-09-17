"""
utils.py
--------
Shared helpers: Excel validation, logging setup, and report building.
"""

import logging
import os
from datetime import datetime
from dotenv import load_dotenv

import pandas as pd

load_dotenv()

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


def update_env_file(key_values: dict) -> None:
    """Updates or adds key-value pairs to the local .env file and in os.environ."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(base_dir, ".env")
    lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    written_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in key_values:
                new_lines.append(f"{k}={key_values[k]}\n")
                written_keys.add(k)
                os.environ[k] = str(key_values[k])
                continue
        new_lines.append(line)

    for k, v in key_values.items():
        if k not in written_keys:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"{k}={v}\n")
            os.environ[k] = str(v)

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass


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
    "Name": ["name", "student", "participant", "candidate"],
    "Mobile Number": ["mobile", "phone", "contact", "whatsapp", "cell", "tel"],
    "Email ID": ["email", "e-mail", "mail"],
    "Course": ["course", "program", "programme", "course name"],
    "Completion Date": ["completion date", "date of completion", "date", "completed on"],
    "Certificate Number": ["certificate number", "certificate no", "cert number", "cert no"],
}


def _normalize(s: str) -> str:
    """Lowercase and strip everything except letters/digits for loose matching."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def find_matching_column(columns, required: str):
    """
    Find the column that best matches a field by keyword.
    Tries, in order: exact normalized match, then substring/keyword match.
    """
    keywords = COLUMN_KEYWORDS.get(required, [required.lower()])
    norm_cols = {col: _normalize(col) for col in columns}

    # 1) Exact normalized match against the field name itself
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
    Confirms Name and Email ID columns exist (flexibly matched
    by keyword). Mobile Number is matched if present, or optional.
    Returns (is_valid, column_map, missing_columns).
    """
    column_map = {}
    missing = []
    # Primary required fields
    for required in ["Name", "Email ID"]:
        match = find_matching_column(df.columns, required)
        if match:
            column_map[required] = match
        else:
            missing.append(required)

    # Optional fields (Mobile Number, Course, Completion Date, Certificate Number)
    for opt in ["Mobile Number", "Course", "Completion Date", "Certificate Number"]:
        match = find_matching_column(df.columns, opt)
        if match:
            column_map[opt] = match

    return (len(missing) == 0), column_map, missing


def normalize_records(df: pd.DataFrame, column_map: dict):
    """Return a list of dicts with clean, standardized keys."""
    records = []
    for _, row in df.iterrows():
        name_col = column_map.get("Name")
        email_col = column_map.get("Email ID")
        mobile_col = column_map.get("Mobile Number")
        course_col = column_map.get("Course")
        date_col = column_map.get("Completion Date")
        cert_col = column_map.get("Certificate Number")

        name = str(row[name_col]).strip() if name_col and name_col in row else ""
        email = str(row[email_col]).strip() if email_col and email_col in row else ""
        mobile = str(row[mobile_col]).strip() if mobile_col and mobile_col in row else ""
        course = str(row[course_col]).strip() if course_col and course_col in row else ""
        comp_date = str(row[date_col]).strip() if date_col and date_col in row else ""
        cert_no = str(row[cert_col]).strip() if cert_col and cert_col in row else ""

        if mobile.lower() in ("nan", "none"):
            mobile = ""
        if course.lower() in ("nan", "none"):
            course = ""
        if comp_date.lower() in ("nan", "none"):
            comp_date = ""
        if cert_no.lower() in ("nan", "none"):
            cert_no = ""
        if name.lower() in ("nan", "none") or not name:
            continue
        if email.lower() in ("nan", "none"):
            email = ""

        rec = {
            "Name": name,
            "Mobile Number": mobile,
            "Email ID": email,
        }
        if course:
            rec["Course"] = course
        if comp_date:
            rec["Completion Date"] = comp_date
        if cert_no:
            rec["Certificate Number"] = cert_no

        records.append(rec)
    return records


def build_report_dataframe(results: list) -> pd.DataFrame:
    """
    results: list of dicts with keys:
        Name, Mobile Number, Email ID, Course, Certificate Number,
        Certificate Generated, Email Sent, Sent Date & Time, Error Message
    """
    columns = [
        "Name",
        "Mobile Number",
        "Email ID",
        "Course",
        "Certificate Number",
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
