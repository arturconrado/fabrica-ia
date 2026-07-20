from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, get_current_principal
from app.db.session import get_db
from app.models import GamificationEvent, HomologationPackage, QualityGate
from app.schemas.operational import Achievement, GamificationLevel, GamificationProfileResponse
from app.services.serialization import models_to_dict


router = APIRouter(prefix="/api/v1/gamification", tags=["gamification"])
LEVELS = [
    (1, "Iniciação", 0),
    (2, "Operação", 100),
    (3, "Orquestração", 300),
    (4, "Homologação", 700),
    (5, "Excelência", 1500),
]


def _level(xp: int) -> GamificationLevel:
    number, name, threshold = next(level for level in reversed(LEVELS) if xp >= level[2])
    next_threshold = next((item[2] for item in LEVELS if item[2] > threshold), None)
    progress = 100.0 if next_threshold is None else round((xp - threshold) / (next_threshold - threshold) * 100, 2)
    return GamificationLevel(
        number=number,
        name=name,
        threshold=threshold,
        next_threshold=next_threshold,
        progress_percent=max(0.0, min(100.0, progress)),
    )


def _first(events: list[GamificationEvent], event_type: str):
    return next((event for event in events if event.event_type == event_type), None)


@router.get("/profile", response_model=GamificationProfileResponse)
def profile(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    events = (
        db.query(GamificationEvent)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(GamificationEvent.created_at.asc())
        .all()
    )
    xp = sum(event.points for event in events)
    base = _first(events, "knowledge.document_indexed")
    mission = _first(events, "mvp_run.asf_run_created")
    package = _first(events, "homologation.package_created")
    delivery = _first(events, "deliverable.approved_and_delivered")
    completed_quality_run = None
    run_ids = [row[0] for row in db.query(QualityGate.run_id).filter_by(tenant_id=principal.tenant_id).distinct().all()]
    for run_id in run_ids:
        gates = db.query(QualityGate).filter_by(tenant_id=principal.tenant_id, run_id=run_id).all()
        if gates and all(gate.status == "passed" for gate in gates):
            completed_quality_run = max(gate.created_at for gate in gates)
            break
    achievements = [
        Achievement(code="knowledge_ready", name="Base Preparada", unlocked=bool(base), unlocked_at=base.created_at.isoformat() if base else None),
        Achievement(code="mission_started", name="Missão Iniciada", unlocked=bool(mission), unlocked_at=mission.created_at.isoformat() if mission else None),
        Achievement(code="quality_rail", name="Quality Rail Concluído", unlocked=bool(completed_quality_run), unlocked_at=completed_quality_run.isoformat() if completed_quality_run else None),
        Achievement(code="homologated", name="Homologação Concluída", unlocked=bool(package), unlocked_at=package.created_at.isoformat() if package else None),
        Achievement(code="delivery_accepted", name="Entrega Aceita", unlocked=bool(delivery), unlocked_at=delivery.created_at.isoformat() if delivery else None),
    ]
    return GamificationProfileResponse(
        tenant_id=principal.tenant_id,
        xp_total=xp,
        level=_level(xp),
        achievements=achievements,
        recent_events=models_to_dict(list(reversed(events[-20:]))),
    )


@router.get("/events")
def gamification_events(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(GamificationEvent)
        .filter_by(tenant_id=principal.tenant_id)
        .order_by(GamificationEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return models_to_dict(rows)
