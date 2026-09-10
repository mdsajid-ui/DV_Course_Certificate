"""
email_sender.py
----------------
Handles SMTP email delivery with certificate attachments.
Credentials are read from environment variables only — never hardcoded.
"""

import os
import re
import smtplib
import ssl
from email.message import EmailMessage

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


class SMTPConfig:
    """Loads SMTP credentials/settings from Streamlit secrets or environment variables."""

    def __init__(self):
        try:
            import streamlit as st
            sec = st.secrets
        except Exception:
            sec = {}

        self.host = sec.get("SMTP_HOST", os.environ.get("SMTP_HOST", "smtp.gmail.com"))
        self.port = int(sec.get("SMTP_PORT", os.environ.get("SMTP_PORT", "587")))
        self.username = sec.get("SMTP_EMAIL", os.environ.get("SMTP_EMAIL", ""))
        self.password = sec.get("SMTP_PASSWORD", os.environ.get("SMTP_PASSWORD", ""))
        self.sender_name = sec.get("SMTP_SENDER_NAME", os.environ.get("SMTP_SENDER_NAME", "DV Analytics Team"))

    def is_configured(self) -> bool:
        return bool(self.username and self.password)


class EmailSender:
    def __init__(self, config: SMTPConfig = None):
        self.config = config or SMTPConfig()
        self._server = None

    def connect(self):
        """Open a single SMTP connection to reuse across a batch send."""
        if not self.config.is_configured():
            raise RuntimeError(
                "SMTP credentials are not configured. Set SMTP_EMAIL and "
                "SMTP_PASSWORD as environment variables (see .env.example)."
            )
        context = ssl.create_default_context()
        self._server = smtplib.SMTP(self.config.host, self.config.port, timeout=30)
        self._server.starttls(context=context)
        self._server.login(self.config.username, self.config.password)
        return self

    def close(self):
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def send(self, to_email: str, subject: str, body: str, attachment_path: str = None):
        """Send a single email with an optional file attachment. Raises on failure."""
        if not is_valid_email(to_email):
            raise ValueError(f"Invalid email address: {to_email}")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{self.config.sender_name} <{self.config.username}>"
        msg["To"] = to_email
        msg.set_content(body)

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                data = f.read()
            filename = os.path.basename(attachment_path)
            msg.add_attachment(
                data, maintype="application", subtype="pdf", filename=filename
            )

        if self._server is None:
            # Fallback: open a fresh connection for a one-off send
            with self.connect():
                self._server.send_message(msg)
                self.close()
        else:
            self._server.send_message(msg)
