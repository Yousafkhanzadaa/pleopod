from app.core.config import Settings
from app.providers.ai import AIProvider


def create_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "gemini":
        from app.providers.gemini import GeminiAIProvider

        return GeminiAIProvider(settings)

    from app.providers.fake import FakeAIProvider

    return FakeAIProvider()
