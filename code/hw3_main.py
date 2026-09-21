import os
import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from hw3_authentication import router as auth_router

app = FastAPI()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-key")

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=True,
    same_site="lax",
    max_age=3600
)

#connect the router for hw3_authentication.py to work upon running the file
app.include_router(auth_router)

#use to run the app on PORT_BASE 8439
if __name__ == "__main__":
    uvicorn.run(
        "hw3_main:app",
        host="127.0.0.1",
        port=8439,
        reload=True
    )
