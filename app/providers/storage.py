from __future__ import annotations

import asyncio
import hashlib
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.client import Config

from app.core.config import Settings


class StoredObject:
    def __init__(self, key: str, mime_type: str, size_bytes: int, checksum_sha256: str):
        self.key = key
        self.mime_type = mime_type
        self.size_bytes = size_bytes
        self.checksum_sha256 = checksum_sha256


class ObjectStorage(ABC):
    @abstractmethod
    async def put_bytes(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    async def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        raise NotImplementedError

    async def put_text(
        self, key: str, text: str, mime_type: str = "text/plain; charset=utf-8"
    ) -> StoredObject:
        return await self.put_bytes(key, text.encode("utf-8"), mime_type)

    async def get_text(self, key: str) -> str:
        return (await self.get_bytes(key)).decode("utf-8")

    async def delete_prefix(self, prefix: str) -> None:
        return None


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        clean_key = key.lstrip("/").replace("..", "_")
        return self.root / clean_key

    async def put_bytes(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()
        return StoredObject(
            key=key, mime_type=mime_type, size_bytes=len(data), checksum_sha256=checksum
        )

    async def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return str(self._path(key).resolve())

    async def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


class TemporaryObjectStorage(LocalObjectStorage):
    """Disk-backed ephemeral storage; cleanup is explicit after successful upload."""


class R2ObjectStorage(ObjectStorage):
    def __init__(self, settings: Settings):
        settings.validate_storage()
        self.bucket_name = settings.r2_bucket_name or ""
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    async def put_bytes(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket_name,
            Key=key,
            Body=data,
            ContentType=mime_type,
        )
        checksum = hashlib.sha256(data).hexdigest()
        return StoredObject(
            key=key, mime_type=mime_type, size_bytes=len(data), checksum_sha256=checksum
        )

    async def get_bytes(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket_name, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )


def public_object_url(settings: Settings, key: str) -> str | None:
    base = settings.r2_public_base_url
    if not base:
        return None

    parsed = urlparse(base if "://" in base else f"https://{base}")
    if parsed.hostname and parsed.hostname.endswith(".r2.cloudflarestorage.com"):
        return None

    return f"{base.rstrip('/')}/{key}"


def create_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "r2":
        return R2ObjectStorage(settings)
    if settings.storage_backend == "temporary":
        return TemporaryObjectStorage(settings.temporary_storage_path)
    return LocalObjectStorage(settings.local_storage_path)
