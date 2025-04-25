from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm


app = FastAPI(
  description="API with restricted access to some endpoints"
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


ADMIN_USERNAME = "test"
ADMIN_PASSWORD = "test"


async def get_current_user(
  token: Annotated[str, Depends(oauth2_scheme)]
) -> dict[str, str]:
  if token:
    return token
  raise HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid authentication credentials",
    headers={"WWW-Authenticate": "Bearer"},
  )


@app.post("/login", include_in_schema=False)
async def login(
  form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> dict[str, str]:
  if form.username != ADMIN_USERNAME:
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect username")
  if form.password != ADMIN_PASSWORD:
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect password")
  return {"access_token": form.username, "token_type": "bearer"}


@app.get("/protected/")
async def get_protected(
  current_user: Annotated[str, Depends(get_current_user)]
) -> dict[str, str]:
  return {"hello": current_user}


@app.get("/unprotected/")
async def get_unprotected() -> dict[str, str]:
  return {"access": "free"}
