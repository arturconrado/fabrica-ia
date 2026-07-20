import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_batches import router as batches_router
from app.api.routes_feedback import router as feedback_router
from app.api.routes_health import router as health_router
from app.api.routes_health import observe_request
from app.api.routes_learning import router as learning_router
from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_gamification import router as gamification_router
from app.api.routes_global_learning import router as global_learning_router
from app.api.routes_operator import router as operator_router
from app.api.routes_ai_cost import router as ai_cost_router
from app.api.routes_review import router as review_router
from app.api.routes_projects import router as projects_router
from app.api.routes_runtime import router as runtime_router
from app.api.routes_runs import router as runs_router
from app.api.routes_service_delivery import router as service_delivery_router
from app.api.routes_service_delivery_os import router as service_delivery_os_router
from app.api.routes_workflows import router as workflows_router
from app.core.config import get_settings, validate_production_runtime
from app.db.init_db import init_db
from app.db.session import SessionLocal, set_tenant_context
from app.service_delivery.ai_prompts import ensure_prompt_versions
from app.service_delivery.service import ensure_component_definitions
from app.service_delivery.catalog import ensure_service_catalog
from app.service_delivery.service import DomainError
from app.service_delivery.ledger import append_ledger_event
from app.knowledge.service import KnowledgeError
from app.observability.tracing import configure_tracing, shutdown_tracing
from app.services.run_service import provider

app = FastAPI(title="Agentic Software Factory API", version="0.1.0")
logger = logging.getLogger("asf.requests")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _audit_access_denial(request: Request, detail) -> None:
    tenant_id = getattr(request.state, "tenant_id", "")
    if tenant_id:
        audit_db = SessionLocal()
        try:
            set_tenant_context(audit_db, tenant_id, getattr(request.state, "user_id", "system"))
            normalized = detail if isinstance(detail, dict) else {"message": str(detail)}
            append_ledger_event(
                audit_db,
                tenant_id=tenant_id,
                aggregate_type="access_control",
                aggregate_id=str(normalized.get("details", {}).get("component_code") or tenant_id),
                event_type="access.denied",
                actor_user_id=getattr(request.state, "user_id", ""),
                correlation_id=request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or "",
                idempotency_key=f"access-denied:{uuid.uuid4()}",
                payload={"summary": normalized.get("message") or "Access denied", "code": normalized.get("code"), "path": request.url.path},
            )
            audit_db.commit()
        except Exception:
            audit_db.rollback()
            logger.exception("Failed to persist access denial event")
        finally:
            audit_db.close()


@app.exception_handler(DomainError)
def domain_error_handler(request: Request, exc: DomainError):
    if exc.status_code == 403:
        _audit_access_denial(request, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(KnowledgeError)
def knowledge_error_handler(request: Request, exc: KnowledgeError):
    if exc.status_code == 403:
        _audit_access_denial(request, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(HTTPException)
def http_error_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403:
        _audit_access_denial(request, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.middleware("http")
async def operational_request_log(request, call_next):
    started = time.perf_counter()
    correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or ""
    try:
        response = await call_next(request)
    except Exception:
        observe_request(500)
        logger.exception(
            json.dumps(
                {
                    "event": "http.request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "tenant_id": getattr(request.state, "tenant_id", request.headers.get("X-Tenant-ID") or "unknown"),
                    "correlation_id": correlation_id,
                }
            )
        )
        raise
    observe_request(response.status_code)
    logger.info(
        json.dumps(
            {
                "event": "http.request_completed",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "tenant_id": getattr(request.state, "tenant_id", request.headers.get("X-Tenant-ID") or "public"),
                "correlation_id": correlation_id,
            }
        )
    )
    return response

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(workflows_router)
app.include_router(runs_router)
app.include_router(feedback_router)
app.include_router(learning_router)
app.include_router(knowledge_router)
app.include_router(gamification_router)
app.include_router(global_learning_router)
app.include_router(operator_router)
app.include_router(ai_cost_router)
app.include_router(review_router)
app.include_router(batches_router)
app.include_router(runtime_router)
app.include_router(service_delivery_router)
app.include_router(service_delivery_os_router)


@app.on_event("startup")
def startup() -> None:
    validate_production_runtime()
    configure_tracing(settings)
    init_db()
    db = SessionLocal()
    try:
        ensure_component_definitions(db)
        ensure_service_catalog(db)
        ensure_prompt_versions(db)
        if settings.runtime_profile == "homologation":
            set_tenant_context(db, settings.default_tenant_id)
            provider.ensure_workflows(db, tenant_id=settings.default_tenant_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.on_event("shutdown")
def shutdown() -> None:
    shutdown_tracing()
