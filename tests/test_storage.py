from types import SimpleNamespace

import pytest

from app.providers.storage import R2ObjectStorage, public_object_url


class _R2Client:
    def __init__(self) -> None:
        self.call: dict | None = None

    def generate_presigned_url(
        self,
        operation: str,
        Params: dict[str, str],
        ExpiresIn: int,
    ) -> str:
        self.call = {"operation": operation, "params": Params, "expires_in": ExpiresIn}
        return "https://signed.example/audio.mp3?token=abc"


@pytest.mark.asyncio
async def test_r2_presigned_get_url_uses_signed_url_even_with_public_base() -> None:
    client = _R2Client()
    storage = R2ObjectStorage.__new__(R2ObjectStorage)
    storage.bucket_name = "podcasts"
    storage.client = client

    url = await storage.presigned_get_url("jobs/job-1/audio/final.mp3", expires_in=123)

    assert url == "https://signed.example/audio.mp3?token=abc"
    assert client.call == {
        "operation": "get_object",
        "params": {"Bucket": "podcasts", "Key": "jobs/job-1/audio/final.mp3"},
        "expires_in": 123,
    }


def test_public_object_url_ignores_private_r2_api_endpoint() -> None:
    settings = SimpleNamespace(
        r2_public_base_url="https://account-id.r2.cloudflarestorage.com"
    )

    assert public_object_url(settings, "jobs/job-1/thumbnail/cover.png") is None


def test_public_object_url_allows_real_public_base() -> None:
    settings = SimpleNamespace(r2_public_base_url="https://media.example.com")

    assert (
        public_object_url(settings, "jobs/job-1/thumbnail/cover.png")
        == "https://media.example.com/jobs/job-1/thumbnail/cover.png"
    )
