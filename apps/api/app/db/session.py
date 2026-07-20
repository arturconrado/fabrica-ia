from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm import with_loader_criteria
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


def set_tenant_context(db: SQLAlchemySession, tenant_id: str, user_id: str = "system") -> None:
    """Bind tenant/user context to the current transaction for PostgreSQL RLS."""
    previous_tenant_id = db.info.get("tenant_id")
    if previous_tenant_id and previous_tenant_id != tenant_id:
        # A session used by controlled bootstrap/demo routines may cross tenant
        # boundaries. Persist the previous tenant's pending ORM changes while
        # its RLS context is still active; flushing after the switch would make
        # PostgreSQL hide those rows and SQLAlchemy would raise StaleDataError.
        db.flush()
    db.info["tenant_id"] = tenant_id
    db.info["user_id"] = user_id
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT set_config('app.tenant_id', :tenant_id, true), "
                "set_config('app.user_id', :user_id, true)"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )


@event.listens_for(SQLAlchemySession, "after_begin")
def restore_tenant_context(session: SQLAlchemySession, _transaction, connection) -> None:
    """Reapply RLS variables whenever a session starts a new transaction."""
    tenant_id = session.info.get("tenant_id")
    if tenant_id and connection.dialect.name == "postgresql":
        connection.execute(
            text(
                "SELECT set_config('app.tenant_id', :tenant_id, true), "
                "set_config('app.user_id', :user_id, true)"
            ),
            {"tenant_id": tenant_id, "user_id": session.info.get("user_id") or "system"},
        )


@event.listens_for(SQLAlchemySession, "before_flush")
def populate_tenant_id(session: SQLAlchemySession, _flush_context, _instances) -> None:
    from app.models import Batch, WorkflowRun

    settings = get_settings()
    run_tenants = {}
    batch_tenants = {}
    for obj in session.new:
        if not hasattr(obj, "tenant_id"):
            continue
        explicit_tenant_id = getattr(obj, "tenant_id", None)
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
        inherited_tenant_id = tenant_id or session.info.get("tenant_id") or settings.default_tenant_id
        if explicit_tenant_id and tenant_id and explicit_tenant_id != tenant_id:
            raise ValueError("Tenant mismatch between child record and owning run/batch")
        if not explicit_tenant_id:
            setattr(obj, "tenant_id", inherited_tenant_id)


@event.listens_for(SQLAlchemySession, "do_orm_execute")
def apply_automatic_tenant_filter(execute_state) -> None:
    """Add defense-in-depth tenant predicates to ORM SELECT statements.

    PostgreSQL RLS remains the security boundary. This filter also protects
    homologation/SQLite paths and makes accidental unscoped ORM reads visible.
    """
    if not execute_state.is_select or execute_state.execution_options.get("include_all_tenants"):
        return
    tenant_id = execute_state.session.info.get("tenant_id")
    if not tenant_id:
        return
    from app.models import Base, PromptEvaluation, PromptVersion

    statement = execute_state.statement
    for mapper in Base.registry.mappers:
        entity = mapper.class_
        if not hasattr(entity, "tenant_id"):
            continue
        if entity in {PromptVersion, PromptEvaluation}:
            statement = statement.options(
                with_loader_criteria(
                    entity,
                    lambda row: (row.tenant_id == tenant_id) | (row.tenant_id == "global"),
                    include_aliases=True,
                )
            )
        else:
            statement = statement.options(
                with_loader_criteria(entity, lambda row: row.tenant_id == tenant_id, include_aliases=True)
            )
    execute_state.statement = statement


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
