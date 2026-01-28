from fastapi import FastAPI

from routes_v1 import router as router_v1  # isort: skip
from routes_v2 import router as router_v2

app = FastAPI(
  title="File Upload API",
  description="An API to upload files synchronously and asynchronously.",
)
app.include_router(router_v1, prefix="/v1")
app.include_router(router_v2, prefix="/v2")
