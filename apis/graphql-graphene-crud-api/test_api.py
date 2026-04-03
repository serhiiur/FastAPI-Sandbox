from collections.abc import AsyncIterator  # noqa: I001

import pytest

from faker import Faker
from fastapi import status
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock
from graphql.error.graphql_error import GraphQLError

from api import (
  CreateUserInput,
  GraphQLAppContext,
  UpdateUserInput,
  app,
  schema,
)


faker = Faker()

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend for running async tests via pytest."""
  return "asyncio"


@pytest.fixture(scope="session")
async def api_client() -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  t = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=t) as client:
    yield client


@pytest.fixture(scope="session")
async def http_client() -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test remote API calls."""
  async with AsyncClient(base_url="http://test") as client:
    yield client


async def test_health(api_client: AsyncClient) -> None:
  resp = await api_client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


@pytest.mark.parametrize(
  "users",
  [
    [
      CreateUserInput(
        name=faker.name(),
        username=faker.user_name(),
        email=faker.email(),
        phone=faker.phone_number(),
        website=faker.url(),
      ),
    ]
  ],
)
async def test_get_users(
  http_client: AsyncClient,
  httpx_mock: HTTPXMock,
  users: list[CreateUserInput],
) -> None:
  query = """
    query GetUsers{
      users{
        name
        username
        email
        phone
        website
      }
    }
  """
  mock_users = [user.kwargs for user in users]
  httpx_mock.add_response(json=mock_users)
  res = await schema.execute_async(
    query,
    context_value=GraphQLAppContext(http_client=http_client),
  )
  assert res.errors is None
  assert res.data["users"] == mock_users


@pytest.mark.parametrize(
  "user",
  [
    CreateUserInput(
      name=faker.name(),
      email=faker.email(),
      phone=faker.phone_number(),
    )
  ],
)
async def test_get_user(
  http_client: AsyncClient,
  httpx_mock: HTTPXMock,
  user: CreateUserInput,
) -> None:
  query = """
    query GetUser{
      user(userId: "1"){
        name
        email
        phone
      }
    }
  """
  mock_user = user.kwargs
  httpx_mock.add_response(json=mock_user)
  res = await schema.execute_async(
    query,
    context_value=GraphQLAppContext(http_client=http_client),
  )
  assert res.errors is None
  assert res.data["user"] == mock_user


async def test_get_unknown_user(
  http_client: AsyncClient,
  httpx_mock: HTTPXMock,
) -> None:
  query = """
    query GetUser{
      user(userId: "-1"){
        username
      }
    }
  """
  httpx_mock.add_response(json={})
  res = await schema.execute_async(
    query,
    context_value=GraphQLAppContext(http_client=http_client),
  )
  assert res.data["user"] is None
  assert res.errors
  error = res.errors[0]
  assert isinstance(error, GraphQLError)
  assert "not found" in error.message
  assert error.path == ["user"]


@pytest.mark.parametrize(
  "user",
  [
    CreateUserInput(
      name=faker.name(),
      username=faker.user_name(),
      email=faker.email(),
    )
  ],
)
async def test_create_user(
  http_client: AsyncClient,
  httpx_mock: HTTPXMock,
  user: CreateUserInput,
) -> None:
  mock_user = user.kwargs
  query = f"""
   mutation CreateUser{{
    createUser(user: {{
      name: "{mock_user["name"]}",
      username: "{mock_user["username"]}",
      email: "{mock_user["email"]}",
    }}){{
      name
      username
      email
    }}
  }}
  """
  httpx_mock.add_response(json=mock_user)
  res = await schema.execute_async(
    query,
    context_value=GraphQLAppContext(http_client=http_client),
  )
  assert res.errors is None
  assert res.data["createUser"] == mock_user


@pytest.mark.parametrize(
  ("user", "user_id"),
  [
    (
      UpdateUserInput(
        name=faker.name(),
        phone=faker.phone_number(),
      ),
      faker.random_int(),
    )
  ],
)
async def test_update_user(
  http_client: AsyncClient,
  httpx_mock: HTTPXMock,
  user: UpdateUserInput,
  user_id: str,
) -> None:
  mock_user = user.kwargs
  query = f"""
   mutation UpdateUser{{
    updateUser(userId: "{user_id}", user: {{
      name: "{mock_user["name"]}",
      phone: "{mock_user["phone"]}",
    }}){{
      name
      phone
    }}
  }}
  """
  httpx_mock.add_response(json=mock_user)
  res = await schema.execute_async(
    query,
    context_value=GraphQLAppContext(http_client=http_client),
  )
  assert res.errors is None
  assert res.data["updateUser"] == mock_user


@pytest.mark.parametrize("user_id", [faker.random_int()])
async def test_delete_user(
  http_client: AsyncClient,
  httpx_mock: HTTPXMock,
  user_id: str,
) -> None:
  mock_user = {"userId": user_id}
  query = f"""
    mutation DeleteUser{{
      deleteUser(userId: "{user_id}"){{
        ok
      }}
    }}
  """
  httpx_mock.add_response(json=mock_user)
  res = await schema.execute_async(
    query,
    context_value=GraphQLAppContext(http_client=http_client),
  )
  assert res.errors is None
  assert res.data["deleteUser"] == {"ok": True}
