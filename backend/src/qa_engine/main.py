import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from qa_engine.api import router
from qa_engine.config import export_env_file, settings
from qa_engine.database import engine
from qa_engine.migrations import ensure_schema
from qa_engine.database import SessionLocal
from qa_engine.services import recover_interrupted_analyses, recover_interrupted_runs

logger = logging.getLogger(__name__)

# Uvicorn configures its own loggers and nothing else, so every message the engine wrote —
# which variables `.env` published, how long a generation took, that prompts were about to
# leave the machine — went nowhere. The engine's loggers get a handler of their own, in
# uvicorn's format, unless someone has already configured them.
_engine_logger = logging.getLogger("qa_engine")
if not _engine_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    _engine_logger.addHandler(_handler)
    _engine_logger.setLevel(logging.INFO)
    _engine_logger.propagate = False


def _announce_generation_provider() -> None:
    """Say at startup where generation prompts go, loudest when they leave the machine."""
    from qa_engine import llm

    if not settings.generation_enabled:
        logger.info("Génération automatique désactivée (GENERATION_ENABLED=false)")
    try:
        current = llm.provider()
    except llm.LLMError as exc:
        logger.error("Fournisseur de génération invalide : %s", exc)
        return
    if current.remote:
        logger.warning(
            "Génération via %s (%s) : les extraits de code, les textes des écrans et les "
            "exigences envoyés au modèle QUITTENT CETTE MACHINE. Certaines offres gratuites "
            "ou « contributor » les conservent pour entraîner leurs modèles.",
            current.endpoint,
            current.model,
        )
    else:
        logger.info("Génération locale : %s sur %s", current.model, current.endpoint)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Before anything else: a Playwright suite reads its own variables from the
    # environment the engine hands its subprocess, so `.env` has to reach it.
    published = export_env_file()
    if published:
        # Names only. A run's log is persisted and shown on screen.
        logger.info("Published from .env: %s", ", ".join(sorted(published)))

    _announce_generation_provider()

    ensure_schema(engine)
    # An in-process job dies with the process; its row does not. Clear the strays
    # before serving, so no project is left showing a spinner that never ends.
    session = SessionLocal()
    try:
        recover_interrupted_analyses(session)
        recover_interrupted_runs(session)
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
