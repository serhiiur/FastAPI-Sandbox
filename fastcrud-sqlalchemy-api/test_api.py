from collections.abc import AsyncIterator

import pytest
from api import (
  Base,
  CreateUser,
  UpdateUser,
  app,
  configure_logging,
  get_session,
  settings,
)
from faker import Faker
from fastapi import status
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)

engine = create_async_engine(settings.test_database_url)
async_session = async_sessionmaker(engine, expire_on_commit=False)

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture
def faker() -> Faker:
  """Fixture to provide a new instance of the Faker class on each call."""
  return Faker()


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
  app.state.logger = configure_logging(__name__)
  app.dependency_overrides[get_session] = override_get_session
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


@pytest.fixture
def user(faker: Faker) -> CreateUser:
  """Generate random info about user."""
  return CreateUser.model_construct(name=faker.name(), email=faker.email())


async def create_user(
  client: AsyncClient,
  user: CreateUser,
  expected_http_status_code: int = status.HTTP_200_OK,
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


async def test_create_user_email_already_exists_error(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  await create_user(client, user)
  resp = await create_user(
    client,
    user,
    expected_http_status_code=status.HTTP_409_CONFLICT,
  )
  assert "already exists" in resp.json()["error"]


async def test_create_user_success(client: AsyncClient, user: CreateUser) -> None:
  resp = await create_user(client, user)
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "id" in resp_json
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


async def test_get_unknown_user_error(client: AsyncClient, faker: Faker) -> None:
  user_id = faker.uuid4()
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_get_user_success(client: AsyncClient, user: CreateUser) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  resp = await client.get(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["name"] == user.name
  assert resp_json["email"] == user.email
  assert "id" in resp_json
  assert "created_at" in resp_json
  assert "updated_at" in resp_json


async def test_delete_unknown_user_error(client: AsyncClient, faker: Faker) -> None:
  user_id = faker.uuid4()
  resp = await client.delete(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_user_success(client: AsyncClient, user: CreateUser) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  resp = await client.delete(f"/users/{user_id}")
  assert resp.status_code == status.HTTP_200_OK


async def test_update_unknown_user_error(client: AsyncClient, faker: Faker) -> None:
  user_id = faker.uuid4()
  resp = await client.patch(f"/users/{user_id}", json={})
  assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_update_user_name_success(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  new_user_info = UpdateUser(name=faker.name())
  resp = await client.patch(
    f"/users/{user_id}",
    json=new_user_info.model_dump(exclude_defaults=True),
  )
  assert resp.status_code == status.HTTP_200_OK
  assert resp.text == "null"


async def test_update_user_email_success(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  new_user_info = UpdateUser(email=faker.email())
  resp = await client.patch(
    f"/users/{user_id}",
    json=new_user_info.model_dump(exclude_defaults=True),
  )
  assert resp.status_code == status.HTTP_200_OK
  assert resp.text == "null"


async def test_update_user_email_already_exists_error(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  first_user_email = user.email
  await create_user(client, user)
  user.email = faker.email()
  create_second_user_resp = await create_user(client, user)
  second_user_id = create_second_user_resp.json()["id"]
  new_user_info = UpdateUser(email=first_user_email)
  update_second_user_email_resp = await client.patch(
    f"/users/{second_user_id}",
    json=new_user_info.model_dump(),
  )
  assert update_second_user_email_resp.status_code == status.HTTP_409_CONFLICT
  assert "already exists" in update_second_user_email_resp.json()["error"]


async def test_update_user_success(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  create_user_resp = await create_user(client, user)
  user_id = create_user_resp.json()["id"]
  new_user_info = UpdateUser.model_construct(
    email=faker.email(),
    name=faker.name(),
  )
  resp = await client.patch(
    f"/users/{user_id}",
    json=new_user_info.model_dump(),
  )
  assert resp.status_code == status.HTTP_200_OK
  assert resp.text == "null"


async def test_get_multiple_users_success(
  client: AsyncClient,
  user: CreateUser,
) -> None:
  await create_user(client, user)
  resp = await client.get("/users")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert "data" in resp_json
  assert "total_count" in resp_json
  assert len(resp_json["data"]) == resp_json["total_count"]


async def test_get_multiple_users_with_pagination_success(
  client: AsyncClient,
  user: CreateUser,
  faker: Faker,
) -> None:
  await create_user(client, user)
  user.email = faker.email()
  await create_user(client, user)
  resp = await client.get("/users", params={"itemsPerPage": 1})
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert "data" in resp_json
  assert "total_count" in resp_json
  assert len(resp_json["data"]) == resp_json["items_per_page"] == 1


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
