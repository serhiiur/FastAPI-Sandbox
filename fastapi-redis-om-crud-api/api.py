import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, TypedDict

from aredis_om import Field, JsonModel, Migrator
from aredis_om.model.model import NotFoundError
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from redis.asyncio import ConnectionPool, Redis

# Redis connection URL
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class CreateUser(BaseModel):
  """Schema to create a new user."""

  name: str = Field(min_length=1, max_length=255, description="Name of the user")
  email: EmailStr = Field(description="Email of the user")


class UpdateUser(BaseModel):
  """Schema to update an existing user."""

  name: str | None = Field(
    None, min_length=1, max_length=255, description="Name of the user"
  )
  email: EmailStr | None = Field(None, description="Email of the user")


class User(CreateUser, JsonModel):
  """Schema to represent info about user."""

  created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


async def user_not_found_error_handler(
  _: Request,
  e: NotFoundError,  # noqa: ARG001
) -> JSONResponse:
  """User not found error handler."""
  # log error
  message = {"error": "User not found"}
  return JSONResponse(message, status.HTTP_404_NOT_FOUND)


def get_redis(request: Request) -> Redis:
  """Return initialized instance of Redis client from lifespan."""
  return request.state.redis


class AppState(TypedDict):
  """Data structure to represent state of the main app."""

  redis: Redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Init Redis client with connection pool and migrate Redis OM models."""
  redis_connection_pool = ConnectionPool.from_url(REDIS_URL)
  redis_client = Redis(connection_pool=redis_connection_pool)
  await Migrator().run()
  yield AppState(redis=redis_client)
  await redis_connection_pool.disconnect()
  await redis_client.close()


app = FastAPI(lifespan=lifespan)
app.add_exception_handler(NotFoundError, user_not_found_error_handler)

# https://fastapi.tiangolo.com/tutorial/dependencies/#share-annotated-dependencies
UserID = Annotated[str, "user id in the database"]


@app.get("/health")
async def health(redis: Annotated[Redis, Depends(get_redis)]) -> dict[str, bool]:
  """Sample healthcheck endpoint."""
  ping = await redis.ping()
  return {"response": ping}


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
