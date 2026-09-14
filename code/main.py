from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
import uvicorn

app = FastAPI(title="User Management API", version="1.0.0")

#look for the HTML and JavaScript files in the static folder
app.mount("/static", StaticFiles(directory="static"), name="static")

class User(BaseModel):
    id: int
    primary_field: str
    secondary_field: str

class UserCreate(BaseModel):
    primary_field: str
    secondary_field: str

class UserUpdate(BaseModel):
    primary_field: str
    secondary_field: str

users: List[User] = [
    User(id = 1, primary_field = "", secondary_field = ""),
    User(id = 2, primary_field = "", secondary_field = "")
]

@app.get("/")
async def read_root():
    return FileResponse("static/HW1 - Angela Wei.html")

from fastapi import Response

#Get the API and all users
@app.get("/api/users", response_model=List[User])
async def get_users(response: Response, search: str = None):
    #tell client browsers and proxies to not cache user list
    # return list of current users
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    #the primary and secondary field should be searchable
    #convert all fields to lowecase to ensure that there is always a match that is found
    #even if user types in an uppercase letter
    if search:
        query = search.lower().strip()
        filtered = [
            u for u in users
            if query in u.primary_field.lower() or query  in u.secondary_field.lower()
        ]
        return filtered
    
    return users

# Get one user by their ID
@app.get("/api/users/{user_id}", response_model=User)
async def get_user(user_id: int):
    #search list for the first user matching the requested ID
    user = next((user for user in users if user.id == user_id), None)

    #raise  HTTP 404 error if the user is not found
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    #return the information if the user is found
    return user


#Create a new user record
@app.post("/api/users", response_model=User, status_code=201)
async def create_user(user_data: UserCreate):
    #if there is an empty string or blank, then reject it
    #raise HTTP 400 error if this happends
    if not user_data.primary_field.strip():
        raise HTTPException(status_code=400, detail="Please enter a primary field")

    #look for current highest ID and then add 1
    new_id = max([user.id for user in users], default=0) + 1

    #create new user object
    new_user = User(id=new_id, primary_field=user_data.primary_field, secondary_field=user_data.secondary_field)

    #add the new user object to list
    users.append(new_user)

    #return new user info
    print(f"A new record has been created: {new_user}")
    return new_user


#Update a record
@app.put("/api/users/{user_id}", response_model=User)
async def update_user(user_id: int, user_data: UserUpdate):
    #search for user by their ID
    user = next((user for user in users if user.id == user_id), None)

    #raise an HTTP 404 if the user is not found
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    #update fields if successful
    user.primary_field = user_data.primary_field
    user.secondary_field = user_data.secondary_field
    print(f"Updated record fields: {user}")
    return user
        

#Delete a record with the highest ID
@app.delete("/api/users/delete-highest", response_model = User)
async def delete_highest_user(user_id: int):
    #search for user by their ID
    #identify ID by the current highest number
    global users
    user_index = next((index for index, user in enumerate(users) if user.id == user_id), None)

    #raise an HTTP 404 if the user is not found
    if user_index is None:
        raise HTTPException(status_code=404, detail="Records are not found. Cannot be deleted.")

    #iterate through all available users
    #remove the user if found
    highest_id = users[0]
    for user in users:
        if user.id > highest_id.id:
            highest_id = user

    users.remove(highest_id)
    print(f"Record with the highest ID has been deleted: {highest_id}")
    return highest_id

import webbrowser

if __name__ == "__main__":
    #Open the browser automatically upon running file
    #use port 8439
    #is assigned PORT_BASE
    webbrowser.open("http://localhost:8439")
    uvicorn.run(app, host="0.0.0.0", port=8439)