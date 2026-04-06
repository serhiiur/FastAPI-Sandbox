from collections.abc import AsyncIterator
from typing import TypedDict

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from api import app, settings  # isort: skip


class Credentials(TypedDict):
  """Data structure to specify user credentials for authentication."""

  username: str
  password: str


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
  """Fixture to provide async HTTP client."""
  transport = ASGITransport(app=app)
  async with AsyncClient(transport=transport, base_url="http://test") as client:
    yield client


@pytest.fixture
def credentials() -> Credentials:
  """Fixture to provide user credentials for authentication."""
  return Credentials(username="joedoe", password="joedoe")


@pytest.mark.anyio
async def test_unauthenticated_access_returns_401(client: AsyncClient) -> None:
  resp = await client.get("/users/me/")
  assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_login_with_invalid_credentials_returns_401(
  client: AsyncClient,
  credentials: Credentials,
) -> None:
  credentials["username"] += "."
  resp = await client.post("/login", data=credentials)
  assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_login_with_valid_credentials_returns_200(
  client: AsyncClient,
  credentials: Credentials,
) -> None:
  resp = await client.post("/login", data=credentials)
  assert resp.status_code == status.HTTP_200_OK
  body = resp.json()
  assert "access_token" in body
  assert body["token_type"] == settings.token_type


@pytest.mark.anyio
async def test_authenticated_access_returns_200(
  client: AsyncClient,
  credentials: Credentials,
) -> None:
  login = await client.post("/login", data=credentials)
  token = login.json()["access_token"]

  headers = {"Authorization": f"{settings.token_type} {token}"}
  resp = await client.get("/users/me/", headers=headers)
  assert resp.status_code == status.HTTP_200_OK
  body = resp.json()
  assert body["username"] == credentials["username"]
