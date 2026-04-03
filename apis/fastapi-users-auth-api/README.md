## About
The project provides a basic implementation of a FastAPI-based API using [FastAPI Users](https://github.com/fastapi-users/fastapi-users) package to configure and manage users authentication and authorization.


**Note**: the API has't covered with tests yet!


## Running
```bash
# run API
uvicorn api:app --reload

# run tests
pytest -vx test_api.py
```


## References
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [FastAPI Users library](https://fastapi-users.github.io/fastapi-users/latest/)
