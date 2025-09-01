from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from httpx import AsyncClient


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[dict]:
  async with AsyncClient() as client:
    yield {"client": client}


app = FastAPI(lifespan=lifespan)


@app.get("/test")
async def test(request: Request) -> dict[str, bool]:
  client = request.state.client
  return {"result": isinstance(client, AsyncClient)}
