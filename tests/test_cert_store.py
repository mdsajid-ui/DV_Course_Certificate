"""
tests/test_cert_store.py
Run with: pytest tests/test_cert_store.py  (or plain: python -m pytest tests)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_store(tmp_path):
    """cert_store reads CERT_DB_PATH at import time, so point it at a temp
    file and re-import a fresh module instance per test."""
    os.environ["CERT_DB_PATH"] = str(tmp_path / "test_certs.db")
    import importlib
    import cert_store
    importlib.reload(cert_store)
    return cert_store


def test_same_student_same_course_gets_same_number(tmp_path):
    cs = _fresh_store(tmp_path)
    kwargs = dict(
        name="Rohit Verma", email="rohit@example.com", course="APIDS",
        completion_date="10-09-2026", institute_code="DVA", course_code="APIDS", year="2026",
    )
    first = cs.issue_or_get_certificate_number(**kwargs)
    second = cs.issue_or_get_certificate_number(**kwargs)  # simulates "resend"
    assert first.cert_number == second.cert_number


def test_different_students_get_sequential_numbers(tmp_path):
    cs = _fresh_store(tmp_path)
    a = cs.issue_or_get_certificate_number(
        name="A", email="a@example.com", course="APIDS", completion_date="10-09-2026",
        institute_code="DVA", course_code="APIDS", year="2026",
    )
    b = cs.issue_or_get_certificate_number(
        name="B", email="b@example.com", course="APIDS", completion_date="10-09-2026",
        institute_code="DVA", course_code="APIDS", year="2026",
    )
    assert a.cert_number == "DVA-APIDS-2026-000001"
    assert b.cert_number == "DVA-APIDS-2026-000002"


def test_same_email_different_course_gets_a_new_number(tmp_path):
    cs = _fresh_store(tmp_path)
    a = cs.issue_or_get_certificate_number(
        name="A", email="a@example.com", course="APIDS", completion_date="10-09-2026",
        institute_code="DVA", course_code="APIDS", year="2026",
    )
    b = cs.issue_or_get_certificate_number(
        name="A", email="a@example.com", course="APDA", completion_date="10-09-2026",
        institute_code="DVA", course_code="APDA", year="2026",
    )
    assert a.cert_number != b.cert_number


def test_mark_sent_increments_count(tmp_path):
    cs = _fresh_store(tmp_path)
    rec = cs.issue_or_get_certificate_number(
        name="A", email="a@example.com", course="APIDS", completion_date="10-09-2026",
        institute_code="DVA", course_code="APIDS", year="2026",
    )
    cs.mark_sent(rec.cert_number)
    cs.mark_sent(rec.cert_number)  # resend
    updated = cs.get_by_cert_number(rec.cert_number)
    assert updated.send_count == 2
    assert updated.last_sent_at is not None


def test_lookup_by_cert_number_for_verification(tmp_path):
    cs = _fresh_store(tmp_path)
    rec = cs.issue_or_get_certificate_number(
        name="Priya Nair", email="priya@example.com", course="APDA", completion_date="11-09-2026",
        institute_code="DVA", course_code="APDA", year="2025",
    )
    found = cs.get_by_cert_number(rec.cert_number)
    assert found is not None
    assert found.name == "Priya Nair"
    assert cs.get_by_cert_number("BOGUS-NUMBER") is None
