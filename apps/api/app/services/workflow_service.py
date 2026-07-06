from app.services.run_service import provider

def ensure_workflows(db):
    provider.ensure_workflows(db)
