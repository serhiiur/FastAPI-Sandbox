from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Annotated, AsyncIterator, Callable, Literal, TypedDict
from uuid import uuid4, UUID

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache
from fastcrud import FastCRUD
from pydantic import BaseModel, EmailStr
from redis.asyncio import ConnectionPool, Redis
from sqlmodel import SQLModel, Field
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AS
from sqlalchemy.orm import sessionmaker


# Settings
APP_VERSION = "0.0.1"
DEBUG = True
CACHE_PREFIX = "fastapi-cache"
CACHE_KEY_EXPIRATION_TIME = 60 # seconds
DATABASE_URL = "sqlite+aiosqlite:///./test.db"
MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255
REDIS_URL = "redis://localhost:6379/0"

# Database Objects
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AS, expire_on_commit=False)

# lambda function to return current datetime
dt_now = lambda: datetime.now(timezone.utc)

# lambda function to get redis key representing a user
get_user_cache_key = lambda user_id: f"{CACHE_PREFIX}:user:{user_id}"


class Base(SQLModel):
  """Base database model"""
  id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
  created_at: datetime = Field(default_factory=dt_now)
  updated_at: datetime = Field(
    default_factory=dt_now,
    sa_column_kwargs={"onupdate": dt_now}
  )


class CreateUser(SQLModel):
  """Schema to create a user"""
  name: str = Field(
    description="Name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH

  )
  email: EmailStr = Field(
    description="Email of the user",
    unique=True,
    index=True
  )


class User(Base, CreateUser, table=True):
  """Database model to represent a user"""


class UpdateUser(SQLModel):
  """Schema to update a user"""
  name: str | None = Field(
    default=None,
    description="New name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH
  )
  email: EmailStr | None = Field(
    default=None,
    description="New email of the user",
  )


class UserSelectFilters(BaseModel):
  """Schema used to select users frm the database using filters"""
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
    default=None,
    description="Order to sort records by"
  )


responses = {
  404: {
    "description": "User not found in the database",
    "content": {
      "application/json": {
        "example": {
          "error": "User not found"
        }
      }
    }
  },
  409: {
    "description": "User already exists in the database",
    "content": {
      "application/json": {
        "example": {
          "error": "User already exists"
        }
      }
    }
  },
  422: {
    "description": "Data validation error",
    "content": {
      "application/json": {
        "example": {
          "error": "Value is not a valid email address"
        }
      }
    }
  },
}

RawUserResponse = dict[str, Any]


class UsersResponse(BaseModel):
  """Schema used to display multiple users from the database"""
  data: list[User] = Field(
    description="List of users based on the provided filters"
  )
  total_count: int = Field(
    description="Total users in the database"
  )


def users_cache_key_builder(
  _: Callable[..., Any],
  namespace: str = "",
  request: Request | None = None,
  *args,
  **kwargs,
) -> str:
  """
  Function to generate a redis key used by FastAPI-Cache
  extension to cache results of the API endpoints.

  Example of keys:
    - specific user: fastapi-cache:user:ad7485b4-0275-411a-8b06-b7c84bc2cf99
    - regular key:   fastapi-cache:get:/users:[('limit', '10'), ('offset', '0')]
  """
  if user := request.path_params.get("id"):
    return get_user_cache_key(user)
  key_params = ":".join([
    request.method.lower(),
    request.url.path,
    repr(sorted(request.query_params.items())),

  ])
  return f"{CACHE_PREFIX}:{key_params}"


async def get_redis(request: Request) -> Redis:
  """Return Redis client initialized in the lifespan"""
  return getattr(request.state, "redis")


async def invalidate_cache(
  request: Request,
  redis: Annotated[Redis, Depends(get_redis)]
) -> None:
  """Invalidate a key in redis representing a user."""
  if user := request.path_params.get("id"):
    user_cache_key = get_user_cache_key(user)
    await redis.delete(user_cache_key)


async def get_session() -> AsyncIterator[AS]:
  """Yield a database session to be used as a dependency."""
  async with async_session() as session:
    yield session


async def db_not_found_error_handler(
  _: Request,
  e: NoResultFound
) -> JSONResponse:
  """Database. Not found error handler"""
  msg = {"error": str(e)}
  return JSONResponse(msg, status.HTTP_404_NOT_FOUND)


async def db_integrity_error_handler(
  _: Request,
  e: IntegrityError
) -> JSONResponse:
  """Database. Integrity error handler"""
  msg = {"error": "User already exists"}
  return JSONResponse(msg, status.HTTP_409_CONFLICT)


async def validation_error_handler(
  _: Request,
  e: RequestValidationError
) -> JSONResponse:
  """Pydantic validation error handler"""
  msg = {"error": e.errors()[0]["msg"]}
  return JSONResponse(msg, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def unexpected_error_handler(
  _: Request,
  e: Exception
) -> JSONResponse:
  """Error handler for all uncaught exceptions"""
  msg = {"error": "Internal server error. Try again later"}
  return JSONResponse(msg, status.HTTP_500_INTERNAL_SERVER_ERROR)


class AppState(TypedDict):
  """Data structure to represent state of the main app"""
  redis: Redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """
  Initialize objects on the application startup and
  release them on the application shutdown.

  The following objects are initialized and released:
    - client for Redis
    - database objects based on their schema

  Additionally FastAPI cache objects get initialized on the
  application startup.
  """
  # Init redis client + connection pool
  redis_connection_pool = ConnectionPool.from_url(REDIS_URL)
  redis_client = Redis(connection_pool=redis_connection_pool)
  # Init fastapi cache based on redis
  FastAPICache.init(
    RedisBackend(redis_client),
    key_builder=users_cache_key_builder
  )
  # Create database objects on startup
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield AppState(redis=redis_client)
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
)
app.add_exception_handler(NoResultFound, db_not_found_error_handler)
app.add_exception_handler(IntegrityError, db_integrity_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)

# Init FastCRUD object
user_crud = FastCRUD(User)


@app.get(
  "/health",
  description="Simple health-check endpoint",
  tags=["meta"],
  responses={
    200: {
      "description": "Healthcheck",
      "content": {
        "application/json": {
          "example": {
            "response": "ok"
          }
        }
      }
    }
  }
)
async def health() -> dict[str, str]:
  return {"response": "ok"}


@app.get(
  "/users/{id}",
  description="Get information about user from the database",
  response_model=User,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
@cache(expire=CACHE_KEY_EXPIRATION_TIME)
async def get_user(
  id: UUID,
  db: Annotated[AS, Depends(get_session)]
) -> RawUserResponse:
  if user := await user_crud.get(db, id=str(id)):
    return user
  raise NoResultFound("User not found")


@app.get(
  "/users",
  description="Get information about users from the database",
  response_model=UsersResponse,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
@cache(expire=CACHE_KEY_EXPIRATION_TIME)
async def get_users(
  filters: Annotated[UserSelectFilters, Depends()],
  db: Annotated[AS, Depends(get_session)]
) -> dict[str, list[RawUserResponse] | int]:
  return await user_crud.get_multi(db, **filters.model_dump())


@app.post(
  "/users",
  description="Add a new user to the database",
  response_model=User,
  status_code=status.HTTP_201_CREATED,
  responses={409: responses[409], 422: responses[422]},
  tags=["users"],
)
async def create_user(
  user: CreateUser,
  db: Annotated[AS, Depends(get_session)]
) -> User:
  return await user_crud.create(db, user)


@app.delete(
  "/users/{id}",
  description="Delete a user from the database",
  status_code=status.HTTP_204_NO_CONTENT,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
  dependencies=[Depends(invalidate_cache)]
)
async def delete_user(
  id: UUID,
  db: Annotated[AS, Depends(get_session)]
) -> None:
  return await user_crud.delete(db, id=str(id))


@app.patch(
  "/users/{id}",
  description="Update existing user in the database",
  response_model=User,
  responses={**responses},
  tags=["users"],
  dependencies=[Depends(invalidate_cache)]
)
async def update_user(
  id: UUID,
  user: UpdateUser,
  db: Annotated[AS, Depends(get_session)]
) -> User:
  return await user_crud.update(
    db,
    object=user.model_dump(exclude_defaults=True),
    id=str(id),
    schema_to_select=User,
    return_as_model=True,
  )
