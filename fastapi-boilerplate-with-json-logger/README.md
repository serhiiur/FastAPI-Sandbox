## About

A minimal, production-ready FastAPI boilerplate designed as a starting point for new projects.


## Features

- **Python** (*>=3.12,<3.13*)
- **[UV](https://docs.astral.sh/uv/)** - package and project manager
- **[Ruff](https://docs.astral.sh/ruff/)** - linter and code formatter
- **[Ty](https://github.com/astral-sh/ty)** - type checker
- **[Pytest](https://docs.pytest.org/)** - testing framework
- **[Python JSON Logger](https://github.com/madzak/python-json-logger)** - structured JSON logger
- **[Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** - project settings manager
- **[uvloop](https://github.com/MagicStack/uvloop)** - fast, drop-in replacement of the built-in *asyncio* event loop
- **[faker](https://github.com/joke2k/faker)** - plugin for Pytest for generating random test data

## Notes

- All settings are read from the environment variables or <ins>.env</ins> file (see [.env.example](.env.example)). Copy it to <ins>.env</ins> before running the application.

- Debug mode is enabled by default.

- Logger object is tied to the application state in the [lifespan](main.py#L182) and additionally provided as a [dependency](main.py#L122) for FastAPI endpoints or other dependencies. The logger object is [overridden](test_main.py#L15) during testing. Usage example:
```python
@app.get("/test")
async def test(logger: Logger) -> dict[str, str]:
  logger.warning("Something bad is going to happen ...")
  return {"response": "ok"}
```

- There are separate settings for Uvicorn defined in the [project settings](main.py#L68). It can be easily extended or modified. The settings is applicable if you run the application like this:
```bash
uv run python main.py
```

- By default Swagger UI is available at `/api/schema/docs`, ReDoc at `/api/schema/redoc`, and the raw OpenAPI schema at `/api/schema/openapi.json`. It can be easily changed in your <ins>.env</ins> configuration file.


## Running

Before running the application make sure to install project dependencies with uv:
```bash
uv sync --all-groups
```

Then make sure to configure (or preserve the default values) the <ins>.env</ins> file.

Finally run the application:
```bash
uv run python main.py
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


## References

- [FastAPI](https://fastapi.tiangolo.com)
- [UV](https://docs.astral.sh/uv/)
- [Ruff](https://docs.astral.sh/ruff/)
- [Ty](https://github.com/astral-sh/ty)
- [Pytest](https://docs.pytest.org/)
- [Python JSON Logger](https://github.com/madzak/python-json-logger)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [asgi-lifespan](https://github.com/florimondmanca/asgi-lifespan)
