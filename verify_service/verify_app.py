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

from flask import Flask, abort

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


if __name__ == "__main__":
    port = int(os.environ.get("VERIFY_SERVICE_PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
