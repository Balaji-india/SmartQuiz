import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.db import db_ok
from app.ingest.pipeline import fail_interrupted_ingestions
from app.routers import auth, documents

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        fail_interrupted_ingestions()
    except SQLAlchemyError:
        # /health reports a database that is down; the API should still start.
        log.warning("could not check for interrupted ingestions")
    yield


app = FastAPI(title="SmartQuiz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": db_ok()}
