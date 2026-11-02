from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import db_ok
from app.routers import auth

app = FastAPI(title="SmartQuiz API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": db_ok()}
