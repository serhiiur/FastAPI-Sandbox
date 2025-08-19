import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Final, TypedDict

from aredis_om import Field, JsonModel, Migrator
from aredis_om.model.model import NotFoundError
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
  from logging import Logger

# Constants
MIN_USER_NAME_LENGTH: Final[int] = 2
MAX_USER_NAME_LENGTH: Final[int] = 255


class FastAPIKwargs(TypedDict):
  """Kwargs for FastAPI app."""

  title: str
  description: str
  version: str
  debug: bool


class LoggingKwargs(TypedDict):
  """Kwargs for logger config."""

  level: int
  format: str


class Settings(BaseSettings):
  """API settings."""

  # FastAPI settings
  title: str = "Users Management API"
  description: str = "CRUD API to manage users in the Redis-based database"
  version: str = "0.0.1"
  debug: bool = False

  # Logging settings
  log_name: str = __name__
  log_level: int = logging.INFO
  log_format: str = "%(levelname)s - %(name)s - %(asctime)s - %(message)s"

  # Other settings
  redis_url: str = "redis://localhost:6379/0"

  @property
  def fastapi_kwargs(self) -> FastAPIKwargs:
    """Kwargs for FastAPI app."""
    return FastAPIKwargs(
      title=self.title,
      description=self.description,
      version=self.version,
      debug=self.debug,
    )

  @property
  def logging_kwargs(self) -> LoggingKwargs:
    """Kwargs for logger config."""
    return LoggingKwargs(
      level=settings.log_level,
      format=self.log_format,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


def configure_logging() -> "Logger":
  """Configure app logging and return logger object."""
  logging.basicConfig(**settings.logging_kwargs)
  return logging.getLogger(settings.log_name)


class CreateUser(BaseModel):
  """Schema to create a new user."""

  name: str = Field(
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH,
    description="Name of the user",
  )
  email: EmailStr = Field(
    index=True,
    description="Email of the user",
  )


class UpdateUser(BaseModel):
  """Schema to update an existing user."""

  name: str | None = Field(
    None,
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH,
    description="Name of the user",
  )
  email: EmailStr | None = Field(None, description="Email of the user")


class User(CreateUser, JsonModel):
  """Schema to represent info about user."""

  created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "pk": "01K30VC72BTFYCGBRM8XTSFJYP",
        "name": "Joe Doe",
        "email": "jd@example.com",
        "created_at": "2024-02-19T09:43:14.252158Z",
      }
    }
  )


def get_logger(request: Request) -> "Logger":
  """Return logger object, initialized in the lifespan."""
  return request.app.state.logger


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
  client_message = {"error": "Service is temporarily unavailable"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
  """Run Redis OM migrations and init application state."""
  logger = configure_logging()
  # Run migrations for running queries
  await Migrator().run()
  # Set application state
  app.state.logger = logger
  yield


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={
    NotFoundError: user_not_found_error_handler,
    Exception: unexpected_error_handler,
  },
)

# https://fastapi.tiangolo.com/tutorial/dependencies/#share-annotated-dependencies
UserID = Annotated[str, "User ID in the database"]

responses = {
  404: {
    "description": "User not found in the database",
    "content": {"application/json": {"example": {"error": "User not found"}}},
  },
  422: {
    "description": "Data validation error",
    "content": {
      "application/json": {"example": {"error": "Value is not a valid email address"}}
    },
  },
}


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health(
  logger: Annotated["Logger", Depends(get_logger)],
) -> Response:
  """Health-check endpoint."""
  logger.info("API healthcheck - OK")
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )


@app.get(
  "/users/{pk}",
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
async def get_user(pk: UserID) -> User:
  """Get information about user from the database."""
  return await User.get(pk)


@app.get(
  "/users",
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
async def get_users(offset: int = 0, limit: int = 10) -> list[User]:
  """Get information about users from the database."""
  return await User.find().sort_by("-created_at").page(offset, limit)


@app.post(
  "/users",
  status_code=status.HTTP_201_CREATED,
  responses={422: responses[422]},
  tags=["users"],
)
async def add_user(user: CreateUser) -> User:
  """Add a new user to the database."""
  return await User.model_validate(user).save()


@app.delete(
  "/users/{pk}",
  status_code=status.HTTP_204_NO_CONTENT,
  responses={404: responses[404], 422: responses[422]},
  tags=["users"],
)
async def delete_user(pk: UserID) -> None:
  """Delete a user from the database."""
  await User.delete(pk)


@app.patch(
  "/users/{pk}",
  responses=dict(responses.items()),
  tags=["users"],
)
async def update_user(pk: UserID, user: UpdateUser) -> User:
  """Update existing user in the database."""
  db_user = await User.get(pk)
  await db_user.update(**user.model_dump(exclude_defaults=True))
  return db_user
