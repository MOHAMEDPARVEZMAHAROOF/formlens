"""Optional AWS S3 integration for FormLens.

Design: annotated result images are uploaded to S3 when the deployment
provides AWS credentials and FORMLENS_S3_BUCKET is set. The function never
raises and never prints credential values; it reports a machine-readable
reason when the cloud path is unavailable.

Honesty note: this build has no AWS account access, so the S3 path is
documented as designed-but-not-deployed. The app runs fully without it.
"""
from __future__ import annotations

import os


def upload_png(png_bytes: bytes, key: str) -> dict:
    """Best-effort S3 upload of an annotated PNG. Returns a status dict."""
    bucket = os.environ.get("FORMLENS_S3_BUCKET", "").strip()
    if not bucket:
        return {"ok": False, "reason": "FORMLENS_S3_BUCKET not set",
                "mode": "local-only"}
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
    except ImportError:
        return {"ok": False, "reason": "boto3 not installed",
                "mode": "local-only"}
    try:
        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=png_bytes,
                      ContentType="image/png")
        region = s3.meta.region_name or "us-east-1"
        url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        return {"ok": True, "reason": "uploaded", "mode": "s3",
                "bucket": bucket, "key": key, "url": url}
    except Exception as e:  # NoCredentialsError, ClientError, endpoint errors
        return {"ok": False, "mode": "local-only",
                "reason": f"{type(e).__name__}: {str(e)[:160]}"}


def status() -> dict:
    bucket = os.environ.get("FORMLENS_S3_BUCKET", "").strip()
    try:
        import boto3  # noqa: F401
        lib = True
    except ImportError:
        lib = False
    return {"configured": bool(bucket) and lib,
            "bucket": bucket or None,
            "boto3": lib,
            "mode": "s3" if (bucket and lib) else "local-only"}
