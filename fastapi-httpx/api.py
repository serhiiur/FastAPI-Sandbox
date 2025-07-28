import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, TypedDict

import httpx
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

API_URL: str = "https://jsonplaceholder.typicode.com/"
API_HEADERS: dict[str, str] = {
  "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0"  # noqa: E501
}

logging.basicConfig(
  level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Post(BaseModel):
  """Schema to represent a post."""

  id: int
  user_id: int = Field(alias="userId")
  title: str
  body: str
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


async def log_request(request: httpx.Request) -> None:
  """Log the incoming request details."""
  logger.info("Request: %s %s", request.method, request.url)


async def log_response(response: httpx.Response) -> None:
  """Log the outgoing response details."""
  request = response.request
  logger.info(
    "Response: %s %s - Status %d", request.method, request.url, response.status_code
  )


async def httpx_error_handler(_: Request, e: httpx.HTTPStatusError) -> JSONResponse:
  """Httpx error handler."""
  if e.response.status_code == status.HTTP_404_NOT_FOUND:
    # Handle 404 Not Found errors specifically
    error = e.response.json().get("error", "Object not found")
  else:
    # For other errors, use the default error message
    error = e.response.text or "An unexpected error occurred"
  msg = {"API Error": error}
  return JSONResponse(msg, status_code=e.response.status_code)


class AsyncClient(httpx.AsyncClient):
  """Custom async http client that raises HTTPStatusError for non-200 responses."""

  async def request(self, *args, **kwargs) -> httpx.Response:  # noqa: ANN002, ANN003
    """Send the request and raise an exception for error status responses."""
    response = await super().request(*args, **kwargs)
    response.raise_for_status()
    return response


class AppState(TypedDict):
  """Data structure to hold application state."""

  http_client: AsyncClient


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Initialize the application state with an HTTP client."""
  http_client_config = {
    "base_url": API_URL,
    "headers": API_HEADERS,
    "event_hooks": {
      "request": [log_request],
      "response": [log_response],
    },
  }
  async with AsyncClient(**http_client_config) as http_client:
    yield AppState(http_client=http_client)


async def get_http_client(request: Request) -> AsyncClient:
  """Get the HTTP client from the application state."""
  return request.state.http_client


app = FastAPI(lifespan=lifespan)
app.add_exception_handler(httpx.HTTPStatusError, httpx_error_handler)


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT, headers={"x-status": "health"}
  )


@app.get("/posts/{id}", response_model=Post)
async def get_post(
  id: int,  # noqa: A002
  http_client: Annotated[AsyncClient, Depends(get_http_client)],
) -> dict:
  """Fetch a post by ID."""
  response = await http_client.get(f"/posts/{id}")
  return response.json()


@app.get("/posts", response_model=list[Post])
async def get_posts(
  http_client: Annotated[AsyncClient, Depends(get_http_client)],
) -> list[dict]:
  """Fetch a list of posts."""
  response = await http_client.get("/posts")
  return response.json()


@app.post("/posts", response_model=Post, status_code=status.HTTP_201_CREATED)
async def create_post(
  post: Post,
  http_client: Annotated[AsyncClient, Depends(get_http_client)],
) -> dict:
  """Create a new post."""
  response = await http_client.post("/posts", json=post.model_dump(by_alias=True))
  return response.json()


@app.delete("/posts/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
  id: int,  # noqa: A002
  http_client: Annotated[AsyncClient, Depends(get_http_client)],
) -> Response:
  """Delete a post by ID."""
  await http_client.delete(f"/posts/{id}")
  return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put("/posts/{id}", response_model=Post)
async def update_post(
  id: int,  # noqa: A002
  post: Post,
  http_client: Annotated[AsyncClient, Depends(get_http_client)],
) -> dict:
  """Update a post by ID."""
  response = await http_client.put(f"/posts/{id}", json=post.model_dump(by_alias=True))
  return response.json()
