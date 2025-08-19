from collections.abc import AsyncIterator  # noqa: I001

import httpx
import pytest

from asgi_lifespan import LifespanManager
from faker import Faker
from fastapi import status
from pytest_httpx import HTTPXMock

from api import Post, app, get_http_client


faker = Faker()

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend for running async tests via pytest."""
  return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[httpx.AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  async with LifespanManager(app) as manager:
    transport = httpx.ASGITransport(app=manager.app)
    async with (
      # Client for making requests to the internal API
      httpx.AsyncClient(base_url="http://test", transport=transport) as api_client,
      # Client for making requests to the remote API
      httpx.AsyncClient(base_url="http://test") as http_client,
    ):
      app.dependency_overrides[get_http_client] = lambda: http_client
      yield api_client


def generate_random_post() -> Post:
  """Generate a random post."""
  return Post(
    id=faker.pyint(),
    title=faker.sentence(),
    body=faker.text(),
    userId=faker.pyint(),
  )


async def test_health(client: httpx.AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


@pytest.mark.parametrize("post", [generate_random_post()])
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


@pytest.mark.parametrize("posts", [[generate_random_post()]])
async def test_fetch_all_posts(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  posts: list[Post],
) -> None:
  mock_posts = [post.model_dump(by_alias=True) for post in posts]
  httpx_mock.add_response(json=mock_posts)
  resp = await client.get("/posts")
  assert resp.status_code == status.HTTP_200_OK
  assert mock_posts == resp.json()


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


@pytest.mark.parametrize("post_id", [-1])
async def test_fetch_unknown_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post_id: int,
) -> None:
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


@pytest.mark.parametrize("post", [generate_random_post()])
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


@pytest.mark.parametrize("post_id", [1])
async def test_delete_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post_id: int,
) -> None:
  httpx_mock.add_response(status_code=status.HTTP_204_NO_CONTENT)
  resp = await client.delete(f"/posts/{post_id}")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.content == b""


@pytest.mark.parametrize("post", [generate_random_post()])
async def test_update_post(
  httpx_mock: HTTPXMock,
  client: httpx.AsyncClient,
  post: Post,
) -> None:
  post.title = faker.sentence()
  mock_post = post.model_dump(by_alias=True)
  httpx_mock.add_response(json=mock_post)
  resp = await client.put(f"/posts/{post.id}", json=mock_post)
  assert resp.status_code == status.HTTP_200_OK
  assert mock_post == resp.json()
