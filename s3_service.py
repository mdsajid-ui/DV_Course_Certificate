"""
s3_service.py
=============
Enterprise-grade cloud object storage service for student certificates.
Supports standard Amazon S3 and S3-compatible providers (UpCloud, MinIO, Ceph).

Security Architecture:
1. Certificates are uploaded with private access permissions.
2. Direct public access to the S3 bucket is blocked.
3. Access is granted only via temporary, cryptographically-signed S3 Presigned URLs
   with configurable time-to-live (e.g. 1 hour).
4. Student authorization is enforced via HMAC-SHA256 access tokens and credential checks,
   strictly preventing student A from accessing student B's certificate.
5. AWS/S3 credentials are kept strictly in environment variables and never logged or exposed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

from utils import get_secret

logger = logging.getLogger("s3_certificate_storage")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [S3] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class S3StorageError(RuntimeError):
    """Base exception for S3 storage operations."""
    pass


class S3UploadError(S3StorageError):
    """Raised when uploading a certificate PDF to S3 fails."""
    pass


class S3PresignedUrlError(S3StorageError):
    """Raised when presigned URL generation fails."""
    pass


class TokenValidationError(ValueError):
    """Raised when an HMAC student access token is invalid or expired."""
    pass


def _sanitize_path_segment(val: str, default: str = "general") -> str:
    """Sanitizes user/course/student strings for safe S3 key paths."""
    if not val:
        return default
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(val).strip())
    return cleaned or default


class S3CertificateStorage:
    """Manages S3 object storage operations and presigned URL delivery."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        expiry_seconds: Optional[int] = None,
        signing_secret: Optional[str] = None,
    ):
        self.endpoint_url = (endpoint_url or get_secret("AWS_S3_ENDPOINT_URL", "")).strip() or None
        self.access_key = (access_key or get_secret("AWS_ACCESS_KEY_ID", "")).strip()
        self.secret_key = (secret_key or get_secret("AWS_SECRET_ACCESS_KEY", "")).strip()
        self.bucket = (bucket or get_secret("AWS_S3_BUCKET", "b1storage")).strip()
        self.region = (region or get_secret("AWS_REGION", "us-east-1")).strip()
        
        raw_expiry = expiry_seconds or get_secret("S3_PRESIGNED_EXPIRY_SECONDS", "3600")
        try:
            self.expiry_seconds = int(raw_expiry)
        except (ValueError, TypeError):
            self.expiry_seconds = 3600

        self.signing_secret = (
            signing_secret
            or get_secret("APP_SECRET_KEY", "")
            or "dv_analytics_immutable_token_signing_secret_key_2026"
        ).strip().encode("utf-8")

        self._client = None

    def is_configured(self) -> bool:
        """Returns True if minimum S3 credentials and bucket are defined."""
        return bool(self.access_key and self.secret_key and self.bucket)

    def get_client(self):
        """Initializes and returns a thread-safe Boto3 S3 client."""
        if self._client is not None:
            return self._client

        if not self.is_configured():
            raise S3StorageError(
                "S3 Storage is not configured. Please define AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, and AWS_S3_BUCKET in .env."
            )

        client_kwargs: Dict[str, Any] = {
            "service_name": "s3",
            "aws_access_key_id": self.access_key,
            "aws_secret_access_key": self.secret_key,
            "region_name": self.region,
            "config": Config(
                signature_version="s3v4",
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=30,
            ),
        }
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        session = boto3.session.Session()
        self._client = session.client(**client_kwargs)
        return self._client

    def build_object_key(
        self,
        year: str,
        student_id: str,
        filename: str = "certificate.pdf",
    ) -> str:
        """
        Organizes certificates in S3 using the exact required structure:
            certificates/{year}/{student_id}/certificate.pdf
        """
        safe_year = _sanitize_path_segment(year, "2026")
        safe_student = _sanitize_path_segment(student_id, "unknown")
        
        # Ensure clean filename with .pdf extension
        raw_name = str(filename).strip()
        if raw_name.lower().endswith(".pdf"):
            base_part = raw_name[:-4]
        else:
            base_part = raw_name
        safe_base = _sanitize_path_segment(base_part, "certificate")
        return f"certificates/{safe_year}/{safe_student}/{safe_base}.pdf"

    def upload_certificate_pdf(
        self,
        local_pdf_path: str,
        year: str,
        student_id: str,
        filename: str = "certificate.pdf",
        custom_key: Optional[str] = None,
    ) -> str:
        """
        Uploads a generated certificate PDF to S3 under private access.
        Returns the resulting S3 object key.
        """
        if not os.path.exists(local_pdf_path):
            raise FileNotFoundError(f"Local certificate PDF not found: {local_pdf_path}")

        s3_key = custom_key or self.build_object_key(year, student_id, filename)
        client = self.get_client()

        logger.info(
            "Uploading certificate PDF to S3 [bucket=%s, key=%s, local_size=%d bytes]",
            self.bucket,
            s3_key,
            os.path.getsize(local_pdf_path),
        )

        try:
            with open(local_pdf_path, "rb") as f:
                pdf_bytes = f.read()

            client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=pdf_bytes,
                ContentType="application/pdf",
                ACL="private",
            )
            logger.info("Successfully uploaded certificate to S3: %s", s3_key)
            return s3_key
        except (ClientError, BotoCoreError, Exception) as e:
            logger.error("Failed to upload certificate to S3 [key=%s]: %s", s3_key, e, exc_info=True)
            raise S3UploadError(f"S3 certificate upload failed: {e}") from e

    def generate_presigned_download_url(
        self,
        s3_key: str,
        expires_in: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> str:
        """
        Generates a secure, temporary presigned GET URL for student download.
        Expires after configurable period (default: 3600 seconds / 1 hour).
        """
        if not s3_key:
            raise ValueError("s3_key must not be empty.")

        client = self.get_client()
        expiry = expires_in or self.expiry_seconds

        params: Dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": s3_key,
            "ResponseContentType": "application/pdf",
        }

        # Format Content-Disposition so browser prompts a clean download with filename
        if filename:
            clean_name = os.path.basename(filename)
            if not clean_name.endswith(".pdf"):
                clean_name = f"{clean_name}.pdf"
            params["ResponseContentDisposition"] = f'attachment; filename="{clean_name}"'
        else:
            params["ResponseContentDisposition"] = "attachment; filename=\"certificate.pdf\""

        try:
            url = client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expiry,
            )
            logger.info("Generated presigned download URL [key=%s, expiry=%ds]", s3_key, expiry)
            return url
        except Exception as e:
            logger.error("Failed to generate presigned download URL [key=%s]: %s", s3_key, e)
            raise S3PresignedUrlError(f"Presigned URL generation failed: {e}") from e

    # -----------------------------------------------------------------------
    # Cryptographic Student Access Tokens (HMAC-SHA256)
    # -----------------------------------------------------------------------
    def generate_student_access_token(
        self,
        cert_number: str,
        student_id: str,
        email: str,
        expires_in: int = 86400,  # 24 hours valid by default
    ) -> str:
        """
        Generates a cryptographically-signed access token for a student.
        Prevents student tampering and cross-student certificate scraping.
        """
        now = int(time.time())
        payload = {
            "cert_number": str(cert_number).strip(),
            "student_id": str(student_id).strip(),
            "email": str(email).strip().lower(),
            "iat": now,
            "exp": now + expires_in,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")

        sig = hmac.new(self.signing_secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{payload_b64}.{sig}"

    def verify_student_access_token(self, token: str) -> Dict[str, Any]:
        """
        Verifies the HMAC signature and expiration of a student access token.
        Raises TokenValidationError on invalid signature or expiration.
        """
        if not token or "." not in token:
            raise TokenValidationError("Malformed or missing access token.")

        payload_b64, signature = token.rsplit(".", 1)

        expected_sig = hmac.new(
            self.signing_secret, payload_b64.encode("ascii"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            logger.warning("Token verification failed: HMAC signature mismatch.")
            raise TokenValidationError("Invalid access token signature.")

        # Decode payload
        rem = len(payload_b64) % 4
        padded_b64 = payload_b64 + ("=" * ((4 - rem) % 4))
        try:
            payload_json = base64.urlsafe_b64decode(padded_b64.encode("ascii")).decode("utf-8")
            payload = json.loads(payload_json)
        except Exception as e:
            raise TokenValidationError(f"Could not parse token payload: {e}")

        now = int(time.time())
        exp = payload.get("exp", 0)
        if now > exp:
            logger.info("Token expired for cert_number=%s", payload.get("cert_number"))
            raise TokenValidationError("Access token has expired. Please request a new download link.")

        return payload


# Global singleton instance
_default_storage: Optional[S3CertificateStorage] = None


def get_s3_storage() -> S3CertificateStorage:
    global _default_storage
    if _default_storage is None:
        _default_storage = S3CertificateStorage()
    return _default_storage


def build_object_key(
    year: Any,
    student_id: str,
    filename: str = "certificate.pdf",
) -> str:
    """Convenience wrapper for building standard S3 object key."""
    return get_s3_storage().build_object_key(
        year=str(year) if year is not None else "2026",
        student_id=str(student_id) if student_id is not None else "unknown",
        filename=filename,
    )


def upload_certificate_pdf(
    local_pdf_path: str,
    year: str,
    student_id: str,
    filename: str = "certificate.pdf",
    custom_key: Optional[str] = None,
) -> str:
    """Convenience wrapper for S3 upload."""
    return get_s3_storage().upload_certificate_pdf(
        local_pdf_path=local_pdf_path,
        year=year,
        student_id=student_id,
        filename=filename,
        custom_key=custom_key,
    )


def generate_presigned_download_url(
    s3_key: str,
    expires_in: Optional[int] = None,
    filename: Optional[str] = None,
) -> str:
    """Convenience wrapper for generating a presigned download URL."""
    return get_s3_storage().generate_presigned_download_url(
        s3_key=s3_key,
        expires_in=expires_in,
        filename=filename,
    )


def generate_student_access_token(
    cert_number: str,
    student_id: str,
    email: str,
    expires_in: int = 86400,
) -> str:
    """Convenience wrapper for generating an HMAC student access token."""
    return get_s3_storage().generate_student_access_token(
        cert_number=cert_number,
        student_id=student_id,
        email=email,
        expires_in=expires_in,
    )


def verify_student_access_token(token: str) -> Dict[str, Any]:
    """Convenience wrapper for validating an HMAC student access token."""
    return get_s3_storage().verify_student_access_token(token)
