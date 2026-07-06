from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_batches import router as batches_router
from app.api.routes_feedback import router as feedback_router
from app.api.routes_health import router as health_router
from app.api.routes_learning import router as learning_router
from app.api.routes_projects import router as projects_router
from app.api.routes_runtime import router as runtime_router
from app.api.routes_runs import router as runs_router
from app.api.routes_workflows import router as workflows_router
from app.core.config import get_settings, validate_production_runtime
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.services.run_service import provider

app = FastAPI(title="Agentic Software Factory API", version="0.1.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(workflows_router)
app.include_router(runs_router)
app.include_router(feedback_router)
app.include_router(learning_router)
app.include_router(batches_router)
app.include_router(runtime_router)


@app.on_event("startup")
def startup() -> None:
    validate_production_runtime()
    init_db()
    db = SessionLocal()
    try:
        provider.ensure_workflows(db)
    finally:
        db.close()
