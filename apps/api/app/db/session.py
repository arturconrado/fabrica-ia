from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.paths import data_dir


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite:///./"):
        data_dir()
    return url


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False} if _database_url().startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(SQLAlchemySession, "before_flush")
def populate_tenant_id(session: SQLAlchemySession, _flush_context, _instances) -> None:
    from app.models import Batch, WorkflowRun

    settings = get_settings()
    run_tenants = {}
    batch_tenants = {}
    for obj in session.new:
        if not hasattr(obj, "tenant_id") or getattr(obj, "tenant_id", None):
            continue
        tenant_id = None
        run_id = getattr(obj, "run_id", None)
        batch_id = getattr(obj, "batch_id", None)
        if run_id:
            if run_id not in run_tenants:
                run = session.get(WorkflowRun, run_id)
                run_tenants[run_id] = run.tenant_id if run else None
            tenant_id = run_tenants[run_id]
        if not tenant_id and batch_id:
            if batch_id not in batch_tenants:
                batch = session.get(Batch, batch_id)
                batch_tenants[batch_id] = batch.tenant_id if batch else None
            tenant_id = batch_tenants[batch_id]
        setattr(obj, "tenant_id", tenant_id or settings.default_tenant_id)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
