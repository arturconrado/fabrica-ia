from app.models import RequirementTrace


def p0_trace_count(db, run_id: str) -> int:
    return db.query(RequirementTrace).filter_by(run_id=run_id, status="pass").count()
