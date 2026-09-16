"""
tests/test_s3_service.py
Unit tests for S3 storage service, HMAC access tokens, student authorization checks,
and secure certificate download endpoints.
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import s3_service


def _fresh_store(tmp_path):
    os.environ["CERT_DB_PATH"] = str(tmp_path / "s3_test_certs.db")
    import importlib
    import cert_store
    importlib.reload(cert_store)
    return cert_store


# --------------------------------------------------------------------------
# 1. Object Key Path Tests
# --------------------------------------------------------------------------
def test_build_object_key_standard():
    key = s3_service.build_object_key(year=2026, student_id="STU1001", filename="certificate.pdf")
    assert key == "certificates/2026/STU1001/certificate.pdf"


def test_build_object_key_string_year_and_custom_filename():
    key = s3_service.build_object_key(year="2025", student_id="DVA-99", filename="dv_cert.pdf")
    assert key == "certificates/2025/DVA-99/dv_cert.pdf"


def test_build_object_key_sanitizes_special_characters():
    key = s3_service.build_object_key(year="2026", student_id="user/name?#", filename="cert.pdf")
    assert "/" not in key.split("/")[2]
    assert "?" not in key
    assert "#" not in key


def test_build_object_key_fallback_when_empty():
    key = s3_service.build_object_key(year="", student_id="", filename="")
    assert key.startswith("certificates/")
    assert key.endswith("/certificate.pdf")


# --------------------------------------------------------------------------
# 2. HMAC Token Issuance and Anti-Tamper Tests
# --------------------------------------------------------------------------
def test_generate_and_verify_student_access_token():
    cert_number = "202505DVA2075"
    email = "rahul@example.com"
    student_id = "STU101"

    token = s3_service.generate_student_access_token(
        cert_number=cert_number,
        email=email,
        student_id=student_id,
        expires_in=3600,
    )
    assert token is not None and len(token) > 20

    payload = s3_service.verify_student_access_token(token)
    assert payload["cert_number"] == cert_number
    assert payload["email"] == email
    assert payload["student_id"] == student_id


def test_token_rejects_tampered_payload_and_signature():
    cert_number = "202505DVA2075"
    email = "rahul@example.com"
    student_id = "STU101"

    token = s3_service.generate_student_access_token(
        cert_number=cert_number,
        email=email,
        student_id=student_id,
    )

    # 1. Attacker tampers with signature
    tampered_sig = token[:-5] + "12345"
    with pytest.raises(s3_service.TokenValidationError):
        s3_service.verify_student_access_token(tampered_sig)

    # 2. Attacker modifies payload to claim another student's cert without valid HMAC key
    import json, base64
    parts = token.split(".")
    raw_bytes = base64.urlsafe_b64decode(parts[0] + "==")
    data = json.loads(raw_bytes)
    data["cert_number"] = "202505DVA9999"
    tampered_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    tampered_token = f"{tampered_b64}.{parts[1]}"
    with pytest.raises(s3_service.TokenValidationError):
        s3_service.verify_student_access_token(tampered_token)


def test_token_expiration():
    cert_number = "202505DVA2075"
    # Generate token that is already expired
    token = s3_service.generate_student_access_token(
        cert_number=cert_number,
        email="rahul@example.com",
        student_id="STU101",
        expires_in=-10,  # Negative duration -> expired
    )

    with pytest.raises(s3_service.TokenValidationError, match="expired"):
        s3_service.verify_student_access_token(token)


# --------------------------------------------------------------------------
# 3. Database Authorization and Metadata Tests
# --------------------------------------------------------------------------
def test_cert_store_verify_student_authorization(tmp_path):
    cs = _fresh_store(tmp_path)
    rec = cs.issue_or_get_certificate_number(
        name="Aarav Sharma",
        email="aarav@example.com",
        course="APIDS",
        completion_date="15-09-2026",
        student_id="STU-1008",
        institute_code="DVA",
        course_code="APIDS",
        year="2026",
    )

    # Authorized by exact student_id
    assert cs.verify_student_authorization(rec.cert_number, student_id="STU-1008") is True
    # Authorized case-insensitively
    assert cs.verify_student_authorization(rec.cert_number, student_id="stu-1008") is True

    # Authorized by exact email
    assert cs.verify_student_authorization(rec.cert_number, email="aarav@example.com") is True
    assert cs.verify_student_authorization(rec.cert_number, email="AARAV@example.com") is True

    # Unauthorized student ID
    assert cs.verify_student_authorization(rec.cert_number, student_id="STU-9999") is False

    # Unauthorized email
    assert cs.verify_student_authorization(rec.cert_number, email="stranger@example.com") is False

    # Non-existent certificate
    assert cs.verify_student_authorization("DOES-NOT-EXIST", student_id="STU-1008") is False


def test_cert_store_update_s3_metadata(tmp_path):
    cs = _fresh_store(tmp_path)
    rec = cs.issue_or_get_certificate_number(
        name="Sara Khan",
        email="sara@example.com",
        course="APDA",
        completion_date="12-09-2026",
        student_id="STU-2044",
        institute_code="DVA",
        course_code="APDA",
        year="2026",
    )

    s3_key = "certificates/2026/STU-2044/certificate.pdf"
    s3_bucket = "b1storage"

    cs.update_s3_metadata(
        cert_number=rec.cert_number,
        s3_key=s3_key,
        s3_bucket=s3_bucket,
        student_id="STU-2044",
    )

    stored = cs.get_by_cert_number(rec.cert_number)
    assert stored is not None
    assert stored.s3_key == s3_key
    assert stored.s3_bucket == s3_bucket
    assert stored.student_id == "STU-2044"


# --------------------------------------------------------------------------
# 4. Verification App Download Endpoints Tests
# --------------------------------------------------------------------------
def test_verify_app_download_api_flow(tmp_path):
    cs = _fresh_store(tmp_path)
    rec = cs.issue_or_get_certificate_number(
        name="Karan Mehta",
        email="karan@example.com",
        course="APIDS",
        completion_date="10-09-2026",
        student_id="STU-3090",
        institute_code="DVA",
        course_code="APIDS",
        year="2026",
    )
    s3_key = "certificates/2026/STU-3090/certificate.pdf"
    cs.update_s3_metadata(rec.cert_number, s3_key=s3_key, s3_bucket="b1storage", student_id="STU-3090")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "verify_service"))
    import importlib
    import verify_app
    importlib.reload(verify_app)
    verify_app.cert_store = cs

    client = verify_app.app.test_client()

    # 4.1 POST /api/certificate/request-download with valid credentials
    resp = client.post(
        "/api/certificate/request-download",
        json={"cert_number": rec.cert_number, "student_id": "STU-3090"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["cert_number"] == rec.cert_number
    assert "token" in data
    assert "download_url" in data
    issued_token = data["token"]

    # 4.2 POST /api/certificate/request-download with wrong credentials returns 403
    resp_bad = client.post(
        "/api/certificate/request-download",
        json={"cert_number": rec.cert_number, "student_id": "UNAUTHORIZED_ID"},
    )
    assert resp_bad.status_code == 403
    assert resp_bad.get_json()["status"] in ("error", "forbidden")

    # 4.3 GET /api/certificate/download with valid token and JSON header
    resp_dl = client.get(
        f"/api/certificate/download?token={issued_token}",
        headers={"Accept": "application/json"},
    )
    assert resp_dl.status_code == 200
    dl_data = resp_dl.get_json()
    assert dl_data["status"] == "success"
    assert "download_url" in dl_data

    # 4.4 GET /api/certificate/download with invalid token returns 401/403
    resp_invalid = client.get(
        "/api/certificate/download?token=INVALID_TOKEN_123",
        headers={"Accept": "application/json"},
    )
    assert resp_invalid.status_code in (401, 403)

    # 4.5 GET /download with valid token returns branded HTML page
    resp_page = client.get(f"/download?token={issued_token}")
    assert resp_page.status_code == 200
    page_text = resp_page.get_data(as_text=True)
    assert "Certificate Ready for Download" in page_text
    assert "Karan Mehta" in page_text

    # 4.6 GET /download without token returns student authentication form
    resp_form = client.get("/download")
    assert resp_form.status_code == 200
    form_text = resp_form.get_data(as_text=True)
    assert "Student Certificate Portal" in form_text
    assert "authForm" in form_text
