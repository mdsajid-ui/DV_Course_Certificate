# Automated Certificate Generation and Email Sending System

A Streamlit app that turns an Excel participant list + a certificate template
into personalized PDF certificates, then emails each one out automatically —
with a live progress bar, dashboard, and downloadable reports.

## Features

- Upload an `.xlsx` file with **Name**, **Mobile Number**, **Email ID** columns (flexible column matching, order-independent)
- Upload a PNG/JPG/PDF certificate template; name is drawn centered on top (adjustable font size, position, color)
- One-click **Generate Certificates** → saved as `Name_Certificate.pdf` in `output/certificates/`
- One-click **Send Certificates** → personalized email per participant via SMTP, certificate attached, live progress bar + running Total/Sent/Failed/Pending counts
- Email address validation before sending
- Auto-generated `Email_Sending_Report.xlsx` and `Error_Report.xlsx` after each send
- `email_log.txt` — timestamped log of every send attempt
- Dashboard: total participants, certificates generated, emails sent, failed, success rate
- Download buttons for certificates (.zip), report, error report, and log file
- Credentials read only from environment variables — nothing hardcoded

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with your real SMTP credentials
```

**Gmail users:** enable 2-Step Verification, then create an
[App Password](https://myaccount.google.com/apppasswords) — use that as
`SMTP_PASSWORD`, not your normal Gmail password.

**Outlook/Office365 users:** set `SMTP_HOST=smtp.office365.com` in `.env`.

## Run

```bash
streamlit run app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).

## Usage flow

1. **① Upload** — upload your Excel list and certificate template; preview the sample certificate.
2. **② Generate Certificates** — click the button; review the generated list.
3. **③ Send Certificates** — write your subject/body (`{{Name}}` is replaced per participant), click Send, watch the progress bar.
4. **④ Report & Dashboard** — view KPIs and download the certificates zip, the Excel report, the error report, and the log file.

## File structure

```
app.py                    # Streamlit UI and orchestration
certificate_generator.py  # PIL-based certificate rendering + PDF export
email_sender.py           # SMTP wrapper, attachment handling, email validation
utils.py                  # Excel validation, logging, report building
requirements.txt
.env.example
```

## Notes

- Certificates and reports are written to `output/` (created automatically).
- For very large batches (thousands of records), sending happens sequentially
  in one connection to stay within SMTP rate limits — expect it to take a
  while; the progress bar and counters update live throughout.
- SQLite persistence (to resume a partially-completed batch) was left out of
  this version for simplicity, per the spec noting it as optional — the
  Excel report + log file already give you a full audit trail. Ask if you'd
  like resume/retry support added.
---

## ⑤ Sheet + QR Certificates (Google Sheet → PPTX template → QR → verify page)

This is a second, independent certificate pipeline added alongside the
original Excel-upload flow (Tabs ①–④), built specifically around your real
certificate design (`assets/templates/certificate_APIDS_blank.pptx`) and a
live Google Sheet roster. It reuses the existing SMTP sender (`email_sender.py`)
and login gate — nothing about Tabs ①–④ was changed.

### What it does

Select students pulled live from your Google Sheet → click **Send** →
certificate is generated from your *actual* PowerPoint template (not a
redrawn copy) with Name / Certificate Number / Date filled in → a QR code
pointing to `{CERTIFICATE_VERIFICATION_BASE_URL}/verify/{number}` is embedded
inside the PDF → email sent with the PDF attached → anyone who scans the QR
sees a public "CERTIFICATE VERIFIED" page with Name, Course, Certificate
Number, and Status — no email, phone, or other private data.

### Two important deviations from the original spec — read this first

**1. Google Sheets access is read-only (API key), by explicit choice.**
A service account or OAuth would allow writing certificate numbers back into
the sheet automatically. Since the ask was for API-key access instead, the
sheet can only be *read*, not written to. The consequence: **certificate
numbers are NOT stored in your Google Sheet.** They're stored locally in
`data/certificates.db` (SQLite), which is the actual source of truth for
"has this student already got a number, and what is it." That's what
guarantees the same number comes back on every regenerate/resend, and it's
what the `/verify/{number}` page reads from. Use the **"Export certificate
numbers"** button in Tab ⑤ to get a CSV you can paste back into your sheet
by hand if you want the numbers visible there too. Back up
`data/certificates.db` — if you switch this module to a service account or
OAuth later, `sheets_readonly.py` is the only file that needs to change.

Also: with an API key, the sheet **must** be shared as *"Anyone with the
link — Viewer."* Google does not authorize API keys against private sheets
under any setting — there's no way around this short of switching auth
methods.

**2. The verification page is a *separate* small Flask app, not a Streamlit
page.** Streamlit only supports its own page-slug routing with query
params (e.g. `/Verify?cert=X`); it cannot serve an exact path like
`/verify/DVA-APIDS-2026-000123`. Since the exact path was required, that
page lives in `verify_service/verify_app.py` — a ~100-line standalone Flask
app with one route, no auth, reading the same `certificates.db` file. Run
it as its own process next to Streamlit and put an nginx (or similar) reverse
proxy in front of both so they share one domain — see
`verify_service/nginx.example.conf`. `CERTIFICATE_VERIFICATION_BASE_URL`
should be set to that domain; changing environments only ever means
changing that one variable, never code.

### Certificate template

The template is edited as a real `.pptx` (not a flattened image) because
that's what your actual design turned out to be: one full-bleed background
picture (logos, signatures, ribbon, borders) plus a single text box holding
"This is to certify that `[ ]` ... Certificate Registration Number: `[ ]`
Date of Completion: `[ ]`". `pptx_certificate.py` finds and replaces only the
bracketed placeholder text — using a run-boundary-safe method, since testing
showed PowerPoint splits those brackets across a different number of text
runs depending on how the file was last edited — so the rest of the
paragraph's formatting is untouched, then shells out to LibreOffice
(`soffice --headless --convert-to pdf`) to render the final PDF, keeping the
result vector-crisp and pixel-identical to your design.

The QR sits in the one blank rectangle available in the current layout
(bottom-right, above the second signature) — found by scanning the
rasterized template for contiguous whitespace. At the size that area allows
(~0.8in), it's scannable but not generous; if you want a larger, more
reliably-scannable QR from further away, the master template's right
signature block would need to shift slightly to free up more space.
Position/size are tunable via `CERTIFICATE_QR_LEFT_IN` /
`CERTIFICATE_QR_TOP_IN` / `CERTIFICATE_QR_SIZE_IN` without touching code.

The bundled template only encodes the APIDS six-month program text. If you
issue certificates for other courses, add their `.pptx` file (same bracket
pattern) under `assets/templates/` and point `CERTIFICATE_TEMPLATE_PPTX` at
it per course, or ask to extend Tab ⑤ with a per-course template dropdown.

### Certificate number format

`INSTITUTE-COURSE-YEAR-######`, e.g. `DVA-APIDS-2026-000123` — sequence
resets per (institute code, course code, year) combination and is allocated
atomically, so concurrent sends can't collide or skip a number. This
**replaces** the numbering style already visible in the template's sample
text (`202505DVA2057`) per your instruction to switch to the spec's format;
new certificates will look different from any already issued under the old
scheme.

### Setup

```bash
pip install -r requirements.txt        # now includes qrcode, python-pptx, Flask, requests
sudo apt-get install -y libreoffice    # needed for pptx -> pdf conversion
cp .env.example .env
```

In `.env`, set at minimum:

```
GOOGLE_SHEETS_API_KEY=...              # from Google Cloud Console, Sheets API enabled
CERT_INSTITUTE_CODE=DVA
CERT_COURSE_CODE=APIDS
CERT_YEAR=2026
CERTIFICATE_VERIFICATION_BASE_URL=https://your-domain.example.com
```

Share your Google Sheet as "Anyone with the link — Viewer".

Run both processes:

```bash
streamlit run app.py                        # admin UI, Tab ⑤
python verify_service/verify_app.py         # public /verify/{number} page
```

Put both behind one reverse proxy per `verify_service/nginx.example.conf`
so `CERTIFICATE_VERIFICATION_BASE_URL` only needs to be one domain.

### Duplicate-send protection

The Send button tracks in-flight (email, course) pairs for the duration of
a batch, so a double-click can't fire the same send twice concurrently. Each
send always resolves to the *existing* certificate number for that student
(never a new one), so even a genuine resend later reuses the same PDF
content and the same verify link.

### Testing performed

Google Sheets and SMTP credentials weren't available in this environment, so
those two integration points are built defensively (clear errors on
403/404/missing columns; reuses the existing, already-working
`email_sender.py`) but not exercised against live services. Everything else
was tested directly — `pytest tests/` (15 tests):

- Certificate numbering: idempotent on resend, sequential per course/year,
  independent per course, send-count tracking.
- PPTX filling: all three fields land correctly, raises a clear error if the
  template doesn't match the expected pattern (rather than silently emitting
  a certificate with blank fields), full pptx → PDF render succeeds.
- Sheets roster reading: fuzzy column-header matching, incomplete rows
  skipped rather than failing the batch, 403/missing-column errors surfaced
  clearly, spreadsheet ID extraction from a full URL.
- Verification service: valid lookup returns Name/Course/Number/Status and
  never the student's email; unknown numbers return 404 with an
  "not found" page.

The rendered certificate was also visually inspected end-to-end (name, cert
number, and date filled correctly; QR present, decodes to the correct URL,
and doesn't overlap the signature or decorative border).

### File structure (additions)

```
cert_store.py                          # SQLite: certificate numbers, send status (source of truth)
sheets_readonly.py                     # Google Sheets roster reader (API key, read-only)
qr_utils.py                            # QR generation
pptx_certificate.py                    # Fills the real .pptx template, embeds QR, renders PDF
assets/templates/certificate_APIDS_blank.pptx
verify_service/
  verify_app.py                        # standalone Flask app: GET /verify/<certificate_number>
  nginx.example.conf
tests/
  test_cert_store.py
  test_pptx_certificate.py
  test_sheets_readonly.py
  test_verify_service.py
```

