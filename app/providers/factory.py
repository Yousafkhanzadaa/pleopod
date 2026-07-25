from app.core.config import Settings
from app.providers.ai import AIProvider, WordAlignmentProvider


def create_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "gemini":
        from app.providers.gemini import GeminiAIProvider

        return GeminiAIProvider(settings)

    from app.providers.fake import FakeAIProvider

    return FakeAIProvider()


def create_thumbnail_image_provider(
    settings: Settings,
    default_provider: AIProvider | None = None,
) -> AIProvider:
    provider = settings.resolved_thumbnail_image_provider
    if default_provider is not None and provider == settings.ai_provider:
        return default_provider

    if provider == "gemini":
        from app.providers.gemini import GeminiAIProvider

        return GeminiAIProvider(settings)
    if provider == "openai":
        from app.providers.openai import OpenAIImageProvider

        return OpenAIImageProvider(settings)

    from app.providers.fake import FakeAIProvider

    return FakeAIProvider()


def create_voice_provider(
    settings: Settings,
    default_provider: AIProvider | None = None,
) -> AIProvider:
    provider = settings.resolved_voice_provider
    if default_provider is not None and provider == settings.ai_provider:
        return default_provider

    if provider == "openai":
        from app.providers.openai import OpenAIAudioProvider

        return OpenAIAudioProvider(settings)
    if provider == "gemini":
        from app.providers.gemini import GeminiAIProvider

        return GeminiAIProvider(settings)

    from app.providers.fake import FakeAIProvider

    return FakeAIProvider()


def create_word_alignment_provider(
    settings: Settings,
    voice_provider: AIProvider | None = None,
) -> WordAlignmentProvider | None:
    if not settings.enable_word_alignment or not settings.openai_api_key:
        return None

    from app.providers.openai import OpenAIAudioProvider

    if isinstance(voice_provider, OpenAIAudioProvider):
        return voice_provider
    return OpenAIAudioProvider(settings)
