from collections.abc import AsyncIterator  # noqa: I001

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from request_app_state_api import app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    app.state.client = ac
    yield ac


@pytest.mark.anyio
async def test(client: AsyncClient) -> None:
  resp = await client.get("/test")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json()["result"] is True
