import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hw6_mongodb import router as documents_router
from hw6_mongodb_memory import router as memory_router

# from hw3_authentication import router as auth_router
from hw7_authentication import router as auth_router

app = FastAPI(
    title="Extended Service API",
    description="An extension of FastAPI service for related entities and queries",
    version="1.0.0",
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-key")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# connect the router for hw3_authentication.py to work upon running the file
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(memory_router)


@app.get("/")
def root():
    return {"message": "API is running", "docs": "/docs"}


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}


# use to run the app on PORT_BASE 8439
if __name__ == "__main__":
    uvicorn.run("hw3_main:app", host="127.0.0.1", port=8439, reload=True)
