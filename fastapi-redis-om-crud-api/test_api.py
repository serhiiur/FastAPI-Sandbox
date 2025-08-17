import logging  # noqa: I001
from collections.abc import AsyncIterator

import pytest
from faker import Faker
from fakeredis import FakeAsyncRedis
from fastapi import status
from httpx import ASGITransport, AsyncClient

from api import CreateUser, UpdateUser, app, get_redis

faker = Faker()

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


async def override_get_redis() -> AsyncIterator[FakeAsyncRedis]:
  """Override real redis client."""
  async with FakeAsyncRedis() as client:
    yield client


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  # Set application state
  app.state.logger = logging.getLogger(__name__)

  transport = ASGITransport(app)
  app.dependency_overrides[get_redis] = override_get_redis
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


def generate_user_info() -> CreateUser:
  """Generate random info about user."""
  return CreateUser(name=faker.name(), email=faker.email())


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "healthy"


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_create_user(client: AsyncClient, user: CreateUser) -> None:
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == status.HTTP_201_CREATED
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "pk" in resp_json
  assert "created_at" in resp_json


@pytest.mark.parametrize("user_id", [faker.uuid4()])
async def test_get_unknown_user(client: AsyncClient, user_id: str) -> None:
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_get_valid_user(client: AsyncClient, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  user_id = create_user_resp.json()["pk"]
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == user.name
  assert get_user_resp_json["email"] == user.email
  assert "pk" in get_user_resp_json
  assert "created_at" in get_user_resp_json


@pytest.mark.parametrize("user", [generate_user_info()])
async def test_delete_user(client: AsyncClient, user: CreateUser) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  user_id = create_user_resp.json()["pk"]
  # Delete User
  delete_user_resp = await client.delete(f"/users/{user_id}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT
  # Get the deleted user
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(("user", "user_id"), [(UpdateUser(), faker.uuid4())])
async def test_update_unknown_user(
  client: AsyncClient, user: UpdateUser, user_id: str
) -> None:
  resp = await client.patch(f"/users/{user_id}", json=user.model_dump())
  assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
  ("user", "new_user_name"), [(generate_user_info(), faker.name())]
)
async def test_update_user_name(
  client: AsyncClient, user: CreateUser, new_user_name: str
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["pk"]
  # Update User
  updated_user = UpdateUser(name=new_user_name)
  updated_user_resp = await client.patch(
    f"/users/{user_id}", json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == updated_user.name
  assert get_user_resp_json["email"] == create_user_resp_json["email"]


@pytest.mark.parametrize(
  ("user", "new_user_email"), [(generate_user_info(), faker.email())]
)
async def test_update_user_email(
  client: AsyncClient, user: CreateUser, new_user_email: str
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["pk"]
  # Update User
  updated_user = UpdateUser(email=new_user_email)
  updated_user_resp = await client.patch(
    f"/users/{user_id}", json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == create_user_resp_json["name"]
  assert get_user_resp_json["email"] == updated_user.email


@pytest.mark.parametrize(
  ("user", "updated_user"),
  [(generate_user_info(), generate_user_info())],
)
async def test_update_user(
  client: AsyncClient, user: CreateUser, updated_user: UpdateUser
) -> None:
  # Create User
  create_user_resp = await client.post("/users", json=user.model_dump())
  assert create_user_resp.status_code == status.HTTP_201_CREATED
  create_user_resp_json = create_user_resp.json()
  user_id = create_user_resp_json["pk"]
  # Update User
  updated_user_resp = await client.patch(
    f"/users/{user_id}", json=updated_user.model_dump()
  )
  assert updated_user_resp.status_code == status.HTTP_200_OK
  # Get User
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  get_user_resp_json = get_user_resp.json()
  assert get_user_resp_json["pk"] == user_id
  assert get_user_resp_json["name"] == updated_user.name
  assert get_user_resp_json["email"] == updated_user.email
