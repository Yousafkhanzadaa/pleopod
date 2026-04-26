from types import SimpleNamespace

import pytest

from app.providers.gemini import GeminiAIProvider


class _Models:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_images(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            generated_images=[
                SimpleNamespace(
                    image=SimpleNamespace(image_bytes=b"image-bytes", mime_type="image/png")
                )
            ]
        )


@pytest.mark.asyncio
async def test_generate_image_uses_imagen_api_for_imagen_models() -> None:
    provider = GeminiAIProvider.__new__(GeminiAIProvider)
    models = _Models()
    provider.client = SimpleNamespace(models=models)

    image = await provider.generate_image("make a thumbnail", "imagen-4.0-fast-generate-001")

    assert image.data == b"image-bytes"
    assert image.mime_type == "image/png"
    assert image.prompt == "make a thumbnail"
    assert models.calls[0]["model"] == "imagen-4.0-fast-generate-001"
    assert models.calls[0]["prompt"] == "make a thumbnail"
