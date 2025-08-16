import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import crud_router
from fastcrud.exceptions.http_exceptions import DuplicateValueException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import DateTime, String, func
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import (
  AsyncSession,
  async_sessionmaker,
  create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Settings
APP_VERSION = "0.0.1"
DEBUG = True
DATABASE_URL = "sqlite+aiosqlite:///./test.db"

# Constants
MIN_USER_NAME_LENGTH = 2
MAX_USER_NAME_LENGTH = 255
MAX_USER_EMAIL_LENGTH = 255
USER_ID_LENGTH = 36

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(
  engine,
  class_=AsyncSession,
  expire_on_commit=False,
)


def configure_logging() -> logging.Logger:
  """Configure app logging and return logger object."""
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
  )
  return logging.getLogger(__name__)


class Base(DeclarativeBase):
  """Base declarative database class."""


class User(Base):
  """Database model to represent a user."""

  __tablename__ = "users"
  id: Mapped[str] = mapped_column(
    String(USER_ID_LENGTH),
    primary_key=True,
    default=lambda: str(uuid4()),
  )
  name: Mapped[str] = mapped_column(
    String(MAX_USER_NAME_LENGTH),
    nullable=False,
  )
  email: Mapped[str] = mapped_column(
    String(MAX_USER_EMAIL_LENGTH),
    nullable=False,
    unique=True,
    index=True,
  )
  created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
  )
  updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
  )


class CreateUser(BaseModel):
  """Schema to create a user."""

  name: str = Field(
    description="Name of the user",
    min_length=MIN_USER_NAME_LENGTH,
    max_length=MAX_USER_NAME_LENGTH,
  )
  email: EmailStr = Field(description="Email of the user")


class UpdateUser(BaseModel):
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


async def get_session() -> AsyncIterator[AsyncSession]:
  """Yield a database session to be used as a dependency."""
  async with async_session() as session:
    yield session


def get_logger(request: Request) -> logging.Logger:
  """Return logger object, initialized in the lifespan."""
  return request.app.state.logger


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
  e: IntegrityError | DuplicateValueException,
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
  """Create the database objects on the application startup."""
  logger = configure_logging()
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)

  # Set application state
  app.state.logger = logger
  yield


app = FastAPI(
  title="Users Management App",
  description="CRUD Application to Manage Users",
  lifespan=lifespan,
  debug=DEBUG,
  version=APP_VERSION,
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


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "health"},
  )
