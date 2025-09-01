from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from httpx import AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  async with AsyncClient() as client:
    app.state.client = client
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/test")
async def test(request: Request) -> dict[str, bool]:
  client = request.app.state.client
  return {"result": isinstance(client, AsyncClient)}
