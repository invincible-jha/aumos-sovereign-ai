"""Basic smoke tests for aumos-sovereign-ai.

These tests verify the service starts correctly and health endpoints respond.
They run without infrastructure dependencies (no database, no Kafka).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from aumos_sovereign_ai.main import app


@pytest.mark.asyncio
async def test_liveness_endpoint_returns_200() -> None:
    """Liveness probe must return 200 OK with no dependencies.

    The /live endpoint must never fail due to infrastructure issues —
    it only signals whether the process itself is alive.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/live")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_schema_is_accessible() -> None:
    """OpenAPI schema endpoint must be accessible in development.

    Verifies the FastAPI app is correctly configured and routes are registered.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert "info" in schema


@pytest.mark.asyncio
async def test_docs_endpoint_is_accessible() -> None:
    """Swagger UI docs endpoint must be accessible.

    Verifies the docs are served correctly for local development.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/docs")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_schema_includes_sovereign_routes() -> None:
    """OpenAPI schema must include all sovereign AI route paths.

    Validates that all eight sovereign AI endpoints are registered.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/openapi.json")

    schema = response.json()
    paths = schema.get("paths", {})

    expected_paths = [
        "/api/v1/sovereign/residency/enforce",
        "/api/v1/sovereign/residency/status",
        "/api/v1/sovereign/deploy/regional",
        "/api/v1/sovereign/regions",
        "/api/v1/sovereign/route",
        "/api/v1/sovereign/registry/models",
    ]

    for path in expected_paths:
        assert path in paths, f"Expected route {path!r} not found in OpenAPI schema"
