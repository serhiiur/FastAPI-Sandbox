import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache
from fastcrud import FastCRUD
from pydantic import BaseModel, EmailStr
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)
from sqlmodel import Field, SQLModel

# Settings
APP_VERSION = "0.0.1"
DEBUG = True
CACHE_PREFIX = "fastapi-cache"
CACHE_EXPIRE_SECONDS = 60
DATABASE_URL = "sqlite+aiosqlite:///./test.db"
MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255
REDIS_CONNECTION_URL = "redis://localhost:6379/0"

# Database Objects
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def configure_logging() -> logging.Logger:
  """Configure app logging and return logger object."""
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
  )
  return logging.getLogger(__name__)


def get_current_datetime() -> datetime:
  """Return current UTC datetime object."""
  return datetime.now(UTC)


def get_user_cache_key(user_id: str) -> str:
  """Return a key representing a user in the cache."""
  return f"{CACHE_PREFIX}:user:{user_id}"


class Base(SQLModel):
  """Base database model."""

  id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
  created_at: datetime = Field(default_factory=get_current_datetime)
  updated_at: datetime = Field(
    default_factory=get_current_datetime,
    sa_column_kwargs={"onupdate": get_current_datetime},
  )


class CreateUser(SQLModel):
  """Schema to create a user."""

  name: str = Field(
    description="Name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH,
  )
  email: EmailStr = Field(description="Email of the user", unique=True, index=True)


class User(Base, CreateUser, table=True):
  """Database model to represent a user."""


class UpdateUser(SQLModel):
  """Schema to update a user."""

  name: str | None = Field(
    default=None,
    description="New name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH,
  )
  email: EmailStr | None = Field(
    default=None,
    description="New email of the user",
  )


class UserSelectFilters(BaseModel):
  """Schema used to select users frm the database using filters."""

  limit: int = Field(
    default=10,
    description="Total number of records to select",
    gt=0,
  )
  offset: int = Field(
    default=0,
    description="Index to start selecting records from",
    ge=0,
  )
  sort_columns: Literal["name", "created_at", "updated_at"] | None = Field(
    default=None,
    description="Field to sort records by",
  )
  sort_orders: Literal["asc", "desc"] | None = Field(
    default=None, description="Order to sort records by"
  )


responses = {
  404: {
    "description": "User not found in the database",
    "content": {"application/json": {"example": {"error": "User not found"}}},
  },
  409: {
    "description": "User already exists in the database",
    "content": {"application/json": {"example": {"error": "User already exists"}}},
  },
  422: {
    "description": "Data validation error",
    "content": {
      "application/json": {"example": {"error": "Value is not a valid email address"}}
    },
  },
}

RawUserResponse = dict[str, Any]


class UsersResponse(BaseModel):
  """Schema used to display multiple users from the database."""

  data: list[User] = Field(description="List of users based on the provided filters")
  total_count: int = Field(description="Total users in the database")


def users_cache_key_builder(
  _: Callable[..., Any],
  namespace: str,  # noqa: ARG001
  request: Request,
  *args: tuple[Any, ...],  # noqa: ARG001
  **kwargs: dict[str, Any],  # noqa: ARG001
) -> str:
  """Generate a redis key used by FastAPI-Cache extension.

    The key is used to cache results of the API endpoints.

  Example of keys:
    - specific user: fastapi-cache:user:ad7485b4-0275-411a-8b06-b7c84bc2cf99
    - regular key:   fastapi-cache:get:/users:[('limit', '10'), ('offset', '0')]
  """
  if user := request.path_params.get("user_id"):
    return get_user_cache_key(user)
  key_params = ":".join(
    [
      request.method.lower(),
      request.url.path,
      repr(sorted(request.query_params.items())),
    ]
  )
  return f"{CACHE_PREFIX}:{key_params}"


def get_logger(request: Request) -> logging.Logger:
  """Return logger object, initialized in the lifespan."""
  return request.app.state.logger


def get_redis(request: Request) -> Redis:
  """Return Redis client, initialized in the lifespan."""
  return request.app.state.redis


async def invalidate_cache(
  request: Request,
  redis: Annotated[Redis, Depends(get_redis)],
) -> None:
  """Invalidate a key in redis representing a user."""
  if user_id := request.path_params.get("user_id"):
    user_cache_key = get_user_cache_key(user_id)
    await redis.delete(user_cache_key)


async def get_session() -> AsyncIterator[AsyncSession]:
  """Yield a database session to be used as a dependency."""
  async with async_session() as session:
    yield session


async def db_not_found_error_handler(
  request: Request,
  e: NoResultFound,
) -> JSONResponse:
  """Database. Not found error handler."""
  logger = get_logger(request)
  logger.info("Database Not Found Error: %s", e)
  client_message = {"error": "User not found"}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


async def db_integrity_error_handler(
  request: Request,
  e: IntegrityError,
) -> JSONResponse:
  """Database. Integrity error handler."""
  logger = get_logger(request)
  logger.warning("Database Integrity Error: %s", e)
  client_message = {"error": "User already exists"}
  return JSONResponse(client_message, status.HTTP_409_CONFLICT)


async def validation_error_handler(
  request: Request,
  e: RequestValidationError,
) -> JSONResponse:
  """Pydantic validation error handler."""
  logger = get_logger(request)
  logger.warning("Data Validation Error: %s", e)
  client_message = {"error": e.errors()[0]["msg"]}
  return JSONResponse(client_message, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def unexpected_error_handler(request: Request, e: Exception) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  logger = get_logger(request)
  logger.critical("Internal Server Error: %s", e)
  client_message = {"error": "Internal server error. Try again later"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
  """Init and release app state objects on app startup and shutdown.

  The following objects are initialized and released:
    - client for Redis
    - database objects based on their schema

  Additionally FastAPI cache objects get initialized on the
  application startup.
  """
  logger = configure_logging()
  # Init redis client + connection pool
  redis_connection_pool = ConnectionPool.from_url(REDIS_CONNECTION_URL)
  redis_client = Redis(connection_pool=redis_connection_pool)
  # Init fastapi cache based on redis
  FastAPICache.init(
    RedisBackend(redis_client),
    expire=CACHE_EXPIRE_SECONDS,
    key_builder=users_cache_key_builder,
  )
  # Create database objects on startup
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)

  # Set application state
  app.state.logger = logger
  app.state.redis = redis_client

  yield

  # Disconnect connection pool for redis and close the client
  await redis_client.connection_pool.disconnect()
  await redis_client.close()
  # Dispose database engine
  await engine.dispose()


app = FastAPI(
  title="Users Management App",
  description="CRUD Application to Manage Users",
  lifespan=lifespan,
  debug=DEBUG,
  version=APP_VERSION,
  exception_handlers={
    NoResultFound: db_not_found_error_handler,
    IntegrityError: db_integrity_error_handler,
    RequestValidationError: validation_error_handler,
    Exception: unexpected_error_handler,
  },
)
# app.add_exception_handler(NoResultFound, db_not_found_error_handler)
# app.add_exception_handler(IntegrityError, db_integrity_error_handler)
# app.add_exception_handler(RequestValidationError, validation_error_handler)
# app.add_exception_handler(Exception, unexpected_error_handler)

# Init FastCRUD object
user_crud = FastCRUD(User)


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "health"},
  )


@app.get(
  "/users/{user_id}",
  response_model=User,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
@cache()
async def get_user(
  user_id: UUID,
  db: Annotated[AsyncSession, Depends(get_session)],
) -> RawUserResponse:
  """Get information about user from the database."""
  if user := await user_crud.get(db, id=str(user_id)):
    return user
  raise NoResultFound


@app.get(
  "/users",
  response_model=UsersResponse,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
@cache()
async def get_users(
  filters: Annotated[UserSelectFilters, Depends()],
  db: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, list[RawUserResponse] | int]:
  """Get information about users from the database."""
  return await user_crud.get_multi(db, **filters.model_dump())


@app.post(
  "/users",
  status_code=status.HTTP_201_CREATED,
  responses={409: responses[409], 422: responses[422]},
  tags=["users"],
)
async def create_user(
  user: CreateUser,
  db: Annotated[AsyncSession, Depends(get_session)],
) -> User:
  """Add a new user to the database."""
  return await user_crud.create(db, user)


@app.delete(
  "/users/{user_id}",
  status_code=status.HTTP_204_NO_CONTENT,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
  dependencies=[Depends(invalidate_cache)],
)
async def delete_user(
  user_id: UUID,
  db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
  """Delete a user from the database."""
  return await user_crud.delete(db, id=str(user_id))


@app.patch(
  "/users/{user_id}",
  responses=dict(responses.items()),
  tags=["users"],
  dependencies=[Depends(invalidate_cache)],
)
async def update_user(
  user_id: UUID,
  user: UpdateUser,
  db: Annotated[AsyncSession, Depends(get_session)],
) -> User:
  """Update existing user in the database."""
  res = await user_crud.update(
    db,
    object=user.model_dump(exclude_defaults=True),
    id=str(user_id),
    schema_to_select=User,
    return_as_model=True,
  )
  return cast("User", res)
