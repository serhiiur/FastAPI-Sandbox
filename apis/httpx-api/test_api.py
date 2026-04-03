from collections.abc import AsyncIterator  # noqa: I001
from typing import TYPE_CHECKING

import httpx
import pytest

from fastapi import status
from pytest_httpx import HTTPXMock

from api import Post, app, get_http_client

if TYPE_CHECKING:
  from faker import Faker

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
    # Client for making requests to the internal API
    httpx.AsyncClient(base_url="http://test", transport=transport) as api_client,
    # Client for making requests to the remote API
    httpx.AsyncClient(base_url="http://test") as http_client,
  ):

    async def override_http_client() -> httpx.AsyncClient:
      return http_client

    app.dependency_overrides[get_http_client] = override_http_client
    yield api_client


@pytest.fixture
def post(faker: "Faker") -> Post:
  """Generate a random post."""
  faker.seed_instance()
  return Post.model_construct(
    id=faker.pyint(),
    title=faker.sentence(),
    body=faker.text(),
    userId=faker.pyint(),
  )


async def test_health(client: httpx.AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


async def test_fetch_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post: Post,
) -> None:
  mock_post = post.model_dump(by_alias=True)
  httpx_mock.add_response(json=mock_post)
  resp = await client.get(f"/posts/{post.id}")
  assert resp.status_code == status.HTTP_200_OK
  assert mock_post == resp.json()


async def test_fetch_all_posts(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post: Post,
) -> None:
  posts = [post]
  mock_posts = [post.model_dump(by_alias=True) for post in posts]
  httpx_mock.add_response(json=mock_posts)
  resp = await client.get("/posts")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["posts"] == mock_posts
  assert resp_json["count"] == len(mock_posts)


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


async def test_fetch_unknown_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
) -> None:
  post_id = -1
  endpoint = f"/posts/{post_id}"
  httpx_mock.add_exception(
    httpx.HTTPStatusError(
      "",
      request=httpx.Request("GET", endpoint),
      response=httpx.Response(404, json={"error": "Post not found"}),
    )
  )
  resp = await client.get(endpoint)
  assert resp.status_code == status.HTTP_404_NOT_FOUND
  assert resp.json() == {"error": "Post not found"}


async def test_create_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post: Post,
) -> None:
  mock_post = post.model_dump(by_alias=True)
  httpx_mock.add_response(json=mock_post, status_code=status.HTTP_201_CREATED)
  resp = await client.post("/posts", json=mock_post)
  assert resp.status_code == status.HTTP_201_CREATED
  assert mock_post == resp.json()


async def test_delete_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
) -> None:
  post_id = 1
  httpx_mock.add_response(status_code=status.HTTP_204_NO_CONTENT)
  resp = await client.delete(f"/posts/{post_id}")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.content == b""


async def test_update_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post: Post,
) -> None:
  post.title += "."
  mock_post = post.model_dump(by_alias=True)
  httpx_mock.add_response(json=mock_post)
  resp = await client.put(f"/posts/{post.id}", json=mock_post)
  assert resp.status_code == status.HTTP_200_OK
  assert mock_post == resp.json()
