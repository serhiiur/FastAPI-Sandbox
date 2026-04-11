## About

A minimal, production-ready FastAPI boilerplate designed as a starting point for new projects.


## Features

- **Python** (*>=3.12,<3.13*)
- **Docker + Docker Compose** setup
- **[UV](https://docs.astral.sh/uv/)** - package and project manager
- **[Ruff](https://docs.astral.sh/ruff/)** - linter and code formatter
- **[Ty](https://github.com/astral-sh/ty)** - type checker
- **[Pytest](https://docs.pytest.org/)** - testing framework
- **[Python JSON Logger](https://github.com/madzak/python-json-logger)** - structured JSON logger
- **[Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** - project settings manager
- **[faker](https://github.com/joke2k/faker)** - plugin for Pytest for generating random test data

## Notes

- All settings are read from the environment variables or <ins>.env</ins> file (see [.env.example](.env.example)). Copy it to <ins>.env</ins> before running the application.

- Configure **Uvicorn** via environment variables, set in <ins>.env</ins> file. It makes sense when running in Docker using [docker compose](docker-compose.yml). [.env.example](.env.example) file provides some configuration for Uvicorn.

- Logging config is defined in a [logging.config.json](logging.config.json). It gets passed to the `uvicorn` command when running the application.

- Logger object is tied to the application state. There is a [dependency](main.py#L66) to get the logger object. The logger object is [overridden](test_main.py#L15) during testing. Usage example:
```python
@app.get("/test")
async def test(logger: Logger) -> dict[str, str]:
  logger.warning("Something bad is going to happen ...")
  return {"response": "ok"}
```

- There is an [error handler](main.py#L83) to intercept all unhandled errors and return a custom response to the client, providing information about the error.

- There are 2 internal routes to specify [healthcheck](main.py#L151) and [version](main.py#L145) of the API. They use a separate `APIRouter` which is included in the main FastAPI application.

- By default Swagger UI is available at [/api/schema/docs](http://localhost:8000/api/schema/docs), ReDoc at [/api/schema/redoc](http://localhost:8000/api/schema/redoc), and the raw OpenAPI schema at [/api/schema/openapi.json](http://localhost:8000/api/schema/openapi.json). It can be changed in your <ins>.env</ins> configuration file.


## Running

There are 2 ways to run the FastAPI application. Make sure to configure your <ins>.env</ins> file beforehand.

### Running Locally

```bash
# install project dependencies
uv sync --all-groups

# run the application
uv run uvicorn main:app --log-config logging.config.json
```

### Running via Docker Compose

```bash
docker compose up --build
```

The API is now available at [http://localhost:8000](http://localhost:8000).

Navigate to [/api/schema/docs](http://localhost:8000/api/schema/docs) (or the path you set in your <ins>.env</ins> file) to get access to Swagger UI.


### Testing, Linting and Type-Checking commands:

```bash
# run tests
uv run pytest

# run linting
uv run ruff check

# run type checking
uv run ty check
```
