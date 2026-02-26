"""AumOS Sovereign AI service entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aumos_common.app import create_app
from aumos_common.database import init_database

from aumos_sovereign_ai.api.router import router
from aumos_sovereign_ai.settings import Settings

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Args:
        app: The FastAPI application instance.

    Yields:
        None
    """
    # Startup
    init_database(settings.database)
    # TODO: Initialize Kafka publisher for sovereignty events
    # TODO: Initialize K8s client for regional deployments
    # TODO: Initialize Redis client for compliance cache
    yield
    # Shutdown
    # TODO: Close Kafka connections
    # TODO: Close Redis connections


app: FastAPI = create_app(
    service_name="aumos-sovereign-ai",
    version="0.1.0",
    settings=settings,
    lifespan=lifespan,
    health_checks=[
        # HealthCheck(name="postgres", check_fn=check_db),
        # HealthCheck(name="kafka", check_fn=check_kafka),
    ],
)

app.include_router(router, prefix="/api/v1")
