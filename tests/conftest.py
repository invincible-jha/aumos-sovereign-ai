"""Shared test fixtures for aumos-sovereign-ai.

Import standard fixtures from aumos_common.testing:
  - test_db_session: Async database session with transaction rollback
  - test_client: HTTPX async client configured against the FastAPI app
  - mock_tenant: A TenantContext fixture for auth override
  - UserFactory, TenantFactory: Factory Boy factories for test data

Override auth for endpoint tests using override_auth_dependency.
"""

import pytest
from httpx import AsyncClient

from aumos_common.auth import get_current_user
from aumos_common.testing import UserFactory, override_auth_dependency

from aumos_sovereign_ai.main import app


@pytest.fixture
def mock_user() -> UserFactory:
    """Create a test user with default permissions.

    Returns:
        A UserFactory instance suitable for auth override.
    """
    return UserFactory.create()


@pytest.fixture
async def client(mock_user: UserFactory) -> AsyncClient:
    """Async HTTP client with auth overrides applied.

    Args:
        mock_user: The test user fixture for auth override.

    Returns:
        Configured HTTPX AsyncClient for test requests.
    """
    app.dependency_overrides[get_current_user] = override_auth_dependency(mock_user)
    async with AsyncClient(app=app, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()
