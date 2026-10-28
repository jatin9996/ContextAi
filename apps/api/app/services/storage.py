import asyncio
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def destination(self, key: str) -> Path:
        if not key or key.startswith(("/", "\\")) or ".." in Path(key).parts:
            raise AppError("invalid_storage_key", "Invalid storage path.", 400)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise AppError("invalid_storage_key", "Invalid storage path.", 400)
        return path

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self.destination(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        def write() -> None:
            path.write_bytes(data)

        await asyncio.to_thread(write)
        del content_type

    async def load(self, key: str) -> bytes:
        path = self.destination(key)
        if not path.is_file():
            raise AppError("missing_file", "The stored file could not be found.", 404)

        def read() -> bytes:
            return path.read_bytes()

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        path = self.destination(key)

        def remove() -> None:
            if path.is_file():
                path.unlink()

        await asyncio.to_thread(remove)


class S3Storage:
    def __init__(self) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def _guard(self, key: str) -> str:
        if not key or ".." in key or key.startswith("/"):
            raise AppError("invalid_storage_key", "Invalid storage path.", 400)
        return key

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        safe = self._guard(key)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=safe,
            Body=data,
            ContentType=content_type,
        )

    async def load(self, key: str) -> bytes:
        safe = self._guard(key)

        def read() -> bytes:
            response = self.client.get_object(Bucket=self.bucket, Key=safe)
            return response["Body"].read()

        try:
            return await asyncio.to_thread(read)
        except Exception as exc:
            name = type(exc).__name__
            if "NoSuchKey" in name or "404" in str(exc):
                raise AppError("missing_file", "The stored file could not be found.", 404) from exc
            raise AppError("storage_error", "Object storage could not be read.", 502) from exc

    async def delete(self, key: str) -> None:
        safe = self._guard(key)
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=safe)


_storage: LocalStorage | S3Storage | None = None


def get_storage() -> LocalStorage | S3Storage:
    global _storage
    if _storage is None:
        if settings.storage_backend == "s3":
            _storage = S3Storage()
        else:
            _storage = LocalStorage(settings.resolved_storage_path)
    return _storage
