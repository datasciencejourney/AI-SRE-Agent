from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import dev, incidents, webhooks
from app.db.session import init_db
from app.rag.store import seed_runbooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_runbooks()
    yield


app = FastAPI(title="AI SRE Agent", lifespan=lifespan)
app.include_router(webhooks.router)
app.include_router(incidents.router)
app.include_router(dev.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/ui/")


app.mount("/ui", StaticFiles(directory=Path(__file__).resolve().parents[1] / "dashboard", html=True), name="ui")
