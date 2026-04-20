from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin_jobs, episodes, health
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Pleopod Backend",
        version="0.1.0",
        description=(
            "AI-agent podcast generation backend with FastAPI, "
            "Supabase, and Cloudflare R2."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_local else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(admin_jobs.router)
    app.include_router(episodes.router)
    return app


app = create_app()
