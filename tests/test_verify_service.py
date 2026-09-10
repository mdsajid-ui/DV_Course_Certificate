"""
tests/test_verify_service.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_store(tmp_path):
    os.environ["CERT_DB_PATH"] = str(tmp_path / "verify_test.db")
    import importlib
    import cert_store
    importlib.reload(cert_store)
    return cert_store


def test_verify_valid_certificate(tmp_path):
    cs = _fresh_store(tmp_path)
    rec = cs.issue_or_get_certificate_number(
        name="Priya Nair", email="priya@example.com", course="APDA", completion_date="11-09-2026",
        institute_code="DVA", course_code="APDA", year="2025",
    )

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "verify_service"))
    import importlib
    import verify_app
    importlib.reload(verify_app)  # picks up the reloaded cert_store's DB path
    verify_app.cert_store = cs

    client = verify_app.app.test_client()
    resp = client.get(f"/verify/{rec.cert_number}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "CERTIFICATE VERIFIED" in body
    assert "Priya Nair" in body
    assert "APDA" in body
    # never expose email/phone on the public page
    assert "priya@example.com" not in body


def test_verify_invalid_certificate_returns_404(tmp_path):
    cs = _fresh_store(tmp_path)

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "verify_service"))
    import importlib
    import verify_app
    importlib.reload(verify_app)
    verify_app.cert_store = cs

    client = verify_app.app.test_client()
    resp = client.get("/verify/DOES-NOT-EXIST-0001")
    assert resp.status_code == 404
    assert "NOT FOUND" in resp.get_data(as_text=True)
