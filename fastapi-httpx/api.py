import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

import httpx
from fastapi import Depends, FastAPI, Path, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
  from logging import Logger


class FastAPIKwargs(TypedDict):
  """Kwargs for FastAPI app."""

  title: str
  description: str
  version: str
  debug: bool


class HttpKwargs(TypedDict):
  """Kwargs for Http client."""

  base_url: str
  headers: dict[str, str]


class LoggingKwargs(TypedDict):
  """Kwargs for logger config."""

  level: int
  format: str


class Settings(BaseSettings):
  """API settings."""

  # FastAPI settings
  title: str = "Posts Management API"
  description: str = "API to manage Posts from a 3rd-party API"
  version: str = "0.0.1"
  debug: bool = False

  # Logging settings
  log_name: str = __name__
  log_level: int = logging.INFO
  log_format: str = "%(levelname)s - %(name)s - %(asctime)s - %(message)s"

  # JSONPlaceholder API settings
  posts_api_url: str = "https://jsonplaceholder.typicode.com/"
  posts_api_headers: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0"  # noqa: E501
  }

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
  def http_kwargs(self) -> HttpKwargs:
    """Kwargs for Http client."""
    return HttpKwargs(
      base_url=self.posts_api_url,
      headers=self.posts_api_headers,
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


class CreatePost(BaseModel):
  """Schema for creating posts."""

  user_id: int = Field(
    alias="userId",
    description="ID of the Author of the post",
  )
  title: str = Field(description="Title of the post")
  body: str = Field(description="Text of the post")


class Post(CreatePost):
  """Schema to represent a post."""

  id: int = Field(description="ID of the post")
  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "id": 1,
        "userId": 1,
        "title": "Sample Post",
        "body": "This is a sample post.",
      }
    }
  )


def get_logger(request: Request) -> "Logger":
  """Return logger object, initialized in the lifespan."""
  return request.app.state.logger


async def http_error_handler(
  request: Request,
  e: httpx.HTTPStatusError,
) -> JSONResponse:
  """Httpx error handler."""
  logger = get_logger(request)
  if e.response.status_code == status.HTTP_404_NOT_FOUND:
    # Handle 404 Not Found errors specifically
    error = e.response.json().get("error", "Post not found")
    logger.info(error)
  else:
    # For other errors, use the default error message
    error = "Service is temporarily unavailable"
    logger.critical("Unexpected error occurred: %s", e.response.text)
  client_message = {"error": error}
  return JSONResponse(client_message, status_code=e.response.status_code)


class AsyncClient(httpx.AsyncClient):
  """Custom async http client based on httpx.AsyncClient.

  The client overrides request method to raise HTTPStatusError
  for non-200 responses.
  """

  async def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
    """Send the request and raise an exception for error status responses."""
    response = await super().request(*args, **kwargs)
    response.raise_for_status()
    return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
  """Initialize the application state with an HTTP client."""
  logger = configure_logging()
  http_client = AsyncClient(**settings.http_kwargs)
  # Set application state
  app.state.logger = logger
  app.state.http_client = http_client
  yield
  await http_client.aclose()


async def get_http_client(request: Request) -> AsyncClient:
  """Get the HTTP client from the application state."""
  return request.app.state.http_client


app = FastAPI(
  **settings.fastapi_kwargs,
  lifespan=lifespan,
  exception_handlers={
    httpx.HTTPStatusError: http_error_handler,
  },
)

# https://fastapi.tiangolo.com/tutorial/dependencies/#share-annotated-dependencies
HttpClient = Annotated[AsyncClient, Depends(get_http_client)]


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


PostID = Annotated[int, Path(alias="postId")]


@app.get(
  "/posts/{postId}",  # noqa: FAST003
  response_model=Post,
  tags=["posts"],
)
async def fetch_post(post_id: PostID, http_client: HttpClient) -> dict:
  """Fetch post by ID."""
  resp = await http_client.get(f"/posts/{post_id}")
  return resp.json()


@app.get(
  "/posts",
  response_model=list[Post],
  tags=["posts"],
)
async def fetch_all_posts(http_client: HttpClient) -> list[dict]:
  """Fetch list of posts."""
  resp = await http_client.get("/posts")
  return resp.json()


@app.post(
  "/posts",
  response_model=Post,
  status_code=status.HTTP_201_CREATED,
  tags=["posts"],
)
async def create_post(post: CreatePost, http_client: HttpClient) -> dict:
  """Create new post."""
  new_post = post.model_dump(by_alias=True)
  resp = await http_client.post("/posts", json=new_post)
  return resp.json()


@app.delete(
  "/posts/{postId}",  # noqa: FAST003
  status_code=status.HTTP_204_NO_CONTENT,
  tags=["posts"],
)
async def delete_post(post_id: PostID, http_client: HttpClient) -> Response:
  """Delete post by ID."""
  await http_client.delete(f"/posts/{post_id}")
  return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put(
  "/posts/{postId}",  # noqa: FAST003
  response_model=Post,
  tags=["posts"],
)
async def update_post(
  post_id: PostID,
  post: Post,
  http_client: HttpClient,
) -> dict:
  """Update post by ID."""
  updated_post = post.model_dump(by_alias=True)
  resp = await http_client.put(f"/posts/{post_id}", json=updated_post)
  return resp.json()
