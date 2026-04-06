## About
Minimal FastAPI application with JWT authentication.

**Note**: the implementation is taken from the [official documentation](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) and slightly modified according to the author's preferences.


## Running
```bash
# run API
python api.py

# run tests
pytest -vx test_api.py
```


## Usage
Open up [/docs](http://localhost:8000/docs) in your browser and authenticate using credentials:
```
username: joedoe
password: joedoe
```

Then send a POST request to `/users/me/` endpoint to make sure that the authentication succeeded and the information about current user is displayed correctly.


## References
- [OAuth2 with Password (and hashing), Bearer with JWT tokens](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
