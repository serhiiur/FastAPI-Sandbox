import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from fakeredis import FakeAsyncRedis
from fastapi import status
from fastapi.testclient import TestClient
from main import WSManager, app, get_redis, get_ws_manager
from starlette.testclient import WebSocketTestSession

if TYPE_CHECKING:
  from redis.asyncio import Redis

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def redis_client() -> AsyncIterator["Redis"]:
  """Fake Redis client for testing."""
  async with FakeAsyncRedis() as client:
    yield client


@pytest.fixture(scope="session")
async def client(redis_client: "Redis") -> AsyncIterator[TestClient]:
  """HTTP client to test FastAPI endpoints."""

  async def override_get_redis() -> "Redis":
    return redis_client

  async def override_get_ws_manager() -> WSManager:
    return WSManager(redis_client)

  app.dependency_overrides[get_redis] = override_get_redis
  app.dependency_overrides[get_ws_manager] = override_get_ws_manager

  with TestClient(app) as test_client:
    yield test_client


@pytest.fixture
async def ws_client(client: TestClient) -> AsyncIterator[WebSocketTestSession]:
  """Websocket client to test websocket endpoints."""
  with client.websocket_connect("/ws") as ws:
    yield ws


async def test_health(client: TestClient) -> None:
  resp = client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


async def test_online(client: TestClient) -> None:
  resp = client.get("/online")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json()["online"] == 0
  assert "timestamp" in resp.json()


async def test_websocket_connect(client: TestClient) -> None:
  with client.websocket_connect("/ws"):
    resp = client.get("/online")
    assert resp.json()["online"] == 1


async def test_websocket_disconnect(client: TestClient) -> None:
  with client.websocket_connect("/ws"):
    await asyncio.sleep(1)
  resp = client.get("/online")
  assert resp.json()["online"] == 0


async def test_websocket_broadcast(ws_client: WebSocketTestSession) -> None:
  message = "Hello, World!"
  ws_client.send_text(message)
  data = ws_client.receive_text()
  assert data == message


@pytest.mark.skip(reason="Doesn't work properly, needs investigation")
async def test_websocket_broadcast_multiple_clients(client: TestClient) -> None:
  with client.websocket_connect("/ws") as ws1, client.websocket_connect("/ws") as ws2:
    message = "Hello, Everyone!"
    ws1.send_text(message)
    data1 = ws1.receive_text()
    data2 = ws2.receive_text()
    assert data1 == message
    assert data2 == message


# async def test_websocket_broadcast_multiple_clients(client: TestClient) -> None:
#   with client.websocket_connect("/ws") as ws1:
#     ws1.send_text("Hello from client 1")
#     data1 = ws1.receive_text()
#     assert data1 == "Hello from client 1"

#     with client.websocket_connect("/ws") as ws2:
#       ws2.send_text("Hello from client 2")
#       data2 = ws2.receive_text()
#       assert data2 == "Hello from client 2"

#     ws1.send_text("Another message from client 1")
#     data1_new = ws1.receive_text()
#     assert data1_new == "Another message from client 1"
