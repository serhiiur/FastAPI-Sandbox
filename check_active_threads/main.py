from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import uvicorn
from anyio.to_thread import current_default_thread_limiter
from fastapi import Depends, FastAPI, Request
from httpx import AsyncClient


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[dict[str, AsyncClient]]:
  async with AsyncClient() as client:
    yield {"client": client}


app = FastAPI(lifespan=lifespan)


# sync dependencies create a new thread
def http_client(request: Request) -> AsyncClient:
  return request.state.client


@app.get("/")
async def read_root(client: AsyncClient = Depends(http_client)) -> None:
  pass


async def monitor_thread_limiter() -> None:
  limiter = current_default_thread_limiter()
  threads_in_use = limiter.borrowed_tokens
  while True:
    if threads_in_use != limiter.borrowed_tokens:
      print(f"Threads in use: {limiter.borrowed_tokens}")
      threads_in_use = limiter.borrowed_tokens
    await anyio.lowlevel.checkpoint()


async def main() -> None:
  config = uvicorn.Config(app="main:app")
  server = uvicorn.Server(config)
  async with anyio.create_task_group() as tg:
    tg.start_soon(monitor_thread_limiter)
    await server.serve()


if __name__ == "__main__":
  anyio.run(main)
