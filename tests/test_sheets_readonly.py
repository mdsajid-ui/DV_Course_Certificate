"""
tests/test_sheets_readonly.py
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sheets_readonly as sr


def test_fuzzy_column_matching_and_incomplete_row_skipped():
    fake_json = {
        "values": [
            ["Full Name", "Email Address", "Program", "Date of Completion", "Certificate No"],
            ["Rohit Verma", "rohit@example.com", "APIDS", "10-09-2026", ""],
            ["", "blank@example.com", "APIDS", "", ""],
            ["Priya Nair", "priya@example.com", "APDA", "11-09-2026", "DVA-APDA-2025-000042"],
        ]
    }
    with patch("sheets_readonly.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, ok=True, json=lambda: fake_json)
        rows = sr.get_roster("https://docs.google.com/spreadsheets/d/FAKEID/edit", api_key="k")

    assert len(rows) == 2
    assert rows[0].name == "Rohit Verma"
    assert rows[0].email == "rohit@example.com"
    assert rows[1].existing_certificate_number == "DVA-APDA-2025-000042"


def test_403_raises_helpful_sharing_error():
    with patch("sheets_readonly.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=403, ok=False, text="Forbidden")
        try:
            sr.get_roster("https://docs.google.com/spreadsheets/d/FAKEID/edit", api_key="k")
            assert False, "expected SheetAccessError"
        except sr.SheetAccessError as e:
            assert "Anyone with the link" in str(e)


def test_missing_required_column_raises():
    fake_json = {"values": [["Program", "Date"], ["APIDS", "10-09-2026"]]}
    with patch("sheets_readonly.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, ok=True, json=lambda: fake_json)
        try:
            sr.get_roster("https://docs.google.com/spreadsheets/d/FAKEID/edit", api_key="k")
            assert False, "expected SheetAccessError"
        except sr.SheetAccessError as e:
            assert "name" in str(e) or "email" in str(e)


def test_extract_spreadsheet_id_from_full_url():
    url = "https://docs.google.com/spreadsheets/d/1vTrLQiIvB6fMTUgsQtuJcnFR-Z3VVY_ALTRKF2dH0Jw/edit?usp=sharing"
    assert sr.extract_spreadsheet_id(url) == "1vTrLQiIvB6fMTUgsQtuJcnFR-Z3VVY_ALTRKF2dH0Jw"
