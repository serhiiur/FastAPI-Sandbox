import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, ClassVar, Self, TypedDict, cast

from fastapi import APIRouter, FastAPI, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, model_validator
from pydantic_settings import BaseSettings
from tortoise import fields, models
from tortoise.contrib.fastapi import RegisterTortoise
from tortoise.contrib.pydantic import PydanticModel, pydantic_model_creator
from tortoise.exceptions import DoesNotExist, IntegrityError

if TYPE_CHECKING:
  from logging import Logger


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
  datefmt: str


class Settings(BaseSettings):
  """API settings."""

  # FastAPI settings
  title: str = "Users management API"
  description: str = "CRUD Application to Manage Users"
  version: str = "0.0.1"
  debug: bool = True

  # Logging settings
  log_name: str = "api"
  log_level: int = logging.INFO
  log_format: str = "%(levelname)s - %(name)s - %(asctime)s - %(message)s"
  log_datefmt: str = "%Y-%m-%d %H:%M:%S"

  # Database settings
  database_url: str = "sqlite://./test.db"
  test_database_url: str = "sqlite://:memory:"

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
      level=self.log_level,
      format=self.log_format,
      datefmt=self.log_datefmt,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


def configure_logging(name: str, options: LoggingKwargs | None = None) -> "Logger":
  """Configure app logging and return logger object."""
  if options is not None:
    logging.basicConfig(**options)
  return logging.getLogger(name)


class User(models.Model):
  """Model to represent a user in the database."""

  id = fields.IntField(primary_key=True)
  username = fields.CharField(max_length=255, unique=True, db_index=True)
  email = fields.CharField(max_length=255, unique=True, db_index=True)
  first_name = fields.CharField(max_length=255)
  second_name = fields.CharField(max_length=255)
  password = fields.CharField(max_length=255)
  created_at = fields.DatetimeField(auto_now_add=True)
  updated_at = fields.DatetimeField(auto_now=True)

  def full_name(self) -> str:
    """Return full name of the user by combining first and second name."""
    return f"{self.first_name} {self.second_name}"

  class PydanticMeta:
    """Configuration of the model to be represented as Pydantic schema."""

    computed: ClassVar[list[str]] = ["full_name"]
    exclude: ClassVar[list[str]] = ["password"]


if TYPE_CHECKING:

  class UserInDB(User, PydanticModel):  # type:ignore[misc]
    """Pydantic schema to represent info about user from the database."""
else:
  UserInDB = pydantic_model_creator(User, name="User")


class CreateUser(BaseModel):
  """Schema to create a user."""

  username: str
  email: EmailStr
  first_name: str
  second_name: str
  password: str


class UpdateUser(BaseModel):
  """Schema to update a user."""

  username: str | None = None
  email: EmailStr | None = None
  first_name: str | None = None
  second_name: str | None = None
  password: str | None = None


class Users(BaseModel):
  """Schema to represent a list of users from the database."""

  data: list[UserInDB]
  count: int = 0

  @model_validator(mode="after")
  def count_data(self) -> Self:
    """Set self.count attr based on length of self.data attr."""
    self.count = len(self.data)
    return self


async def validation_error_handler(
  _: Request,
  e: RequestValidationError,
) -> JSONResponse:
  """Pydantic validation error handler."""
  client_message = {"error": e.errors()[0]["msg"]}
  return JSONResponse(client_message, status.HTTP_422_UNPROCESSABLE_CONTENT)


async def unexpected_error_handler(
  request: Request,
  e: Exception,
) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  logger = cast("Logger", request.app.state.logger)
  logger.critical("Internal Server Error: %s", e)
  client_message = {"error": "Service is temporarily unavailable"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


async def db_not_found_error_handler(
  _: Request,
  e: DoesNotExist,  # noqa: ARG001
) -> JSONResponse:
  """Database. Not found error handler."""
  client_message = {"error": "User not found"}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


async def db_integrity_error_handler(
  request: Request,
  e: IntegrityError,
) -> JSONResponse:
  """Database. Integrity error handler."""
  logger = cast("Logger", request.app.state.logger)
  logger.warning("Database Integrity Error: %s", e)
  client_message = {"error": "User already exists"}
  return JSONResponse(client_message, status.HTTP_409_CONFLICT)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Run database migrations and init application state."""
  database_url = getattr(app.state, "database_url", settings.database_url)
  if not hasattr(app.state, "logger"):
    app.state.logger = configure_logging(settings.log_name, settings.logging_kwargs)
  async with RegisterTortoise(
    app=app,
    db_url=database_url,
    generate_schemas=True,
    modules={"models": ["api"]},
  ) as _:
    yield


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={
    RequestValidationError: validation_error_handler,
    DoesNotExist: db_not_found_error_handler,
    IntegrityError: db_integrity_error_handler,
    Exception: unexpected_error_handler,
  },
)
router = APIRouter(prefix="/users", tags=["users"])


@app.get(
  "/health",
  status_code=status.HTTP_204_NO_CONTENT,
  tags=["meta"],
)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )


@router.get("/{user_id}")
async def get_user(user_id: int) -> UserInDB:
  """Get info about user from the database."""
  user = User.get(id=user_id)
  return await UserInDB.from_queryset_single(user)


@router.get("")
async def get_users(
  limit: Annotated[int, Query(gt=0, le=100)] = 10,
  offset: Annotated[int, Query(ge=0)] = 0,
) -> Users:
  """Get info about users from the database."""
  queryset = User.all().limit(limit).offset(offset)
  users = await UserInDB.from_queryset(queryset)
  return Users(data=users)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(user: CreateUser) -> UserInDB:
  """Add a new user to the database."""
  db_user = await User.create(**user.model_dump())
  return await UserInDB.from_tortoise_orm(db_user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int) -> None:
  """Delete a user from the database."""
  res = await User.filter(id=user_id).delete()
  if not res:
    raise DoesNotExist(model=f"User {user_id} not found")


@router.patch(
  "/{user_id}",
  description="Partially update info about user",
)
@router.put(
  "/{user_id}",
  description="Fully update info about user",
)
async def update_user(user_id: int, user: UpdateUser) -> UserInDB:
  """Update existing user in the database."""
  await User.filter(id=user_id).update(**user.model_dump(exclude_defaults=True))
  return await UserInDB.from_queryset_single(User.get(id=user_id))


app.include_router(router)
