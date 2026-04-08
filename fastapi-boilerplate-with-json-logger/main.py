import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, Callable, TypeAlias, TypedDict, cast

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from uvicorn.config import LoopFactoryType


class FastApiKwargs(TypedDict):
  """Data structure to specify kwargs for FastAPI application."""

  title: str
  description: str
  debug: bool
  version: str
  docs_url: str
  redoc_url: str
  openapi_url: str


class UvicornKwargs(TypedDict):
  """Data structure to specify kwargs for Uvicorn."""

  log_level: int
  log_config: dict[str, Any]
  loop: LoopFactoryType
  reload: bool


class Settings(BaseSettings):
  """Application settings."""

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

  # FastAPI settings
  title: str = "Boilerplate API"
  description: str = "Starter FastAPI application."
  debug: bool = False
  version: str = "0.0.1"
  docs_url: str = "/api/schema/docs"
  redoc_url: str = "/api/schema/redoc"
  openapi_url: str = "/api/schema/openapi.json"

  # Logging settings
  log_format: str = (
    "%(levelname)s %(asctime)s %(name)s %(message)s %(pathname)s %(lineno)d"
  )
  log_datefmt: str = "%Y-%m-%d %H:%M:%S"

  # Uvicorn settings
  uvicorn_loop: LoopFactoryType = "uvloop"

  @property
  def fastapi_kwargs(self) -> FastApiKwargs:
    """Kwargs for FastAPI application."""
    return FastApiKwargs(
      title=self.title,
      description=self.description,
      debug=self.debug,
      version=self.version,
      docs_url=self.docs_url,
      redoc_url=self.redoc_url,
      openapi_url=self.openapi_url,
    )

  @property
  def uvicorn_kwargs(self) -> UvicornKwargs:
    """Kwargs for Uvicorn"""
    log_config: dict[str, Any] = {
      "version": 1,
      "disable_existing_loggers": False,
      "formatters": {
        "json": {
          "()": "pythonjsonlogger.json.JsonFormatter",
          "format": self.log_format,
          "datefmt": self.log_datefmt,
        }
      },
      "handlers": {
        "default": {
          "class": "logging.StreamHandler",
          "formatter": "json",
          "stream": "ext://sys.stdout",
        }
      },
      "loggers": {
        "uvicorn.error": {
          "handlers": ["default"],
          "level": logging.WARNING,
          "propagate": False,
        },
        "uvicorn.access": {
          "handlers": ["default"],
          "level": logging.INFO,
          "propagate": False,
        },
      },
    }
    return UvicornKwargs(
      log_level=logging.INFO if self.debug else logging.WARNING,
      log_config=log_config,
      loop=self.uvicorn_loop,
      reload=self.debug,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


async def get_logger(request: Request) -> logging.Logger:
  """Return logger object initialized in the lifespan."""
  return cast("logging.Logger", request.state.logger)


# type alias to specify the dependency to get the logger object
Logger: TypeAlias = Annotated["logging.Logger", Depends(get_logger)]


async def internal_server_error_handler(
  request: Request,
  _exc: Exception,
) -> JSONResponse:
  """Error handler for all uncaught exceptions."""
  return JSONResponse(
    content={
      "detail": "service is temporarily unavailable",
      "path": request.url.path,
      "timestamp": datetime.now(UTC).isoformat(),
    },
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
  )


# eError handlers mapping to be registered in the main FastAPI app
error_handlers: dict[
  int | type[Exception],
  Callable[[Request, Any], Coroutine[Any, Any, Response]],
] = {
  Exception: internal_server_error_handler,
}


class ApiVersion(BaseModel):
  """Response schema to provide info about API version."""

  version: str = Field(
    default=settings.fastapi_kwargs["version"],
    description="Version of the API",
    examples=[settings.fastapi_kwargs["version"]],
  )


class ApiHealth(BaseModel):
  """Response schema to provide info about API health status."""

  status: str = Field(
    default="ok",
    description="Health status of the API",
    examples=["ok"],
  )


class AppState(TypedDict):
  """Data structure to represent state of the main application."""

  logger: "logging.Logger"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
  """Run database migrations and define application state objects."""
  logger = getattr(
    app.state,
    "logger",
    logging.getLogger("uvicorn.error"),
  )
  yield AppState(logger=logger)


app = FastAPI(
  **settings.fastapi_kwargs,
  exception_handlers=error_handlers,
  lifespan=lifespan,
)

internal_router = APIRouter(prefix="/api", tags=["internal"])


@internal_router.get("/version")
async def version() -> ApiVersion:
  """Return information about API version."""
  return ApiVersion.model_construct()


@internal_router.get("/health")
async def health() -> ApiHealth:
  """Return information about API health status."""
  return ApiHealth.model_construct()


app.include_router(internal_router)


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("main:app", **settings.uvicorn_kwargs)
