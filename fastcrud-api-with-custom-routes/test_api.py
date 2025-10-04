from collections.abc import AsyncIterator  # noqa: I001

import pytest
from faker import Faker
from fastapi import status
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)

from api import (
  MAX_USER_NAME_LENGTH,
  MIN_USER_NAME_LENGTH,
  Base,
  CreateUser,
  app,
  get_session,
  settings,
)

pytestmark = pytest.mark.anyio

engine = create_async_engine(settings.test_database_url)
async_session = async_sessionmaker(
  engine,
  class_=AsyncSession,
  expire_on_commit=False,
)


@pytest.fixture
def faker() -> Faker:
  """Faker instance to generate random data."""
  return Faker()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def migrate_db() -> AsyncIterator[None]:
  """Create and drop test test db on startup and shutdown."""
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.drop_all)


async def override_get_session() -> AsyncIterator[AsyncSession]:
  """Override dependency for API routes to interact with db."""
  async with async_session() as session:
    yield session


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""
  app.dependency_overrides[get_session] = override_get_session
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


@pytest.fixture
def user(faker: Faker) -> CreateUser:
  """Generate random info about user to be created."""
  return CreateUser.model_construct(name=faker.name(), email=faker.email())


async def create_user(
  client: AsyncClient,
  user: CreateUser,
  expected_http_status_code: int = status.HTTP_201_CREATED,
) -> Response:
  """Perform API call to create a random user for testing."""
  resp = await client.post("/users", json=user.model_dump())
  assert resp.status_code == expected_http_status_code
  return resp


async def get_user(
  client: AsyncClient,
  user_id: str,
  expected_http_status_code: int = status.HTTP_200_OK,
) -> Response:
  """Perform API call to get a random user for testing."""
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == expected_http_status_code
  return resp


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "ok"


async def test_create_user_incorrect_email(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  user.email = user.name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
  )
  assert "value is not a valid email address" in resp.json()["error"]


async def test_create_user_too_long_name(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  random_long_name = faker.pystr(
    min_chars=MAX_USER_NAME_LENGTH + 1,
    max_chars=MAX_USER_NAME_LENGTH + 1,
  )
  user.name = random_long_name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
  )
  assert f"at most {MAX_USER_NAME_LENGTH} characters" in resp.json()["error"]


async def test_create_user_too_short_name(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  random_short_name = faker.pystr(
    min_chars=MIN_USER_NAME_LENGTH - 1,
    max_chars=MIN_USER_NAME_LENGTH - 1,
  )
  user.name = random_short_name
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
  )
  assert f"at least {MIN_USER_NAME_LENGTH} characters" in resp.json()["error"]


async def test_create_user(client: AsyncClient, user: CreateUser) -> None:
  resp = await create_user(client, user)
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "id" in resp_json


async def test_create_user_email_already_exists(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  await create_user(client, user)
  # Create second user with same email
  create_second_user_resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_409_CONFLICT,
  )
  assert "already exists" in create_second_user_resp.json()["error"]


async def test_get_unknown_user(client: AsyncClient, faker: Faker) -> None:
  unknown_user_id = faker.uuid4()
  resp = await client.get(f"/users/{unknown_user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_get_user(client: AsyncClient, user: CreateUser) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  get_user_resp = await client.get(f"/users/{user_id}")
  assert get_user_resp.status_code == status.HTTP_200_OK
  resp_json = get_user_resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "id" in resp_json
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


async def test_delete_unknown_user(client: AsyncClient, faker: Faker) -> None:
  unknown_user_id = faker.uuid4()
  resp: Response = await client.delete(f"/users/{unknown_user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_user(client: AsyncClient, user: CreateUser) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  delete_user_resp: Response = await client.delete(f"/users/{user_id}")
  assert delete_user_resp.status_code == status.HTTP_204_NO_CONTENT


async def test_update_user_incorrect_email(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  update_user_resp = await client.patch(
    f"/users/{user_id}",
    json={"email": user.name},
  )
  assert update_user_resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
  assert "not a valid email address" in update_user_resp.json()["error"]


async def test_update_unknown_user(client: AsyncClient, faker: Faker) -> None:
  unknown_user_id = faker.uuid4()
  resp = await client.patch(f"/users/{unknown_user_id}", json={})
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_update_user_name(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  new_user_name = faker.name()
  update_user_resp = await client.patch(
    f"/users/{user_id}",
    json={"name": new_user_name},
  )
  resp_json = update_user_resp.json()
  assert update_user_resp.status_code == status.HTTP_200_OK
  assert resp_json["name"] == new_user_name


async def test_update_user_email(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  new_user_email = faker.email()
  update_user_resp = await client.patch(
    f"/users/{user_id}",
    json={"email": new_user_email},
  )
  resp_json = update_user_resp.json()
  assert update_user_resp.status_code == status.HTTP_200_OK
  assert resp_json["email"] == new_user_email


async def test_update_user_email_already_exists(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  # Create first user
  create_first_user_resp = await create_user(client, user)
  first_user_data = create_first_user_resp.json()

  # Create second user
  user.email = faker.email()
  create_second_user_resp = await create_user(client, user)
  second_user_data = create_second_user_resp.json()

  # Update email of second user to email of first user
  update_second_user_resp = await client.patch(
    f"/users/{second_user_data['id']}",
    json={"email": first_user_data["email"]},
  )
  assert update_second_user_resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in update_second_user_resp.json()["error"]


async def test_update_user(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  # Create user
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  # Update name and email of the user
  user.name = faker.name()
  user.email = faker.email()
  update_user_resp = await client.patch(
    f"/users/{user_id}",
    json=user.model_dump(),
  )
  resp_json = update_user_resp.json()
  assert update_user_resp.status_code == status.HTTP_200_OK
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email


async def test_get_users(client: AsyncClient, user: CreateUser) -> None:
  await create_user(client, user)
  resp = await client.get("/users")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["total_count"] >= 1
  assert len(resp_json["data"]) == resp_json["total_count"]


async def test_get_users_limit(client: AsyncClient, user: CreateUser) -> None:
  await create_user(client, user)
  request_params = {"limit": 1, "offset": 0}
  resp = await client.get("/users", params=request_params)
  resp_json = resp.json()
  assert resp_json["total_count"] >= 1
  assert len(resp_json["data"]) >= 1


async def test_get_users_limit_with_offset(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  await create_user(client, user)
  request_params = {"limit": 1, "offset": 1}
  resp = await client.get("/users", params=request_params)
  resp_json = resp.json()
  assert resp_json["total_count"] >= 1
  assert len(resp_json["data"]) >= 1


@pytest.mark.skip(reason="Not Implemented")
async def test_get_users_sort_filter(
  client: AsyncClient,
  total_users: int,
) -> None:
  pass


@pytest.mark.skip(reason="Not Implemented")
async def test_get_users_sort_order_filter(
  client: AsyncClient,
  total_users: int,
) -> None:
  pass
