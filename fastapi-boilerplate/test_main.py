import logging
from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from fastapi import status
from httpx import ASGITransport, AsyncClient

from main import ApiHealth, ApiVersion, app  # isort: skip

pytestmark = pytest.mark.anyio


# Override application state objects
app.state.logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Fixture to provide async HTTP client for API endpoints."""
  async with LifespanManager(app) as manager:
    transport = ASGITransport(manager.app)
    base_url = "http://test"
    async with AsyncClient(base_url=base_url, transport=transport) as client:
      yield client


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/api/health")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == ApiHealth.model_construct().model_dump()


async def test_version(client: AsyncClient) -> None:
  resp = await client.get("/api/version")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == ApiVersion.model_construct().model_dump()
