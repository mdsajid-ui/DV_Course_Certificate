"""
verify_service/verify_app.py
=============================
A standalone Flask app that serves the public certificate
verification page at the exact path:

    GET /verify/<certificate_number>

Matches the mobile verification reference design with official DV Analytics branding.
"""

from __future__ import annotations

import html
import os
import sys

from flask import Flask, abort, request, jsonify, redirect
import s3_service

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cert_store  # noqa: E402

app = Flask(__name__)

SEAL_SVG = """﻿<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="100%" height="100%">
  <defs>
    <path id="topCurve" d="M 40,150 A 110,110 0 1,1 260,150" fill="none" />
    <path id="bottomCurve" d="M 252,150 A 102,102 0 0,1 48,150" fill="none" />
    <linearGradient id="blueGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#142c6e"/>
      <stop offset="100%" stop-color="#091538"/>
    </linearGradient>
  </defs>

  <!-- Outer Rings -->
  <circle cx="150" cy="150" r="142" fill="none" stroke="#142c6e" stroke-width="4"/>
  <circle cx="150" cy="150" r="135" fill="none" stroke="#142c6e" stroke-width="1.5"/>

  <!-- Top Text -->
  <text font-family="'Inter', 'Segoe UI', Arial, sans-serif" font-size="11.5" font-weight="700" fill="#142c6e" letter-spacing="1.8">
    <textPath href="#topCurve" startOffset="50%" text-anchor="middle">
      DV DATA &amp; ANALYTICS • VERIFIED
    </textPath>
  </text>

  <!-- Bottom Text -->
  <text font-family="'Inter', 'Segoe UI', Arial, sans-serif" font-size="9" font-weight="700" fill="#142c6e" letter-spacing="1.5">
    <textPath href="#bottomCurve" startOffset="50%" text-anchor="middle">
      IT - ITeS SSC NASSCOM ACCREDITED
    </textPath>
  </text>

  <!-- Inner Circle Border -->
  <circle cx="150" cy="150" r="88" fill="none" stroke="#142c6e" stroke-width="3.5"/>
  <circle cx="150" cy="150" r="84" fill="#f8fafc" stroke="#142c6e" stroke-width="1"/>

  <!-- Globe Grid Lines inside inner circle -->
  <g clip-path="url(#globeClip)">
    <clipPath id="globeClip">
      <circle cx="150" cy="150" r="83"/>
    </clipPath>
    <rect x="65" y="65" width="170" height="170" fill="#142c6e"/>
    <ellipse cx="150" cy="150" rx="83" ry="55" fill="none" stroke="#ffffff" stroke-width="1.2" opacity="0.6"/>
    <ellipse cx="150" cy="150" rx="83" ry="28" fill="none" stroke="#ffffff" stroke-width="1.2" opacity="0.6"/>
    <line x1="67" y1="150" x2="233" y2="150" stroke="#ffffff" stroke-width="1.4" opacity="0.7"/>
    <ellipse cx="150" cy="150" rx="55" ry="83" fill="none" stroke="#ffffff" stroke-width="1.2" opacity="0.6"/>
    <ellipse cx="150" cy="150" rx="28" ry="83" fill="none" stroke="#ffffff" stroke-width="1.2" opacity="0.6"/>
    <line x1="150" y1="67" x2="150" y2="233" stroke="#ffffff" stroke-width="1.4" opacity="0.7"/>
  </g>

  <!-- Center White Emblem / Banner for DV Analytics -->
  <rect x="70" y="123" width="160" height="54" rx="6" fill="#ffffff" stroke="#142c6e" stroke-width="2.5"/>
  
  <!-- DV Brand Monogram / Text -->
  <text x="150" y="152" font-family="'Segoe UI', Arial, sans-serif" font-size="20" font-weight="900" fill="#142c6e" text-anchor="middle" letter-spacing="1">
    DV <tspan fill="#e63946">ANALYTICS</tspan>
  </text>
  <text x="150" y="167" font-family="'Segoe UI', Arial, sans-serif" font-size="7.5" font-weight="700" fill="#64748b" text-anchor="middle" letter-spacing="1.2">
    TRANSFORMING YOU
  </text>
</svg>
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Official Certificate Verification · DV Analytics</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background-color: #ffffff;
    color: #1e293b;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px 16px 80px;
  }
  .container {
    width: 100%;
    max-width: 420px;
    margin: 0 auto;
    text-align: center;
  }
  .auth-header {
    margin-top: 12px;
    margin-bottom: 24px;
  }
  .auth-title {
    font-size: 1.45rem;
    font-weight: 700;
    color: #38b000;
    letter-spacing: -0.2px;
    margin-bottom: 8px;
  }
  .auth-title.invalid {
    color: #d90429;
  }
  .cert-label {
    font-size: 1.15rem;
    color: #2b2d42;
    font-weight: 500;
    margin-bottom: 2px;
  }
  .cert-number-head {
    font-size: 1.25rem;
    font-weight: 600;
    color: #1a1a24;
    letter-spacing: 0.5px;
  }
  .cert-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05);
    padding: 32px 24px 28px;
    text-align: left;
    margin-bottom: 20px;
    position: relative;
  }
  .logo-box {
    text-align: center;
    margin-bottom: 28px;
  }
  .logo-box svg {
    width: 140px;
    height: 140px;
    display: inline-block;
  }
  .details-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .detail-item {
    font-size: 1.05rem;
    line-height: 1.5;
    color: #334155;
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    gap: 8px;
  }
  .detail-key {
    font-weight: 500;
    color: #475569;
    white-space: nowrap;
    min-width: 125px;
  }
  .detail-sep {
    color: #64748b;
    font-weight: 500;
  }
  .detail-val {
    font-weight: 600;
    color: #0f172a;
    word-break: break-word;
  }
  .status-active {
    color: #2b9348;
    font-weight: 700;
  }
  .security-seal {
    background: #f8fafc;
    border: 1px dashed #cbd5e1;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 0.76rem;
    color: #475569;
    text-align: left;
    margin-top: 20px;
    line-height: 1.4;
  }
  .security-seal strong {
    display: block;
    margin-bottom: 3px;
    color: #1e293b;
  }
  .hash-box {
    font-family: monospace;
    font-size: 0.7rem;
    color: #64748b;
    word-break: break-all;
    background: #ffffff;
    padding: 3px 6px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
    margin-top: 4px;
  }
  .unverified-box {
    background: #fff5f5;
    border: 1px solid #fed7d7;
    border-radius: 8px;
    padding: 24px 20px;
    text-align: center;
    color: #c53030;
    margin-bottom: 20px;
  }
  .unverified-box h3 {
    font-size: 1.15rem;
    font-weight: 700;
    margin-bottom: 8px;
  }
  .unverified-box p {
    font-size: 0.9rem;
    color: #742a2a;
    line-height: 1.5;
  }
  .authority-footer {
    font-size: 0.78rem;
    color: #94a3b8;
    text-align: center;
    margin-top: 18px;
    line-height: 1.5;
  }
  .chat-pill {
    position: fixed;
    bottom: 24px;
    right: 20px;
    z-index: 1000;
    background: #000435;
    color: #ffffff;
    padding: 9px 18px;
    border-radius: 9999px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.92rem;
    font-weight: 600;
    text-decoration: none;
    box-shadow: 0 4px 14px rgba(0, 4, 53, 0.35);
    cursor: pointer;
    border: none;
  }
  .chat-dot {
    width: 9px;
    height: 9px;
    background-color: #00e676;
    border-radius: 50%;
    display: inline-block;
    box-shadow: 0 0 8px #00e676;
  }
  .modal-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(15, 23, 42, 0.6);
    z-index: 2000;
    align-items: flex-end;
    justify-content: center;
    backdrop-filter: blur(2px);
  }
  .modal-overlay.open { display: flex; }
  .modal-sheet {
    background: #ffffff;
    width: 100%;
    max-width: 440px;
    border-radius: 20px 20px 0 0;
    padding: 24px 20px 32px;
    box-shadow: 0 -10px 30px rgba(0,0,0,0.2);
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }
  .modal-header h4 { font-size: 1.15rem; font-weight: 700; color: #0f172a; }
  .close-btn {
    background: #f1f5f9;
    border: none;
    font-size: 1.2rem;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    cursor: pointer;
    color: #64748b;
  }
  .contact-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    background: #f8fafc;
    border-radius: 10px;
    margin-bottom: 10px;
    text-decoration: none;
    color: #0f172a;
    font-weight: 500;
    border: 1px solid #e2e8f0;
  }
</style>
</head>
<body>
  <div class="container">
    {body}
  </div>

  <button class="chat-pill" id="chatBtn" aria-label="Chat Support">
    <span class="chat-dot"></span> Chat
  </button>

  <div class="modal-overlay" id="supportModal">
    <div class="modal-sheet">
      <div class="modal-header">
        <h4>DV Analytics Support</h4>
        <button class="close-btn" id="closeModal">&times;</button>
      </div>
      <p style="font-size: 0.88rem; color: #64748b; margin-bottom: 16px;">
        Have questions regarding this credential? Connect with the DV Analytics Academic Registry.
      </p>
      <a href="mailto:md.sajid@dvdataanalytics.com?subject=Certificate%20Verification%20Inquiry" class="contact-item">
        <span style="font-size: 1.3rem;">✉️</span>
        <div>
          <div style="font-size: 0.95rem; font-weight: 600;">Email Academic Desk</div>
          <div style="font-size: 0.8rem; color: #64748b;">md.sajid@dvdataanalytics.com</div>
        </div>
      </a>
      <a href="https://wa.me/?text=Hello%20DV%20Analytics%20Support,%20I%20have%20an%20inquiry%20regarding%20certificate%20verification" target="_blank" class="contact-item">
        <span style="font-size: 1.3rem;">💬</span>
        <div>
          <div style="font-size: 0.95rem; font-weight: 600;">WhatsApp Inquiries</div>
          <div style="font-size: 0.8rem; color: #64748b;">Direct chat with coordinator</div>
        </div>
      </a>
    </div>
  </div>

  <script>
    document.getElementById('chatBtn').addEventListener('click', function() {
      document.getElementById('supportModal').classList.add('open');
    });
    document.getElementById('closeModal').addEventListener('click', function() {
      document.getElementById('supportModal').classList.remove('open');
    });
    document.getElementById('supportModal').addEventListener('click', function(e) {
      if (e.target === document.getElementById('supportModal')) {
        document.getElementById('supportModal').classList.remove('open');
      }
    });
  </script>
</body>
</html>"""


@app.get("/verify/<certificate_number>")
def verify(certificate_number: str):
    record = cert_store.get_by_cert_number(certificate_number)
    safe_number = html.escape(certificate_number)

    if record is None or record.status != "VALID":
        body = f"""
          <div class="auth-header">
            <div class="auth-title invalid">Authentication Unsuccessful</div>
            <div class="cert-label">Certificate No :</div>
            <div class="cert-number-head">{safe_number}</div>
          </div>

          <div class="unverified-box">
            <h3>RECORD NOT FOUND</h3>
            <p>This certificate number could not be authenticated in the official DV Analytics registry. If you believe this is an error, please contact DV Analytics administration.</p>
          </div>
          <div class="authority-footer">
            Official Registry · DV Analytics · Unverified Record
          </div>
        """
        return PAGE_TEMPLATE.replace('{body}', body), 404

    safe_name = html.escape(record.name)
    safe_course = html.escape(record.course)
    safe_date = html.escape(record.completion_date or "Verified")
    pdf_hash = getattr(record, "pdf_hash", None) or ""

    hash_html = f'<div class="hash-box">SHA-256: {html.escape(pdf_hash[:40])}...</div>' if pdf_hash else ""

    body = f"""
      <div class="auth-header">
        <div class="auth-title">Authentication Successful</div>
        <div class="cert-label">Certificate No :</div>
        <div class="cert-number-head">{safe_number}</div>
      </div>

      <div class="cert-card">
        <div class="logo-box">
          {SEAL_SVG}
        </div>

        <div class="details-list">
          <div class="detail-item">
            <span class="detail-key">Certificate Id</span>
            <span class="detail-sep">:</span>
            <span class="detail-val">{safe_number}</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Name</span>
            <span class="detail-sep">:</span>
            <span class="detail-val">{safe_name}</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Course Name</span>
            <span class="detail-sep">:</span>
            <span class="detail-val">{safe_course}</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Effective from</span>
            <span class="detail-sep">:</span>
            <span class="detail-val">{safe_date}</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Expiry</span>
            <span class="detail-sep">:</span>
            <span class="detail-val">Lifetime</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Status</span>
            <span class="detail-sep">:</span>
            <span class="detail-val status-active">Active</span>
          </div>
        </div>

        <div class="security-seal">
          <strong>🔒 OFFICIAL CERTIFICATE VERIFIED &amp; IMMUTABLE</strong>
          This document is permanently registered with DV Analytics and accredited in partnership with IT - ITeS SSC NASSCOM.
          {hash_html}
        </div>
      </div>

      <div class="authority-footer">
        Official Credential Registered with <strong>DV Analytics</strong><br>
        IT - ITeS SSC NASSCOM Accredited · All Rights Reserved
      </div>
    """
    return PAGE_TEMPLATE.replace('{body}', body)


@app.get("/verify")
def verify_missing_number():
    abort(404)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}




# ===========================================================================
# Secure S3 Certificate Delivery API & Student Download Portal
# ===========================================================================

DOWNLOAD_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Secure Certificate Delivery · DV Analytics</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background-color: #f8fafc;
    color: #1e293b;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px 16px 80px;
  }
  .container {
    width: 100%;
    max-width: 440px;
    margin: 0 auto;
    text-align: center;
  }
  .auth-header {
    margin-top: 12px;
    margin-bottom: 24px;
  }
  .auth-title {
    font-size: 1.45rem;
    font-weight: 700;
    color: #142c6e;
    letter-spacing: -0.2px;
    margin-bottom: 6px;
  }
  .auth-sub {
    font-size: 0.95rem;
    color: #64748b;
  }
  .card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.06);
    padding: 32px 24px;
    text-align: left;
    margin-bottom: 20px;
  }
  .logo-box {
    text-align: center;
    margin-bottom: 24px;
  }
  .logo-box svg {
    width: 110px;
    height: 110px;
    display: inline-block;
  }
  .detail-row {
    margin-bottom: 14px;
  }
  .detail-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .detail-value {
    font-size: 1.05rem;
    font-weight: 700;
    color: #0f172a;
    margin-top: 2px;
  }
  .btn-download {
    display: block;
    width: 100%;
    padding: 14px;
    background: #142c6e;
    color: #ffffff;
    text-align: center;
    border-radius: 8px;
    font-size: 1.05rem;
    font-weight: 700;
    text-decoration: none;
    border: none;
    cursor: pointer;
    margin-top: 20px;
    box-shadow: 0 4px 14px rgba(20, 44, 110, 0.25);
    transition: background-color 0.2s, transform 0.1s;
  }
  .btn-download:hover {
    background: #0b1a45;
  }
  .btn-download:active {
    transform: scale(0.98);
  }
  .security-notice {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 12px;
    font-size: 0.8rem;
    color: #475569;
    margin-top: 18px;
    line-height: 1.4;
  }
  .form-group {
    margin-bottom: 16px;
  }
  .form-label {
    display: block;
    font-size: 0.88rem;
    font-weight: 600;
    color: #334155;
    margin-bottom: 6px;
  }
  .form-input {
    width: 100%;
    padding: 12px 14px;
    border: 1.5px solid #cbd5e1;
    border-radius: 8px;
    font-size: 1rem;
    font-family: inherit;
    outline: none;
  }
  .form-input:focus {
    border-color: #142c6e;
  }
  .alert-error {
    background: #fff5f5;
    border: 1px solid #fed7d7;
    color: #c53030;
    padding: 12px 14px;
    border-radius: 8px;
    font-size: 0.88rem;
    margin-bottom: 16px;
    display: none;
  }
  .authority-footer {
    font-size: 0.78rem;
    color: #94a3b8;
    text-align: center;
    margin-top: 18px;
    line-height: 1.5;
  }
</style>
</head>
<body>
  <div class="container">
    {body}
  </div>
</body>
</html>"""


@app.get("/api/certificate/download")
def api_download_certificate():
    """
    Secure download endpoint:
    1. Validates HMAC student access token or student credentials.
    2. Enforces strict authorization (prevents cross-student access).
    3. Generates a temporary 1-hour presigned S3 URL.
    4. Redirects student directly to S3 or returns JSON.
    """
    token = request.args.get("token")
    cert_no = request.args.get("cert_number") or request.args.get("cert_no")
    email = request.args.get("email")
    student_id = request.args.get("student_id")
    as_json = request.args.get("format") == "json" or request.headers.get("Accept") == "application/json"

    # Strategy A: Authenticate via Cryptographic Token
    if token:
        try:
            payload = s3_service.verify_student_access_token(token)
            target_cert = payload.get("cert_number")
            token_email = payload.get("email")
            token_student_id = payload.get("student_id")

            rec = cert_store.get_by_cert_number(target_cert)
            if not rec or rec.status != "VALID":
                return jsonify({"status": "error", "message": "Certificate not found or revoked."}), 404

            # Verify authorization against DB record
            if not cert_store.verify_student_authorization(target_cert, student_id=token_student_id, email=token_email):
                return jsonify({"status": "error", "message": "Forbidden: Token unauthorized for this certificate."}), 403

            s3_key = rec.s3_key or s3_service.get_s3_storage().build_object_key(
                year=rec.created_at[:4] if rec.created_at else "2026",
                student_id=rec.student_id or rec.email.split("@")[0],
                filename="certificate.pdf",
            )
            download_url = s3_service.generate_presigned_download_url(
                s3_key=s3_key,
                expires_in=int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
                filename=f"{rec.cert_number}.pdf",
            )

            if as_json:
                return jsonify({
                    "status": "success",
                    "certificate_id": rec.cert_number,
                    "student_name": rec.name,
                    "course": rec.course,
                    "download_url": download_url,
                    "expires_in": int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
                })
            return redirect(download_url, code=302)

        except s3_service.TokenValidationError as t_err:
            return jsonify({"status": "error", "message": str(t_err)}), 401
        except Exception as e:
            return jsonify({"status": "error", "message": f"Download generation failed: {e}"}), 500

    # Strategy B: Authenticate via credentials
    if cert_no and (email or student_id):
        if not cert_store.verify_student_authorization(cert_no, student_id=student_id, email=email):
            return jsonify({"status": "error", "message": "Forbidden: Provided credentials do not match this certificate."}), 403

        rec = cert_store.get_by_cert_number(cert_no)
        if not rec or rec.status != "VALID":
            return jsonify({"status": "error", "message": "Certificate record not found."}), 404

        s3_key = rec.s3_key or s3_service.get_s3_storage().build_object_key(
            year=rec.created_at[:4] if rec.created_at else "2026",
            student_id=rec.student_id or rec.email.split("@")[0],
            filename="certificate.pdf",
        )
        download_url = s3_service.generate_presigned_download_url(
            s3_key=s3_key,
            expires_in=int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
            filename=f"{rec.cert_number}.pdf",
        )
        if as_json:
            return jsonify({
                "status": "success",
                "certificate_id": rec.cert_number,
                "student_name": rec.name,
                "course": rec.course,
                "download_url": download_url,
                "expires_in": int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
            })
        return redirect(download_url, code=302)

    return jsonify({"status": "error", "message": "Missing required authentication token or credentials."}), 400


@app.post("/api/certificate/request-download")
def api_request_download():
    """
    POST API for student authentication & download link issuance:
    Validates student identity against certificate ownership.
    Returns temporary presigned URL and HMAC access token.
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    cert_no = (data.get("cert_number") or data.get("cert_no") or "").strip()
    email = (data.get("email") or "").strip()
    student_id = (data.get("student_id") or "").strip()

    if not cert_no:
        return jsonify({"status": "error", "message": "Certificate registration number is required."}), 400

    if not email and not student_id:
        return jsonify({"status": "error", "message": "Registered email or student ID is required for verification."}), 400

    rec = cert_store.get_by_cert_number(cert_no)
    if not rec or rec.status != "VALID":
        return jsonify({"status": "error", "message": "Certificate record could not be found in the registry."}), 404

    # Strict authorization enforcement
    if not cert_store.verify_student_authorization(cert_no, student_id=student_id, email=email):
        return jsonify({
            "status": "error",
            "message": "Authorization failed: Provided credentials do not match the registered recipient of this certificate.",
        }), 403

    effective_student_id = student_id or rec.student_id or rec.email.split("@")[0]
    token = s3_service.generate_student_access_token(
        cert_number=rec.cert_number,
        student_id=effective_student_id,
        email=rec.email,
        expires_in=int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
    )

    s3_key = rec.s3_key or s3_service.get_s3_storage().build_object_key(
        year=rec.created_at[:4] if rec.created_at else "2026",
        student_id=effective_student_id,
        filename="certificate.pdf",
    )

    download_url = s3_service.generate_presigned_download_url(
        s3_key=s3_key,
        expires_in=int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
        filename=f"{rec.cert_number}.pdf",
    )

    return jsonify({
        "status": "success",
        "certificate_id": rec.cert_number,
        "cert_number": rec.cert_number,
        "student_name": rec.name,
        "course": rec.course,
        "issue_date": rec.completion_date,
        "download_url": download_url,
        "access_token": token,
        "token": token,
        "expires_in": int(os.environ.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)),
    })


@app.get("/download")
@app.get("/student/download")
def student_download_page():
    """
    Student Certificate Download Portal (Web UI)
    """
    token = request.args.get("token")

    # If student clicked direct tokenized link from email
    if token:
        try:
            payload = s3_service.verify_student_access_token(token)
            cert_no = payload.get("cert_number")
            rec = cert_store.get_by_cert_number(cert_no)
            if rec and rec.status == "VALID":
                direct_download_api = f"/api/certificate/download?token={token}"
                body = f"""
                  <div class="auth-header">
                    <div class="auth-title">Certificate Ready for Download</div>
                    <div class="auth-sub">Official Authenticated Credential · DV Analytics</div>
                  </div>

                  <div class="card">
                    <div class="logo-box">
                      {SEAL_SVG}
                    </div>

                    <div class="detail-row">
                      <div class="detail-label">Candidate Name</div>
                      <div class="detail-value">{html.escape(rec.name)}</div>
                    </div>

                    <div class="detail-row">
                      <div class="detail-label">Course / Program</div>
                      <div class="detail-value">{html.escape(rec.course)}</div>
                    </div>

                    <div class="detail-row">
                      <div class="detail-label">Certificate Registration Number</div>
                      <div class="detail-value">{html.escape(rec.cert_number)}</div>
                    </div>

                    <div class="detail-row">
                      <div class="detail-label">Date of Completion</div>
                      <div class="detail-value">{html.escape(rec.completion_date or "Verified")}</div>
                    </div>

                    <a href="{direct_download_api}" class="btn-download">
                      ⬇️ Download Official Certificate (PDF)
                    </a>

                    <div class="security-notice">
                      <strong>🔒 Secure S3 Cloud Delivery</strong><br>
                      This certificate is stored securely in private cloud storage. This temporary download link is valid for 1 hour.
                    </div>
                  </div>

                  <div class="authority-footer">
                    Official Credential System · DV Analytics Academic Registry<br>
                    IT - ITeS SSC NASSCOM Accredited
                  </div>
                """
                return DOWNLOAD_PAGE_TEMPLATE.replace("{body}", body)
        except Exception as e:
            # Token error: fall through to manual login form with alert
            pass

    # Default: Student Authentication Form
    body = """
      <div class="auth-header">
        <div class="auth-title">Student Certificate Portal</div>
        <div class="auth-sub">Access and download your official course certificate</div>
      </div>

      <div class="card">
        <div class="logo-box">
          __SEAL_SVG__
        </div>

        <div id="alertBox" class="alert-error"></div>

        <form id="authForm">
          <div class="form-group">
            <label class="form-label" for="certInput">Certificate Registration Number</label>
            <input type="text" id="certInput" class="form-input" placeholder="e.g. 202505DVA2075" required />
          </div>

          <div class="form-group">
            <label class="form-label" for="emailInput">Registered Email Address or Student ID</label>
            <input type="text" id="emailInput" class="form-input" placeholder="e.g. student@example.com" required />
          </div>

          <button type="submit" id="submitBtn" class="btn-download">
            🔓 Authenticate &amp; Access Certificate
          </button>
        </form>

        <div id="resultBox" style="display:none; margin-top:20px;">
          <div style="border-top:1px solid #e2e8f0; padding-top:18px;">
            <div class="detail-row">
              <div class="detail-label">Student Name</div>
              <div class="detail-value" id="resName"></div>
            </div>
            <div class="detail-row">
              <div class="detail-label">Program</div>
              <div class="detail-value" id="resCourse"></div>
            </div>
            <a id="resDownloadBtn" href="#" class="btn-download" target="_blank">
              ⬇️ Download Certificate PDF (S3 Secure)
            </a>
            <div class="security-notice" style="margin-top:14px;">
              ⏰ A fresh 1-hour presigned S3 download URL has been issued.
            </div>
          </div>
        </div>

        <div class="security-notice" style="margin-top:20px;">
          <strong>🛡️ Anti-Unauthorized Protection:</strong><br>
          Access is restricted strictly to the student who completed the program. Credentials must match registered records.
        </div>
      </div>

      <div class="authority-footer">
        DV Analytics Academic Registry · All Rights Reserved
      </div>

      <script>
        document.getElementById('authForm').addEventListener('submit', async function(e) {
          e.preventDefault();
          const certNo = document.getElementById('certInput').value.trim();
          const identifier = document.getElementById('emailInput').value.trim();
          const alertBox = document.getElementById('alertBox');
          const submitBtn = document.getElementById('submitBtn');
          const resultBox = document.getElementById('resultBox');

          alertBox.style.display = 'none';
          resultBox.style.display = 'none';
          submitBtn.disabled = true;
          submitBtn.innerText = 'Verifying authorization...';

          try {
            const resp = await fetch('/api/certificate/request-download', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                cert_number: certNo,
                email: identifier.includes('@') ? identifier : '',
                student_id: !identifier.includes('@') ? identifier : ''
              })
            });
            const data = await resp.json();

            if (!resp.ok || data.status !== 'success') {
              alertBox.innerText = data.message || 'Authorization failed. Please check your credentials.';
              alertBox.style.display = 'block';
              submitBtn.disabled = false;
              submitBtn.innerText = '🔓 Authenticate & Access Certificate';
              return;
            }

            // Success: show download
            document.getElementById('resName').innerText = data.student_name;
            document.getElementById('resCourse').innerText = data.course;
            document.getElementById('resDownloadBtn').href = data.download_url;
            resultBox.style.display = 'block';
            submitBtn.innerText = '✓ Authorized';
          } catch(err) {
            alertBox.innerText = 'Network or server error occurred. Please try again.';
            alertBox.style.display = 'block';
            submitBtn.disabled = false;
            submitBtn.innerText = '🔓 Authenticate & Access Certificate';
          }
        });
      </script>
    """
    return DOWNLOAD_PAGE_TEMPLATE.replace("{body}", body.replace("__SEAL_SVG__", SEAL_SVG))


if __name__ == "__main__":
    port = int(os.environ.get("VERIFY_SERVICE_PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
