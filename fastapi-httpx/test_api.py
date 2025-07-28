from collections.abc import AsyncIterator  # noqa: I001

import httpx
import pytest

from fastapi import status
from pytest_httpx import HTTPXMock

from api import Post, app, get_http_client

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend for running async tests via pytest."""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[httpx.AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  transport = httpx.ASGITransport(app)
  async with (
    httpx.AsyncClient(base_url="http://test", transport=transport) as api_client,
    httpx.AsyncClient(base_url="http://test") as http_client,
  ):
    app.dependency_overrides[get_http_client] = lambda: http_client
    yield api_client


async def test_health(client: httpx.AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "health"


async def test_get_post(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
  """Test getting a post by ID."""
  post = Post.model_config["json_schema_extra"]["example"]
  httpx_mock.add_response(json=post)
  resp = await client.get("/posts/1")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == post


async def test_get_all_posts(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
  """Test getting all posts."""
  posts = [Post.model_config["json_schema_extra"]["example"]]
  httpx_mock.add_response(json=posts)
  resp = await client.get("/posts")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == posts


# async def test_get_unknown_post(
#   httpx_mock: HTTPXMock, client: httpx.AsyncClient
# ) -> None:
#   """Test getting a post by ID that does not exist."""
#   httpx_mock.add_response(
#     json={"error": "Post not found"}, status_code=status.HTTP_404_NOT_FOUND
#   )
#   resp = await client.get("/posts/999")
#   assert resp.status_code == status.HTTP_404_NOT_FOUND
#   assert resp.json() == {"API Error": "Post not found"}


async def test_get_unknown_post(
  httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
  """Test getting a post by ID that does not exist."""
  httpx_mock.add_exception(
    httpx.HTTPStatusError(
      "",
      request=httpx.Request("GET", "/posts/999"),
      response=httpx.Response(404, json={"error": "Post not found"}),
    )
  )
  resp = await client.get("/posts/999")
  assert resp.status_code == status.HTTP_404_NOT_FOUND
  assert resp.json() == {"API Error": "Post not found"}


async def test_create_post(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
  """Test creating a new post."""
  post = Post.model_config["json_schema_extra"]["example"]
  httpx_mock.add_response(json=post, status_code=status.HTTP_201_CREATED)
  resp = await client.post("/posts", json=post)
  assert resp.status_code == status.HTTP_201_CREATED
  assert resp.json() == post


async def test_delete_post(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
  """Test deleting a post by ID."""
  httpx_mock.add_response(status_code=status.HTTP_204_NO_CONTENT)
  resp = await client.delete("/posts/1")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.content == b""


async def test_update_post(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
  """Test updating an existing post."""
  updated_post = Post.model_config["json_schema_extra"]["example"]
  updated_post["title"] = "Updated Title"
  httpx_mock.add_response(json=updated_post)
  resp = await client.put("/posts/1", json=updated_post)
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json() == updated_post
