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
<title>Certificate Verification</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f4f6fb;
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .card {{ background:#fff; border-radius:12px; box-shadow:0 4px 24px rgba(0,0,0,0.08);
           padding:2.5rem; max-width:420px; width:90%; text-align:center; }}
  .badge {{ font-size:1.1rem; font-weight:700; border-radius:8px; padding:0.6rem 1rem; display:inline-block; margin-bottom:1.2rem; }}
  .valid {{ background:#e6f7ec; color:#1a7f3c; }}
  .invalid {{ background:#fdeaea; color:#b3261e; }}
  dl {{ text-align:left; margin:0; }}
  dt {{ font-size:0.8rem; color:#666; margin-top:0.8rem; text-transform:uppercase; letter-spacing:0.03em; }}
  dd {{ font-size:1.05rem; margin:0.15rem 0 0 0; font-weight:600; color:#222; }}
</style>
</head>
<body>
  <div class="card">
    {body}
  </div>
</body>
</html>"""


@app.get("/verify/<certificate_number>")
def verify(certificate_number: str):
    record = cert_store.get_by_cert_number(certificate_number)
    if record is None or record.status != "VALID":
        body = (
            '<div class="badge invalid">&#10007; CERTIFICATE NOT FOUND</div>'
            "<p>This certificate number could not be verified. If you believe this is "
            "an error, please contact DV Analytics.</p>"
        )
        html_out = PAGE_TEMPLATE.format(body=body)
        return html_out, 404

    safe_name = html.escape(record.name)
    safe_course = html.escape(record.course)
    safe_number = html.escape(record.cert_number)
    body = f"""
      <div class="badge valid">&#10003; CERTIFICATE VERIFIED</div>
      <dl>
        <dt>Name</dt><dd>{safe_name}</dd>
        <dt>Course</dt><dd>{safe_course}</dd>
        <dt>Certificate Number</dt><dd>{safe_number}</dd>
        <dt>Status</dt><dd>VALID</dd>
      </dl>
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
