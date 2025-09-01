from collections.abc import AsyncIterator  # noqa: I001

import pytest

# from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from request_state_api import app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  # async with LifespanManager(app) as manager:
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


@pytest.mark.anyio
async def test(client: AsyncClient) -> None:
  with pytest.raises(AttributeError) as e:
    resp = await client.get("/test")
  assert "'State' object has no attribute 'client'" in str(e.value)
