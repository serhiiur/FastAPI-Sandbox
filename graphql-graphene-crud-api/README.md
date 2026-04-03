## About

The project provides an example of how to integrate a simple GraphQL API using [FastAPI](https://github.com/fastapi/fastapi) and [Graphene](https://github.com/graphql-python/graphene) and widely known [JSONPlaceholder](https://jsonplaceholder.typicode.com/) API


## Running
```bash
# run API
python api.py

# run tests
pytest -vsx test_api.py
```


## Usage
After running the API, open up the [Playground](http://localhost:8000/graphql) in your browser and manually run the queries:

Get all users:
```
query GetUsers{
  users{
    name
    username
    email
    address { city street zipcode }
  }
}
```

Get a single user:
```
query GetUser{
  user(userId: "2"){
    id
    name
    email
    address { city geo { lat lng } }
    company{ name }
  }
}
```

Create a new user:
```
mutation CreateUser{
  createUser(user: {
    name: "John Smith",
    username: "johnsmith123",
    email: "johnsmith@example.com",
    company: {name: "Ubisoft", catchPhrase:"My Games"},
    address:{city: "London", street: "NC Av.34 b.19", geo: {lat: 92.18283, lng: -87.22}}
  }){
    id
    name
    username
    email
    address { city geo { lat lng } }
    company { name }
  }
}
```

Update a user:
```
mutation UpdateUser{
  updateUser(userId: "7", user:{
    email: "ervinhowell@example.com",
    address:{ city: "London" street: "H. Maria Av. 57.1"}
    company: {name: "Ubisoft"}
  }){
    email
    address { city }
    company { name }
    
  }
}
```

Delete a user:
```
mutation DeleteUser{
  deleteUser(userId: "1"){
    ok
  }
}
```