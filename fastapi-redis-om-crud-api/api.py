import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from aredis_om import Field, JsonModel, Migrator
from aredis_om.model.model import NotFoundError
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from redis.asyncio import ConnectionPool, Redis

# Settings
VERSION = os.getenv("VERSION", "0.0.1")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
os.environ["REDIS_OM_URL"] = REDIS_URL


def configure_logging() -> logging.Logger:
  """Configure app logging and return logger object."""
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
  )
  return logging.getLogger(__name__)


class CreateUser(BaseModel):
  """Schema to create a new user."""

  name: str = Field(
    min_length=1,
    max_length=255,
    description="Name of the user",
  )
  email: EmailStr = Field(description="Email of the user")


class UpdateUser(BaseModel):
  """Schema to update an existing user."""

  name: str | None = Field(
    None,
    min_length=1,
    max_length=255,
    description="Name of the user",
  )
  email: EmailStr | None = Field(None, description="Email of the user")


class User(CreateUser, JsonModel):
  """Schema to represent info about user."""

  created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def get_logger(request: Request) -> logging.Logger:
  """Return logger object, initialized in the lifespan."""
  return request.app.state.logger


def get_redis(request: Request) -> Redis:
  """Return initialized instance of Redis client from lifespan."""
  return request.app.state.redis


async def user_not_found_error_handler(
  request: Request,
  e: NotFoundError,
) -> JSONResponse:
  """User not found error handler."""
  logger = get_logger(request)
  logger.info("Database Not Found Error: %s", e)
  client_message = {"error": "User not found"}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


async def unexpected_error_handler(
  request: Request,
  e: Exception,
) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  logger = get_logger(request)
  logger.critical("Internal Server Error: %s", e)
  client_message = {"error": "Internal server error. Try again later"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator:
  """Init Redis client with connection pool and migrate Redis OM models."""
  logger = configure_logging()
  redis_connection_pool = ConnectionPool.from_url(REDIS_URL)
  redis_client = Redis(connection_pool=redis_connection_pool)

  # run migrations before running queries
  await Migrator().run()

  # Set application state
  app.state.redis = redis_client
  app.state.logger = logger

  yield

  await redis_connection_pool.disconnect()
  await redis_client.close()


app = FastAPI(
  title="Users Management App",
  description="CRUD Application to Manage Users",
  lifespan=lifespan,
  debug=DEBUG,
  version=VERSION,
  exception_handlers={
    NotFoundError: user_not_found_error_handler,
    Exception: unexpected_error_handler,
  },
)

# https://fastapi.tiangolo.com/tutorial/dependencies/#share-annotated-dependencies
UserID = Annotated[str, "user id in the database"]


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health(redis: Annotated[Redis, Depends(get_redis)]) -> Response:
  """Sample healthcheck endpoint."""
  ping = await redis.ping()
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "healthy" if ping else "unhealthy"},
  )


@app.get("/users/{pk}")
async def get_user(pk: UserID) -> User:
  """Get information about user from the database."""
  return await User.get(pk)


@app.get("/users")
async def get_users(offset: int = 0, limit: int = 10) -> list[User]:
  """Get information about users from the database."""
  return await User.find().sort_by("-created_at").page(offset, limit)


@app.post(
  "/users",
  status_code=status.HTTP_201_CREATED,
)
async def add_user(user: CreateUser) -> User:
  """Add a new user to the database."""
  return await User.model_validate(user).save()


@app.delete(
  "/users/{pk}",
  status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(pk: UserID) -> None:
  """Delete a user from the database."""
  await User.delete(pk)


@app.patch("/users/{pk}")
async def update_user(pk: UserID, user: UpdateUser) -> User:
  """Update existing user in the database."""
  db_user = await User.get(pk)
  await db_user.update(**user.model_dump(exclude_defaults=True))
  return db_user
