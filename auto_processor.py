"""
auto_processor.py
==================
The "automatic" pipeline requested on top of Tab (5): instead of an admin
clicking "Send Certificate" per student, this polls the live Google Sheet on
a schedule and, for every row that looks like a new/unprocessed student
(name + email present, no certificate sent yet), does the full chain by
itself:

    read sheet -> get/issue certificate number -> render PPTX -> embed QR
    -> convert to PDF -> email it -> record SENT/FAILED in certificates.db

It is intentionally *polling*, not a live push trigger — Google Sheets has
no built-in webhook for "a cell changed", so the two real options are (a)
poll on an interval (this script; zero extra moving parts, works with the
read-only API-key setup you already have) or (b) add a small Apps Script
`onEdit` trigger inside the Sheet that calls a webhook the moment a row is
added (near-instant, but means writing and pasting a script into the Sheet
itself, plus a webhook endpoint to receive it). Ask if you want (b) added —
it's a ~30 line Apps Script snippet plus one new Flask route in
verify_service. This script covers (a), which is simpler to run and safe to
leave running unattended.

Safe to run over and over:
  * Every attempt is idempotent — a student who already has a cert number
    keeps that exact number; a student who's already SENT is skipped, not
    re-emailed, every subsequent poll.
  * A student whose last attempt FAILED (bad email, SMTP hiccup, etc.) is
    automatically retried on the next poll — no manual "resend" needed
    unless the row itself is broken (see skipped_rows below).
  * Rows the script can't even attempt — no email address, or a certificate
    number that's already assigned to a *different* student's email in the
    sheet — are logged to cert_store.skipped_rows (visible on the
    dashboard) instead of crashing the whole batch.

Run modes
---------
    python auto_processor.py --once     # single pass, e.g. from cron
    python auto_processor.py --watch    # loop forever, polling every
                                         # AUTO_POLL_SECONDS (default 300)

Required environment variables (see .env.example for the rest already used
by the app — SMTP_*, CERTIFICATE_VERIFICATION_BASE_URL, etc.):

    AUTO_SPREADSHEET_URL       the Google Sheet URL or ID to watch
    AUTO_COURSE_CODE           e.g. APIDS  (sheet has no Course column, so
    AUTO_COURSE_NAME           e.g. "Advanced Program in Industrial Data     one course is watched per instance of this
                                Science (APIDS)"                             script — run a second instance with a
                                                                              different .env for a second course)
    CERT_INSTITUTE_CODE        e.g. DVA
    CERT_YEAR                  e.g. 2026
    AUTO_POLL_SECONDS          optional, default 300 (5 minutes)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from datetime import date

import cert_store
import qr_utils
import pptx_certificate
import sheets_readonly
from email_sender import EmailSender, SMTPConfig, is_valid_email
from utils import get_secret

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("auto_processor")

DEFAULT_SUBJECT = "Your {{course_name}} Certificate from DV Analytics"
DEFAULT_BODY = (
    "Dear {{student_name}},\n\n"
    "Congratulations on completing {{course_name}}! Your certificate is attached.\n\n"
    "Certificate No: {{certificate_number}}\n"
    "You can verify it any time by scanning the QR code on the certificate.\n\n"
    "Best regards,\nDV Analytics Team"
)


def _apply_placeholders(template_text: str, *, student_name, course_name, certificate_number) -> str:
    return (
        template_text.replace("{{student_name}}", student_name)
        .replace("{{course_name}}", course_name)
        .replace("{{certificate_number}}", certificate_number)
    )


def process_once() -> dict:
    """Runs a single poll-and-process pass. Returns a summary dict for logging/tests."""
    spreadsheet = get_secret("AUTO_SPREADSHEET_URL")
    course_code = get_secret("AUTO_COURSE_CODE")
    course_name = get_secret("AUTO_COURSE_NAME", course_code)
    institute_code = get_secret("CERT_INSTITUTE_CODE", "DVA")
    year = get_secret("CERT_YEAR", str(date.today().year))
    template_path = get_secret(
        "CERTIFICATE_TEMPLATE_PPTX",
        os.path.join(os.path.dirname(__file__), "assets", "templates", f"certificate_{course_code}_blank.pptx"),
    )

    if not spreadsheet or not course_code:
        raise RuntimeError("AUTO_SPREADSHEET_URL and AUTO_COURSE_CODE must be set (see auto_processor.py docstring).")

    summary = {"seen": 0, "sent": 0, "failed": 0, "skipped": 0, "already_sent": 0}

    try:
        roster = sheets_readonly.get_roster(spreadsheet)
    except sheets_readonly.SheetAccessError as exc:
        log.error("Could not read the sheet this poll: %s", exc)
        summary["sheet_error"] = str(exc)
        return summary

    smtp_config = SMTPConfig()
    sender = EmailSender(smtp_config)
    smtp_open = False

    for row in roster:
        summary["seen"] += 1
        name = (row.name or "").strip()
        email = (row.email or "").strip()

        if not name:
            continue  # blank row

        if not email or not is_valid_email(email):
            cert_store.record_skip(row.row_number, name, email, "Missing or invalid email address")
            summary["skipped"] += 1
            continue

        completion_date = row.completion_date or date.today().strftime("%d-%m-%Y")

        try:
            record = cert_store.issue_or_get_certificate_number(
                name=name,
                email=email,
                course=course_code,
                completion_date=completion_date,
                institute_code=institute_code,
                course_code=course_code,
                year=year,
                existing_number=row.existing_certificate_number,
            )
        except Exception as exc:  # e.g. sqlite3.IntegrityError: cert number already used by someone else
            reason = (
                f"Certificate number '{row.existing_certificate_number}' in the sheet is already "
                f"assigned to a different student — fix this row in the sheet."
                if row.existing_certificate_number
                else f"Could not issue a certificate number: {exc}"
            )
            cert_store.record_skip(row.row_number, name, email, reason)
            summary["skipped"] += 1
            log.warning("Row %s (%s) skipped: %s", row.row_number, name, reason)
            continue

        if record.email_status == "SENT":
            summary["already_sent"] += 1
            cert_store.clear_skip(row.row_number)
            continue  # nothing to do — this student is fully processed

        # (Re)attempt generation + send — covers brand-new students and
        # anyone whose last attempt FAILED.
        try:
            if not smtp_open:
                sender.connect()
                smtp_open = True

            qr_url = qr_utils.verification_url(record.cert_number)
            qr_bytes = qr_utils.make_qr_image_bytes(qr_url)

            with tempfile.TemporaryDirectory() as tmpdir:
                qr_path = os.path.join(tmpdir, "qr.png")
                with open(qr_path, "wb") as f:
                    f.write(qr_bytes)

                pdf_path = os.path.join(tmpdir, f"{record.cert_number}.pdf")
                pptx_certificate.render_certificate_pdf(
                    name=record.name,
                    certificate_number=record.cert_number,
                    completion_date=completion_date,
                    qr_png_path=qr_path,
                    template_path=template_path,
                    output_pdf_path=pdf_path,
                )

                subject = _apply_placeholders(
                    DEFAULT_SUBJECT, student_name=record.name, course_name=course_name,
                    certificate_number=record.cert_number,
                )
                body = _apply_placeholders(
                    DEFAULT_BODY, student_name=record.name, course_name=course_name,
                    certificate_number=record.cert_number,
                )
                sender.send(email, subject, body, attachment_path=pdf_path)

            cert_store.mark_sent(record.cert_number)
            cert_store.clear_skip(row.row_number)
            summary["sent"] += 1
            log.info("Sent certificate %s to %s <%s>", record.cert_number, record.name, email)

        except Exception as exc:
            cert_store.mark_send_failed(record.cert_number, str(exc))
            summary["failed"] += 1
            log.error("Failed to send certificate %s to %s: %s", record.cert_number, email, exc)
            # A dead SMTP connection shouldn't take down the rest of the batch.
            try:
                sender.close()
            except Exception:
                pass
            smtp_open = False

    if smtp_open:
        sender.close()

    log.info(
        "Poll complete — seen=%s sent=%s already_sent=%s failed=%s skipped=%s",
        summary["seen"], summary["sent"], summary["already_sent"], summary["failed"], summary["skipped"],
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Run a single pass and exit (use with cron/Task Scheduler).")
    group.add_argument("--watch", action="store_true", help="Loop forever, polling every AUTO_POLL_SECONDS.")
    args = parser.parse_args()

    if args.once:
        process_once()
        return

    interval = int(get_secret("AUTO_POLL_SECONDS", "300"))
    log.info("Starting watch loop — polling every %ss. Ctrl+C to stop.", interval)
    while True:
        try:
            process_once()
        except Exception:
            log.exception("Unhandled error during poll — will retry next interval.")
        time.sleep(interval)


if __name__ == "__main__":
    main()
