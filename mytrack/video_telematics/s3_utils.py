"""Shared S3 client factory for video_telematics."""

from __future__ import annotations

from django.conf import settings


def get_s3_client():
    import boto3

    kwargs = {"region_name": getattr(settings, "VIDEO_S3_REGION", None) or "us-east-1"}
    endpoint = getattr(settings, "VIDEO_S3_ENDPOINT_URL", "") or None
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    access = getattr(settings, "VIDEO_S3_ACCESS_KEY_ID", "") or None
    secret = getattr(settings, "VIDEO_S3_SECRET_ACCESS_KEY", "") or None
    if access and secret:
        kwargs["aws_access_key_id"] = access
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("s3", **kwargs)
