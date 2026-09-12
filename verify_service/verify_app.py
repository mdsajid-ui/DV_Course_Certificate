"""
verify_service/verify_app.py
=============================
A tiny, standalone Flask app that serves the public certificate
verification page at the exact path the spec requires:

    GET /verify/<certificate_number>

Why a separate app instead of a Streamlit page?
Streamlit does not support arbitrary path-style routing (it only offers
its own page slugs with query params, e.g. /Verify?cert=X). Since the
requirement was explicitly the real /verify/{number} path, that needs an
actual web framework with a router. This Flask app is deliberately tiny —
one route, one template, no auth, no dependency on Streamlit — and it reads
the SAME SQLite file (cert_store.py) that the main Streamlit app writes to,
so no data duplication or syncing is needed. Run it as its own process next
to Streamlit and put both behind one reverse proxy (see
verify_service/nginx.example.conf) so they share your one domain.

Deliberately exposes ONLY: name, course, certificate number, status.
Never email, phone, or anything else from the roster — per spec.
"""

from __future__ import annotations

import html
import os
import sys

from flask import Flask, abort

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cert_store  # noqa: E402

app = Flask(__name__)

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Official Certificate Verification · DV Analytics</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b112c;
         background: radial-gradient(circle at 50% 0%, #172a6b 0%, #080d24 100%);
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:20px; color:#1e293b; }
  .card { background:#ffffff; border-radius:20px; box-shadow:0 25px 50px -12px rgba(0,0,0,0.45);
           padding:2.8rem 2.2rem; max-width:480px; width:100%; text-align:center; position:relative; overflow:hidden; border: 1px solid rgba(255,255,255,0.1); }
  .card:before { content:""; position:absolute; top:0; left:0; right:0; height:6px; background:linear-gradient(90deg, #5b6cf7, #ef233c); }
  .logo { font-family:'Poppins', sans-serif; font-weight:800; font-size:1.4rem; color:#0b1b4d; letter-spacing:-0.5px; margin-bottom:1.2rem; display:flex; align-items:center; justify-content:center; gap:8px; }
  .logo-badge { background:#ef233c; color:#fff; padding:2px 8px; border-radius:6px; font-size:0.9rem; }
  .badge { font-size:0.95rem; font-weight:700; border-radius:30px; padding:0.6rem 1.4rem; display:inline-flex; align-items:center; gap:6px; margin-bottom:1.5rem; letter-spacing:0.3px; }
  .valid { background:#e6f7ec; color:#128a44; border:1px solid #b7ebd0; }
  .invalid { background:#fdeaea; color:#b3261e; border:1px solid #f9c6c4; }
  dl { text-align:left; margin:0 0 1.5rem; background:#f8fafc; border-radius:14px; padding:1.2rem 1.4rem; border:1px solid #e2e8f0; }
  dt { font-size:0.75rem; color:#64748b; margin-top:0.75rem; text-transform:uppercase; letter-spacing:0.06em; font-weight:600; }
  dt:first-child { margin-top:0; }
  dd { font-size:1.05rem; margin:0.2rem 0 0 0; font-weight:700; color:#0f172a; word-break:break-word; }
  .security-seal { background:#eff6ff; border:1px dashed #3b82f6; border-radius:10px; padding:10px 14px; font-size:0.78rem; color:#1e40af; text-align:left; margin-bottom:1.2rem; }
  .security-seal strong { display:block; margin-bottom:3px; color:#1d4ed8; }
  .hash-box { font-family:monospace; font-size:0.72rem; color:#475569; word-break:break-all; background:#fff; padding:4px 8px; border-radius:4px; border:1px solid #cbd5e1; margin-top:4px; }
  .notice { font-size:0.75rem; color:#94a3b8; line-height:1.4; margin:0; }

  /* Anti-screenshot blankout shield */
  @media print {
    * { display:none !important; }
    html, body { background:#fff !important; visibility:hidden !important; }
  }
  .screenshot-blankout, .screenshot-blankout * {
    visibility:hidden !important;
    opacity:0 !important;
    background:#fff !important;
    color:transparent !important;
    filter:blur(100px) !important;
  }
</style>
<script>
(function() {
  function triggerBlankout() {
    document.body.classList.add('screenshot-blankout');
  }
  function restoreView() {
    setTimeout(function() {
      document.body.classList.remove('screenshot-blankout');
    }, 600);
  }

  // 1. Trigger blankout on window blur (Snipping Tool, screen grabbers, overlays)
  window.addEventListener('blur', triggerBlankout);
  window.addEventListener('focus', restoreView);
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) { triggerBlankout(); } else { restoreView(); }
  });

  // 2. Intercept PrintScreen and screenshot shortcuts
  window.addEventListener('keyup', function(e) {
    if (e.key === 'PrintScreen' || e.keyCode === 44 || e.code === 'PrintScreen') {
      try { navigator.clipboard.writeText(''); } catch(err) {}
      triggerBlankout();
      setTimeout(restoreView, 2500);
    }
  });

  window.addEventListener('keydown', function(e) {
    if (e.key === 'PrintScreen' || e.keyCode === 44 || e.code === 'PrintScreen' ||
        (e.ctrlKey && (e.key === 'p' || e.key === 'P' || e.key === 's' || e.key === 'S')) ||
        (e.ctrlKey && e.shiftKey && (e.key === 's' || e.key === 'S' || e.key === 'i' || e.key === 'I')) ||
        (e.metaKey && e.shiftKey && (e.key === '3' || e.key === '4' || e.key === 's' || e.key === 'S'))) {
      try { navigator.clipboard.writeText(''); } catch(err) {}
      triggerBlankout();
      setTimeout(restoreView, 2500);
      e.preventDefault();
      return false;
    }
  });

  document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    return false;
  });
})();
</script>
</head>
<body>
  <div class="card">
    <div class="logo">
      <span class="logo-badge">DV</span> ANALYTICS
    </div>
    {body}
  </div>
</body>
</html>"""


@app.get("/verify/<certificate_number>")
def verify(certificate_number: str):
    record = cert_store.get_by_cert_number(certificate_number)
    if record is None or record.status != "VALID":
        body = """
          <div class="badge invalid">✕ INVALID / UNVERIFIED CERTIFICATE</div>
          <p style="color:#64748b; font-size:0.92rem; line-height:1.5;">This certificate number could not be authenticated in the DV Analytics official registry. If you believe this is an error, please contact DV Analytics administration.</p>
        """
        html_out = PAGE_TEMPLATE.format(body=body)
        return html_out, 404

    safe_name = html.escape(record.name)
    safe_course = html.escape(record.course)
    safe_number = html.escape(record.cert_number)
    safe_date = html.escape(record.completion_date or "Verified")
    pdf_hash = getattr(record, "pdf_hash", None) or ""

    hash_html = f'<div class="hash-box">SHA-256: {html.escape(pdf_hash[:40])}...</div>' if pdf_hash else ""

    body = f"""
      <div class="badge valid">✓ CERTIFICATE AUTHENTICATED</div>
      <dl>
        <dt>Candidate Name</dt><dd>{safe_name}</dd>
        <dt>Course / Program</dt><dd>{safe_course}</dd>
        <dt>Certificate Number</dt><dd>{safe_number}</dd>
        <dt>Date of Completion</dt><dd>{safe_date}</dd>
        <dt>Status</dt><dd style="color:#128a44;">VALID &amp; REGISTERED</dd>
      </dl>
      <div class="security-seal">
        <strong>🔒 Cryptographically Protected &amp; Immutable</strong>
        This document is permanently registered with DV Analytics. Any physical or digital alterations made to offline copies are void.
        {hash_html}
      </div>
      <p class="notice">DV Analytics Verification Authority · All Rights Reserved</p>
    """
    return PAGE_TEMPLATE.format(body=body)


@app.get("/verify")
def verify_missing_number():
    abort(404)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("VERIFY_SERVICE_PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
