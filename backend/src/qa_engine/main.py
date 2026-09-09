from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from qa_engine.api import router
from qa_engine.config import settings
from qa_engine.database import engine
from qa_engine.migrations import ensure_schema
from qa_engine.database import SessionLocal
from qa_engine.services import recover_interrupted_analyses


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema(engine)
    # An in-process job dies with the process; its row does not. Clear the strays
    # before serving, so no project is left showing a spinner that never ends.
    session = SessionLocal()
    try:
        recover_interrupted_analyses(session)
    finally:
        session.close()
    yield


app = FastAPI(
    title="AI QA Agent Engine",
    version="0.1.0",
    description="Local-repository analysis API. No AI, Jira, GitHub remote, or Playwright in Phase 2.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": "ai-qa-engine"}
