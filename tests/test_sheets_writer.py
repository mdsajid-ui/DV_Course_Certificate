"""
tests/test_sheets_writer.py
Unit tests for sheets_writer.py. No live Google credentials are available in
this environment, so gspread itself is mocked — these tests verify our
logic (column bootstrap, email-based row matching, graceful no-op when no
service account is configured), not gspread's own behavior.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import sheets_writer


def test_is_configured_false_when_no_service_account_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENTS", raising=False)
    assert sheets_writer.is_configured() is False


def test_update_student_status_raises_clear_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENTS", raising=False)
    with pytest.raises(sheets_writer.SheetWriteError, match="No service account configured"):
        sheets_writer.update_student_status(
            "https://docs.google.com/spreadsheets/d/abc123/edit",
            email="student@example.com",
            certificate_status="GENERATED",
        )


class _FakeWorksheet:
    def __init__(self, rows):
        # rows[0] is the header row
        self._rows = [list(r) for r in rows]

    def row_values(self, n):
        return list(self._rows[n - 1])

    def col_values(self, col):
        return [row[col - 1] if col - 1 < len(row) else "" for row in self._rows]

    def update(self, rng, values):
        self._rows[0] = list(values[0])

    def update_cell(self, row, col, value):
        while len(self._rows) < row:
            self._rows.append([])
        r = self._rows[row - 1]
        while len(r) < col:
            r.append("")
        r[col - 1] = value


def test_open_worksheet_adds_missing_status_columns(monkeypatch):
    ws = _FakeWorksheet([["Name", "Email", "Course"], ["Asha", "asha@example.com", "APIDS"]])

    monkeypatch.setattr(sheets_writer, "_load_credentials", lambda: object())

    class _FakeSpreadsheet:
        def worksheet(self, name):
            return ws

        sheet1 = ws

    class _FakeClient:
        def open_by_key(self, key):
            return _FakeSpreadsheet()

    fake_gspread = type("m", (), {"authorize": staticmethod(lambda creds: _FakeClient()), "exceptions": type("e", (), {"APIError": Exception})})
    monkeypatch.setitem(sys.modules, "gspread", fake_gspread)

    handle = sheets_writer._open_worksheet("https://docs.google.com/spreadsheets/d/abc123/edit", None)
    for col in sheets_writer.STATUS_COLUMNS:
        assert col in handle.header


def test_update_student_status_writes_only_matched_row(monkeypatch):
    ws = _FakeWorksheet(
        [
            ["Name", "Email", "Course"] + sheets_writer.STATUS_COLUMNS,
            ["Asha", "asha@example.com", "APIDS", "", "", "", "", "", ""],
            ["Ravi", "ravi@example.com", "APIDS", "", "", "", "", "", ""],
        ]
    )
    monkeypatch.setattr(sheets_writer, "_load_credentials", lambda: object())

    class _FakeSpreadsheet:
        def worksheet(self, name):
            return ws

        sheet1 = ws

    class _FakeClient:
        def open_by_key(self, key):
            return _FakeSpreadsheet()

    fake_gspread = type("m", (), {"authorize": staticmethod(lambda creds: _FakeClient()), "exceptions": type("e", (), {"APIError": Exception})})
    monkeypatch.setitem(sys.modules, "gspread", fake_gspread)

    sheets_writer.update_student_status(
        "https://docs.google.com/spreadsheets/d/abc123/edit",
        email="ravi@example.com",
        certificate_number="DVA-APIDS-2026-000002",
        certificate_status="GENERATED",
    )

    header = ws.row_values(1)
    ravi_row = ws.row_values(3)
    asha_row = ws.row_values(2)
    cert_num_col = header.index("Certificate Number")
    assert ravi_row[cert_num_col] == "DVA-APIDS-2026-000002"
    assert asha_row[cert_num_col] == ""  # untouched


def test_update_student_status_raises_when_email_not_found(monkeypatch):
    ws = _FakeWorksheet([["Name", "Email"] + sheets_writer.STATUS_COLUMNS, ["Asha", "asha@example.com"]])
    monkeypatch.setattr(sheets_writer, "_load_credentials", lambda: object())

    class _FakeSpreadsheet:
        def worksheet(self, name):
            return ws

        sheet1 = ws

    class _FakeClient:
        def open_by_key(self, key):
            return _FakeSpreadsheet()

    fake_gspread = type("m", (), {"authorize": staticmethod(lambda creds: _FakeClient()), "exceptions": type("e", (), {"APIError": Exception})})
    monkeypatch.setitem(sys.modules, "gspread", fake_gspread)

    with pytest.raises(sheets_writer.SheetWriteError, match="No row found"):
        sheets_writer.update_student_status(
            "https://docs.google.com/spreadsheets/d/abc123/edit",
            email="nobody@example.com",
            certificate_status="GENERATED",
        )
