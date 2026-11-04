import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.db import db_ok
from app.ingest.pipeline import fail_interrupted_ingestions
from app.quiz.job import fail_interrupted_quizzes
from app.routers import auth, chat, documents, metrics, quizzes, verify

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        fail_interrupted_ingestions()
        fail_interrupted_quizzes()
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
app.include_router(quizzes.router)
app.include_router(metrics.router)
app.include_router(chat.router)
app.include_router(verify.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": db_ok()}
