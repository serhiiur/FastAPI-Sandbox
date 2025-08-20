import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from typing import (
  TYPE_CHECKING,
  Annotated,
  Any,
  Final,
  Literal,
  TypedDict,
  cast,
)
from uuid import UUID, uuid4

from fastapi import (
  APIRouter,
  Depends,
  FastAPI,
  Path,
  Request,
  Response,
  status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastcrud import FastCRUD
from pydantic import BaseModel, EmailStr
from pydantic_settings import BaseSettings
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
      level=settings.log_level,
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


def configure_logging() -> "Logger":
  """Configure app logging and return logger object."""
  logging.basicConfig(**settings.logging_kwargs)
  return logging.getLogger(settings.log_name)


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
    default=None,
    description="Order to sort records by",
  )


class UsersResponse(BaseModel):
  """Schema used to display multiple users from the database."""

  data: list[User] = Field(description="List of users based on the provided filters")
  total_count: int = Field(description="Total users in the database")


async def get_session() -> AsyncIterator[AsyncSession]:
  """Yield a database session to be used as a dependency."""
  async with async_session() as session:
    yield session


async def db_not_found_error_handler(
  request: Request,
  e: NoResultFound,
) -> JSONResponse:
  """Database. Not found error handler."""
  logger = cast("Logger", request.app.state.logger)
  logger.info("Database Not Found Error: %s", e)
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


async def validation_error_handler(
  request: Request,
  e: RequestValidationError,
) -> JSONResponse:
  """Pydantic validation error handler."""
  logger = cast("Logger", request.app.state.logger)
  logger.warning("Data Validation Error: %s", e)
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
async def lifespan(app: FastAPI) -> AsyncIterator:
  """Run database migrations and init application state."""
  logger = configure_logging()
  # Create database objects on the application startup
  async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
  # Set application state
  app.state.logger = logger
  yield
  await engine.dispose()


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={
    NoResultFound: db_not_found_error_handler,
    IntegrityError: db_integrity_error_handler,
    RequestValidationError: validation_error_handler,
    Exception: unexpected_error_handler,
  },
)

router = APIRouter(prefix="/users", tags=["users"])
crud = FastCRUD(User)

# https://fastapi.tiangolo.com/tutorial/dependencies/#share-annotated-dependencies
DbSession = Annotated[AsyncSession, Depends(get_session)]

UserID = Annotated[UUID, Path(alias="userId")]


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )


@router.get(
  "/{userId}",  # noqa: FAST003
  response_model=User,
)
async def get_user(user_id: UserID, db: DbSession) -> dict[str, Any]:
  """Get information about user from the database."""
  if user := await crud.get(db, id=str(user_id)):
    return user
  raise NoResultFound


@router.get("", response_model=UsersResponse)
async def get_users(
  filters: Annotated[UserSelectFilters, Depends()],
  db: DbSession,
) -> dict[str, list[dict[str, Any]] | int]:
  """Get information about users from the database."""
  return await crud.get_multi(db, **filters.model_dump())


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(user: CreateUser, db: DbSession) -> User:
  """Add a new user to the database."""
  return await crud.create(db, user)


@router.delete(
  "/{userId}",  # noqa: FAST003
  status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(user_id: UserID, db: DbSession) -> None:
  """Delete a user from the database."""
  return await crud.delete(db, id=str(user_id))


@router.patch(
  "/{userId}",  # noqa: FAST003
)
async def update_user(
  user_id: UserID,
  user: UpdateUser,
  db: DbSession,
) -> User:
  """Update existing user in the database."""
  res = await crud.update(
    db,
    object=user.model_dump(exclude_defaults=True),
    id=str(user_id),
    schema_to_select=User,
    return_as_model=True,
  )
  return cast("User", res)


app.include_router(router)
