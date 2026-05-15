import base64

import pytest

from app.providers.openai import OpenAIImageProvider


@pytest.mark.asyncio
async def test_generate_image_decodes_openai_image_response(monkeypatch) -> None:
    provider = OpenAIImageProvider.__new__(OpenAIImageProvider)
    provider.settings = type("Settings", (), {"openai_image_output_format": "png"})()

    captured: dict[str, str] = {}

    def fake_generate(prompt: str, model: str):
        captured["prompt"] = prompt
        captured["model"] = model
        return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}]}

    monkeypatch.setattr(provider, "_generate_image_sync", fake_generate)

    image = await provider.generate_image("make a thumbnail", "gpt-image-2")

    assert image.data == b"image-bytes"
    assert image.mime_type == "image/png"
    assert image.prompt == "make a thumbnail"
    assert captured == {"prompt": "make a thumbnail", "model": "gpt-image-2"}


def test_generate_image_sync_posts_openai_image_options(monkeypatch) -> None:
    provider = OpenAIImageProvider.__new__(OpenAIImageProvider)
    provider.settings = type(
        "Settings",
        (),
        {
            "openai_api_key": "openai-key",
            "openai_image_size": "1280x720",
            "openai_image_quality": "medium",
            "openai_image_output_format": "png",
        },
    )()

    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"data": [{"b64_json": "abc"}]}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.providers.openai.httpx.post", fake_post)

    response = provider._generate_image_sync("make a thumbnail", "gpt-image-2")

    assert response == {"data": [{"b64_json": "abc"}]}
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["headers"] == {
        "Authorization": "Bearer openai-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "prompt": "make a thumbnail",
        "model": "gpt-image-2",
        "n": 1,
        "size": "1280x720",
        "quality": "medium",
        "output_format": "png",
    }
    assert captured["timeout"] == 120
