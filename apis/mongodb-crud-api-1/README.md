## About

This is a sample API that provides a CRUD API for managing movies in a local MongoDB database, provisioned by Docker using Docker Compose. [Beanie](https://github.com/BeanieODM/beanie) ODM is used for integrating MongoDB with FastAPI.


## Running
```bash
# run tests
docker compose run --rm --no-deps api pytest -vx -W ignore

# run the API
docker compose up -d
```


## Usage
After running the API, navigate to `http://localhost:8000/docs` to access the interactive Swagger UI documentation. You can use this interface to test the CRUD operations for managing movies.

In addition, you can access the MongoDB management UI at `http://localhost:8081` using credentials, specified in the <ins>.env</ins> file.


## References
- [Beanie ODM Github](https://github.com/BeanieODM/beanie)
- [Mongo Docker Image](https://hub.docker.com/_/mongo)
- [Mongo-Express Docker Image](https://hub.docker.com/_/mongo-express)
