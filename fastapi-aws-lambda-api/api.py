from fastapi import FastAPI
from mangum import Mangum

app = FastAPI()
handler = Mangum(app)


@app.get("/")
async def index() -> dict[str, str]:
  return {"message": "hello, world"}


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("api:app")
