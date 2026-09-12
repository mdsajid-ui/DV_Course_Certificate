import os
import re
import smtplib
import ssl
from email.message import EmailMessage

from utils import get_secret

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def is_valid_email(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


class SMTPConfig:
    """Loads SMTP credentials/settings from session state, Streamlit secrets, or environment variables."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None,
        sender_name: str = None,
    ):
        sess_smtp = {}
        try:
            import streamlit as st
            if hasattr(st, "session_state"):
                sess_smtp = st.session_state.get("smtp_overrides", {})
        except Exception:
            sess_smtp = {}

        self.host = host or sess_smtp.get("host") or get_secret("SMTP_HOST", "smtp.gmail.com")
        raw_port = port or sess_smtp.get("port") or get_secret("SMTP_PORT", "587")
        try:
            self.port = int(raw_port)
        except (ValueError, TypeError):
            self.port = 587

        self.username = (username or sess_smtp.get("username") or get_secret("SMTP_EMAIL", "")).strip()
        self.password = (password or sess_smtp.get("password") or get_secret("SMTP_PASSWORD", "")).strip()
        self.sender_name = sender_name or sess_smtp.get("sender_name") or get_secret("SMTP_SENDER_NAME", "DV Analytics Team")

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
                "SMTP credentials are not configured. Please provide Sender Email and App Password in Tab ③."
            )

        context = ssl.create_default_context()
        # Support port 465 (Direct SSL) and port 587/25 (STARTTLS)
        if self.config.port == 465:
            self._server = smtplib.SMTP_SSL(self.config.host, self.config.port, context=context, timeout=30)
        else:
            self._server = smtplib.SMTP(self.config.host, self.config.port, timeout=30)
            self._server.ehlo()
            self._server.starttls(context=context)
            self._server.ehlo()

        # Clean spaces from app passwords (e.g. Google's 4-char spaced blocks)
        cleaned_password = self.config.password.replace(" ", "").strip()
        self._server.login(self.config.username.strip(), cleaned_password)
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
        msg["From"] = f"{self.config.sender_name} <{self.config.username.strip()}>"
        msg["To"] = to_email.strip()
        msg.set_content(body)

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                data = f.read()
            filename = os.path.basename(attachment_path)
            msg.add_attachment(
                data, maintype="application", subtype="pdf", filename=filename
            )

        if self._server is None:
            # Open and close single-use connection safely
            with self:
                self._server.send_message(msg)
        else:
            self._server.send_message(msg)

