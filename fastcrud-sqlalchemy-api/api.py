import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict, cast
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import crud_router
from fastcrud.exceptions.http_exceptions import DuplicateValueException
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings
from sqlalchemy import DateTime, String, func
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
  title: str = "Users Management App"
  description: str = "CRUD Application to Manage Users"
  version: str = "0.0.1"
  debug: bool = True

  # Logging settings
  log_name: str = "api"
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
async_session = async_sessionmaker(engine, expire_on_commit=False)


def configure_logging(name: str, options: LoggingKwargs | None = None) -> "Logger":
  """Configure app logging and return logger object."""
  if options is not None:
    logging.basicConfig(**options)
  return logging.getLogger(name)


class Base(DeclarativeBase):
  """Base declarative database class."""

  type_annotation_map: ClassVar[dict[type, Any]] = {
    datetime: DateTime(timezone=True),
    str: String(255),
  }


class User(Base):
  """Model to represent a user in the database."""

  __tablename__ = "users"

  id: Mapped[str] = mapped_column(
    String(36),
    primary_key=True,
    default=lambda: str(uuid4()),
  )
  name: Mapped[str] = mapped_column(nullable=False)
  email: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
  created_at: Mapped[datetime] = mapped_column(server_default=func.now())
  updated_at: Mapped[datetime] = mapped_column(
    server_default=func.now(),
    onupdate=func.now(),
  )


class CreateUser(BaseModel):
  """Schema to create a user."""

  name: str
  email: EmailStr


class UpdateUser(BaseModel):
  """Schema to update a user."""

  name: str | None = None
  email: EmailStr | None = None


async def get_session() -> AsyncIterator[AsyncSession]:
  """Yield a database session to be used as a dependency."""
  async with async_session() as session:
    yield session


async def db_not_found_error_handler(
  _: Request,
  e: NoResultFound,  # noqa: ARG001
) -> JSONResponse:
  """Database. Not found error handler."""
  client_message = {"error": "User not found"}
  return JSONResponse(client_message, status.HTTP_404_NOT_FOUND)


async def db_integrity_error_handler(
  request: Request,
  e: IntegrityError | DuplicateValueException,
) -> JSONResponse:
  """Database. Integrity error handler."""
  logger = cast("Logger", request.app.state.logger)
  logger.warning("Database Integrity Error: %s", e)
  client_message = {"error": "User already exists"}
  return JSONResponse(client_message, status.HTTP_409_CONFLICT)


async def validation_error_handler(
  _: Request,
  e: RequestValidationError,
) -> JSONResponse:
  """Pydantic validation error handler."""
  client_message = {"error": e.errors()[0]["msg"]}
  return JSONResponse(client_message, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def unexpected_error_handler(
  request: Request,
  e: Exception,
) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  logger = cast("Logger", request.app.state.logger)
  logger.critical("Internal Server Error: %s", e)
  client_message = {"error": "Service is temporarily unavailable"}
  return JSONResponse(client_message, status.HTTP_500_INTERNAL_SERVER_ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Run database migrations and init application state."""
  logger = configure_logging(settings.log_name, settings.logging_kwargs)
  app.state.logger = logger
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

user_router = crud_router(
  session=get_session,
  model=User,
  create_schema=CreateUser,
  update_schema=UpdateUser,
  path="/users",
  tags=["users"],
)
app.include_router(user_router)


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT, tags=["meta"])
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )
