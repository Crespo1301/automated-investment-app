"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings


app = FastAPI(
    title="Automated Investment API",
    version="0.1.0",
    summary="Control plane for an autonomous personal trading system.",
    description=(
        "This service models the core passthroughs for a personal autonomous "
        "trading stack: market ingress, signal generation, risk review, "
        "execution intent, and operator-facing portfolio summaries."
    ),
)

app.include_router(router)


@app.get("/healthz", tags=["system"])
def healthcheck() -> dict[str, str]:
    """Simple process health probe for local orchestration and uptime checks."""

    return {"status": "ok", "environment": settings.environment}

