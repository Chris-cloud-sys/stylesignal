"""S3-compatible object storage (production).

Server-side encryption is on by default — §8 requires encryption at rest for
outfit images.
"""
from typing import Optional

from ..config import get_settings
from . import ObjectStorage


class S3Storage(ObjectStorage):
    def __init__(self) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "STYLESIGNAL_STORAGE_BACKEND=s3 requires boto3 "
                "(pip install boto3)"
            ) from exc

        from botocore.config import Config

        settings = get_settings()
        if not settings.s3_bucket:
            raise RuntimeError("STYLESIGNAL_S3_BUCKET must be set for the s3 backend")

        self.bucket = settings.s3_bucket
        self.sse = settings.s3_sse
        self.default_ttl = settings.signed_url_ttl_seconds
        # Explicit timeouts/retries — botocore's own defaults (60s connect,
        # 60s read, up to 5 retries) can silently turn one transient R2
        # hiccup into minutes of hidden retrying with no exception raised.
        # See the comment on the settings above for why this matters.
        self.client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            config=Config(
                connect_timeout=settings.s3_connect_timeout_seconds,
                read_timeout=settings.s3_read_timeout_seconds,
                retries={"max_attempts": settings.s3_max_attempts, "mode": "standard"},
            ),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra = {}
        if self.sse:
            extra["ServerSideEncryption"] = self.sse
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            **extra
        )

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(key) from exc
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return False
        return True

    def delete_prefix(self, prefix: str) -> int:
        paginator = self.client.get_paginator("list_objects_v2")
        removed = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents") or []
            if not contents:
                continue
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": item["Key"]} for item in contents]},
            )
            removed += len(contents)
        return removed

    def signed_url(self, key: str, ttl_seconds: Optional[int] = None) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_seconds or self.default_ttl,
        )
