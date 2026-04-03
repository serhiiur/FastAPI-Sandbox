from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypedDict, cast

import graphene
from fastapi import FastAPI, Response, status
from graphql.error.graphql_error import GraphQLError
from httpx import AsyncClient
from pydantic_settings import BaseSettings
from starlette_graphene3 import GraphQLApp

if TYPE_CHECKING:
  from graphql.type.definition import GraphQLResolveInfo


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


class Settings(BaseSettings):
  """API settings."""

  # FastAPI settings
  title: str = "GraphQL CRUD API"
  description: str = "GraphQL CRUD API using data from JSONPlaceholder API"
  version: str = "0.0.1"
  debug: bool = True

  # JSONPlaceholder API settings
  users_api_url: str = "https://jsonplaceholder.typicode.com/"
  users_api_headers: dict[str, str] = {
    "Content-type": "application/json; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0",  # noqa: E501
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
      base_url=self.users_api_url,
      headers=self.users_api_headers,
    )


@lru_cache
def get_settings() -> Settings:
  """Return cached project settings."""
  return Settings()


settings = get_settings()


class Geo(graphene.ObjectType):
  """Info about location of the place, where the user lives in."""

  lat = graphene.Float()
  lng = graphene.Float()


class Company(graphene.ObjectType):
  """Info about company in which the user works in."""

  name = graphene.String()
  catch_phrase = graphene.String()
  bs = graphene.String()


class Address(graphene.ObjectType):
  """Info about location, where the user lives at."""

  street = graphene.String()
  suite = graphene.String()
  city = graphene.String()
  zipcode = graphene.String()
  geo = graphene.Field(Geo)


class User(graphene.ObjectType):
  """Full info about user."""

  id = graphene.ID(required=True)
  name = graphene.String()
  username = graphene.String()
  email = graphene.String(required=True)
  address = graphene.Field(Address)
  phone = graphene.String()
  website = graphene.String()
  company = graphene.Field(Company)


class CompanyInput(graphene.InputObjectType):
  """Schema to update info about company."""

  name = graphene.String(required=True)
  catch_phrase = graphene.String()
  bs = graphene.String()


class GeoInput(graphene.InputObjectType):
  """Schema to update GEO location."""

  lat = graphene.Float(required=True)
  lng = graphene.Float(required=True)


class AddressInput(graphene.InputObjectType):
  """Schema to update general location info."""

  city = graphene.String(required=True)
  street = graphene.String(required=True)
  suite = graphene.String()
  zipcode = graphene.String()
  geo = graphene.InputField(GeoInput)


class CreateUserInput(graphene.InputObjectType):
  """Schema to create a new user."""

  name = graphene.String(required=True)
  username = graphene.String(required=True)
  email = graphene.String(required=True)
  phone = graphene.String()
  website = graphene.String()
  company = graphene.InputField(CompanyInput)
  address = graphene.InputField(AddressInput)


class UpdateUserInput(graphene.InputObjectType):
  """Schema to update info about user."""

  name = graphene.String()
  username = graphene.String()
  email = graphene.String()
  phone = graphene.String()
  website = graphene.String()
  company = graphene.InputField(CompanyInput)
  address = graphene.InputField(AddressInput)


class CreateUser(graphene.Mutation):
  """Mutation to create a new user."""

  Output = User

  class Arguments:
    """Input arguments to create the user."""

    user = CreateUserInput(required=True)

  @staticmethod
  async def mutate(
    _: None,
    info: "GraphQLResolveInfo",
    user: "User",
  ) -> dict[str, Any]:
    """Save info about user."""
    http_client = cast("AsyncClient", info.context["http_client"])
    resp = await http_client.post("/users", json=user)
    return resp.json()


class UpdateUser(graphene.Mutation):
  """Mutation to update info about user."""

  Output = User

  class Arguments:
    """Input arguments to update the user."""

    user_id = graphene.ID(required=True)
    user = UpdateUserInput()

  @staticmethod
  async def mutate(
    _: None,
    info: "GraphQLResolveInfo",
    user_id: str,
    user: dict[str, Any],
  ) -> dict[str, Any]:
    """Update info about user."""
    http_client = cast("AsyncClient", info.context["http_client"])
    resp = await http_client.patch(f"/users/{user_id}", json=user)
    return resp.json()


class DeleteUser(graphene.Mutation):
  """Mutation to delete a user from the database."""

  ok = graphene.Boolean()

  class Arguments:
    """Input arguments to delete the user."""

    user_id = graphene.ID(required=True)

  @staticmethod
  async def mutate(
    _: None,
    info: "GraphQLResolveInfo",
    user_id: str,
  ) -> "DeleteUser":
    """Delete info about user."""
    http_client = cast("AsyncClient", info.context["http_client"])
    resp = await http_client.delete(f"/users/{user_id}")
    return DeleteUser(ok=resp.status_code == status.HTTP_200_OK)


class Query(graphene.ObjectType):
  """Query to fetch info about one or all users from the API."""

  user = graphene.Field(User, user_id=graphene.String(required=True))
  users = graphene.List(User)

  @staticmethod
  async def resolve_users(
    _: None,
    info: "GraphQLResolveInfo",
  ) -> list[dict[str, Any]]:
    """Fetch info about all users."""
    http_client = cast("AsyncClient", info.context["http_client"])
    resp = await http_client.get("/users")
    return resp.json()

  @staticmethod
  async def resolve_user(
    _: None,
    info: "GraphQLResolveInfo",
    user_id: str,
  ) -> dict[str, Any]:
    """Fetch info about specific user."""
    http_client = cast("AsyncClient", info.context["http_client"])
    resp = await http_client.get(f"/users/{user_id}")
    if user := resp.json():
      return user
    raise GraphQLError(message="User not found")


class Mutations(graphene.ObjectType):
  """Class to represent a list of available mutations."""

  create_user = CreateUser.Field()
  update_user = UpdateUser.Field()
  delete_user = DeleteUser.Field()


schema = graphene.Schema(query=Query, mutation=Mutations)


class GraphQLAppContext(TypedDict):
  """Context attributes of the GraphQL app."""

  http_client: AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Init global HTTP client."""
  graphql_app = GraphQLApp(schema, playground=settings.debug)
  app.mount("/graphql", graphql_app)
  async with AsyncClient(**settings.http_kwargs) as http_client:
    graphql_app.context_value = GraphQLAppContext(http_client=http_client)
    yield


app = FastAPI(**settings.fastapi_kwargs, lifespan=lifespan)


@app.get("/health", status_code=status.HTTP_204_NO_CONTENT)
async def health() -> Response:
  """Health-check endpoint."""
  return Response(
    status_code=status.HTTP_204_NO_CONTENT,
    headers={"x-status": "ok"},
  )


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("api:app", reload=settings.debug)
