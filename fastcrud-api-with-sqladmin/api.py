import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar, Final, TypedDict
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import crud_router
from fastcrud.exceptions.http_exceptions import DuplicateValueException
from pydantic import EmailStr
from pydantic_settings import BaseSettings
from sqladmin import Admin, ModelView
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
  from logging import Logger

  from sqladmin._types import MODEL_ATTR

# Constants
MIN_USER_NAME_LENGTH: Final[int] = 2
MAX_USER_NAME_LENGTH: Final[int] = 255
USER_ID_LENGTH: Final[int] = 36


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
  title: str = "Users Management App"
  description: str = "CRUD Application to Manage Users"
  version: str = "0.0.1"
  debug: bool = False

  # Logging settings
  log_name: str = __name__
  log_level: int = logging.INFO
  log_format: str = "%(levelname)s - %(name)s - %(asctime)s - %(message)s"
  log_datefmt: str = "%Y-%m-%d %H:%M:%S"

  # Database settings
  database_url: str = "sqlite+aiosqlite:///./test.db"
  test_database_url: str = "sqlite+aiosqlite:///:memory:"

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
engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(
  engine,
  class_=AsyncSession,
  expire_on_commit=False,
)


@lru_cache
def configure_logging() -> "Logger":
  """Configure app logging and return logger object."""
  logging.basicConfig(**settings.logging_kwargs)
  return logging.getLogger(settings.log_name)


logger = configure_logging()


class Base(SQLModel):
  """Base database model."""

  id: str = Field(
    default_factory=lambda: str(uuid4()),
    min_length=USER_ID_LENGTH,
    max_length=USER_ID_LENGTH,
    primary_key=True,
  )
  created_at: datetime = Field(default_factory=func.now)
  updated_at: datetime = Field(
    default_factory=func.now,
    sa_column_kwargs={"onupdate": func.now},
  )


class CreateUser(SQLModel):
  """Schema to create a user."""

  name: str = Field(
    description="Name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH,
  )
  email: EmailStr = Field(
    description="Email of the user",
    unique=True,
    index=True,
  )


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


class UserAdminView(ModelView, model=User):
  """Admin view for the User model."""

  form_columns: ClassVar[Sequence["MODEL_ATTR"]] = ["name", "email"]
  column_list: ClassVar[str | Sequence["MODEL_ATTR"]] = [
    "name",
    "email",
    "created_at",
    "updated_at",
  ]
  column_searchable_list: ClassVar[Sequence["MODEL_ATTR"]] = ["name"]
  column_sortable_list: ClassVar[Sequence["MODEL_ATTR"]] = [
    "name",
    "created_at",
    "updated_at",
  ]


async def get_session() -> AsyncIterator[AsyncSession]:
  """Yield a database session to be used as a dependency."""
  async with async_session() as session:
    yield session


async def db_not_found_error_handler(
  _: Request,
  e: NoResultFound,
) -> JSONResponse:
  """Database. Not found error handler."""
  logger.info("Database Not Found Error: %s", e)
  client_message = {"error": "User not found"}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


async def db_integrity_error_handler(
  _: Request,
  e: IntegrityError | DuplicateValueException,
) -> JSONResponse:
  """Database. Integrity error handler."""
  logger.warning("Database Integrity Error: %s", e)
  client_message = {"error": "User already exists"}
  return JSONResponse(client_message, status.HTTP_409_CONFLICT)


async def validation_error_handler(
  _: Request,
  e: RequestValidationError,
) -> JSONResponse:
  """Pydantic validation error handler."""
  logger.warning("Data Validation Error: %s", e)
  client_message = {"error": e.errors()[0]["msg"]}
  return JSONResponse(client_message, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def unexpected_error_handler(
  _: Request,
  e: Exception,
) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  logger.critical("Internal Server Error: %s", e)
  client_message = {"error": "Service is temporarily unavailable"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
  """Run database migrations and init application state."""
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  yield
  await engine.dispose()


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={
    NoResultFound: db_not_found_error_handler,
    IntegrityError: db_integrity_error_handler,
    DuplicateValueException: db_integrity_error_handler,
    RequestValidationError: validation_error_handler,
    Exception: unexpected_error_handler,
  },
)
admin = Admin(app, engine)
admin.add_view(UserAdminView)

user_router = crud_router(
  session=get_session,
  model=User,
  create_schema=CreateUser,
  update_schema=UpdateUser,
  path="/users",
  tags=["users"],
)
app.include_router(user_router)


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )
