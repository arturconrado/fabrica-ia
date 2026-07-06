from app.models import FileChange


def list_file_changes(db, run_id: str):
    return db.query(FileChange).filter_by(run_id=run_id).order_by(FileChange.created_at.asc()).all()
