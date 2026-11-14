import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth.routes import install_auth
from app.config import startup_notes
from app.service_requests.pages import router as service_pages_router
from app.service_requests.routes import router as service_requests_router
from app.service_requests.workflow_routes import router as service_workflow_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Database schema changes are explicit migrations; app startup is read-only (it never connects).
    shown = logging.getLogger("uvicorn.error")  # the logger uvicorn prints at INFO; the app logger would hide info notes
    for level, message in startup_notes():
        shown.log(logging.WARNING if level == 'warning' else logging.INFO, message)
    yield


app = FastAPI(title="Service Desk Agent API", lifespan=lifespan)
install_auth(app)
app.include_router(service_requests_router)
app.include_router(service_workflow_router)
app.include_router(service_pages_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


static_dir = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
else:
    logger.info("Static directory %s does not exist; frontend mount skipped", static_dir)
