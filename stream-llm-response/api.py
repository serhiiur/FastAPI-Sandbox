from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterable, TypeAlias, TypedDict

from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenAIKwargs(TypedDict):
  """Data structure to specify the kwargs for the OpenAI LLM."""

  model: str
  api_key: SecretStr


class Settings(BaseSettings):
  """Project settings."""

  model_config = SettingsConfigDict(env_file=".env")

  model: str = Field("gpt-4o-mini", description="Name of the OpenAI model to use")
  openai_api_key: SecretStr = Field("", description="OpenAI API key")

  @property
  def openai_kwargs(self) -> OpenAIKwargs:
    """Return the kwargs for the OpenAI LLM."""
    return OpenAIKwargs(model=self.model, api_key=self.openai_api_key)


settings = Settings()


class Prompt(BaseModel):
  """Request schema to specify the prompt to send to the LLM."""

  text: str = Field(..., description="Prompt to send to the LLM")


class AppState(TypedDict):
  """Data structure to specify state of the main FastAPI app."""

  llm: ChatOpenAI


async def get_llm(request: Request) -> ChatOpenAI:
  """Dependency to retrieve the LLM from the application state."""
  return request.state.llm


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[AppState]:
  """Init the application state with the LLM."""
  llm = ChatOpenAI(**settings.openai_kwargs)
  yield AppState(llm=llm)


app = FastAPI(lifespan=lifespan)

# reusable type aliases for endpoints
LLM: TypeAlias = Annotated[ChatOpenAI, Depends(get_llm)]

# shortcut to specify data type for the content of the LLM response chunk
type ChunkContent = str | list[str | dict[Any, Any]]


def stream_llm(llm: ChatOpenAI, prompt: str) -> Iterator[ChunkContent]:
  """Yield chunked response from the LLM."""
  response = llm.stream(prompt)
  for chunk in response:
    yield chunk.content


@app.post("/stream-llm-old")
async def stream_llm_old_way(llm: LLM, prompt: Prompt) -> StreamingResponse:
  """Stream LLM response using StreamingResponse."""
  content = stream_llm(llm, prompt.text)
  return StreamingResponse(content, media_type="text/event-stream")


@app.post("/stream-llm-new", response_class=EventSourceResponse)
async def stream_llm_new_way(llm: LLM, prompt: Prompt) -> AsyncIterable[ChunkContent]:
  """Stream LLM response using native python iterators."""
  response = llm.stream(prompt.text)
  for chunk in response:
    yield chunk.content


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("api:app", reload=True)
