from app.models import Artifact


def list_artifacts(db, run_id: str):
    return db.query(Artifact).filter_by(run_id=run_id).order_by(Artifact.created_at.asc()).all()
