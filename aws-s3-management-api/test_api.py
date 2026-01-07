import logging  # noqa: I001
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from aiobotocore.session import get_session
from aiobotocore.stub import AioStubber
from fastapi import status
from httpx import ASGITransport, AsyncClient

from api import app, get_s3_client, settings

if TYPE_CHECKING:
  from faker import Faker
  from types_aiobotocore_s3.client import S3Client


pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def anyio_backend() -> str:
  """Backend (asyncio) for pytest to run async tests."""
  return "asyncio"


@pytest.fixture(scope="session")
async def s3_client() -> AsyncIterator["S3Client"]:
  """Async client to interact with AWS S3."""
  s3_session = get_session()
  async with s3_session.create_client("s3") as client:
    yield client


@pytest.fixture(scope="session")
async def client(s3_client: "S3Client") -> AsyncIterator[AsyncClient]:
  """Async HTTP client to test FastAPI endpoints."""

  async def override_get_s3_client() -> "S3Client":
    return s3_client

  # a different logger specifically for testings
  app.state.logger = logging.getLogger(__name__)
  app.dependency_overrides[get_s3_client] = override_get_s3_client
  transport = ASGITransport(app)
  async with AsyncClient(base_url="http://test", transport=transport) as ac:
    yield ac


@pytest.fixture
def s3_bucket_name(faker: "Faker") -> str:
  """Return random AWS S3 bucket name."""
  faker.seed_instance()
  return f"{faker.user_name()}-bucket"


@pytest.fixture
def s3_object_name(faker: "Faker") -> str:
  """Return random AWS S3 object name."""
  faker.seed_instance()
  return faker.file_name()


async def test_health(client: AsyncClient) -> None:
  resp = await client.get("/health")
  assert resp.status_code == status.HTTP_204_NO_CONTENT
  assert resp.headers["x-status"] == "health"


async def test_version(client: AsyncClient) -> None:
  resp = await client.get("/version")
  assert resp.status_code == status.HTTP_200_OK
  assert resp.json().get("version") == settings.version


async def test_s3_list_objects(
  client: AsyncClient,
  s3_client: "S3Client",
  s3_bucket_name: str,
  s3_object_name: str,
) -> None:
  s3_list_objects_resp = {"Name": s3_bucket_name, "Contents": [{"Key": s3_object_name}]}
  s3_list_objects_params = {"Bucket": s3_bucket_name}
  with AioStubber(s3_client) as stubber:
    stubber.add_response(
      "list_objects_v2", s3_list_objects_resp, s3_list_objects_params
    )
    resp = await client.get(f"/bucket/objects/list/{s3_bucket_name}")
  assert resp.status_code == status.HTTP_200_OK
  resp_json = resp.json()
  assert resp_json["bucket"] == s3_bucket_name
  assert resp_json["count"] == 1
  assert s3_object_name in resp_json["objects"]


async def test_bucket_doesnt_exist(
  s3_client: "S3Client",
  client: AsyncClient,
  s3_bucket_name: str,
) -> None:
  service_message = "The specified bucket does not exist."
  with AioStubber(s3_client) as stubber:
    stubber.add_client_error(
      method="list_objects_v2",
      service_error_code="NoSuchBucket",
      service_message=service_message,
      http_status_code=status.HTTP_404_NOT_FOUND,
    )
    resp = await client.get(f"/bucket/objects/list/{s3_bucket_name}")
  assert resp.status_code == status.HTTP_404_NOT_FOUND
  assert resp.json() == service_message
