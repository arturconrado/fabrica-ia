import asyncio
import json

from sqlalchemy.orm import Session

from app.models import AgentEvent
from app.services.serialization import model_to_dict


async def event_stream(db_factory, run_id: str, tenant_id: str):
    sent = set()
    idle_ticks = 0
    while True:
        db: Session = db_factory()
        try:
            events = (
                db.query(AgentEvent)
                .filter(AgentEvent.run_id == run_id, AgentEvent.tenant_id == tenant_id)
                .order_by(AgentEvent.created_at.asc())
                .all()
            )
            for event in events:
                if event.id in sent:
                    continue
                sent.add(event.id)
                yield "data: " + json.dumps(model_to_dict(event), ensure_ascii=False) + "\n\n"
                idle_ticks = 0
        finally:
            db.close()
        idle_ticks += 1
        if idle_ticks > 120:
            yield ": keep-alive\n\n"
            idle_ticks = 0
        await asyncio.sleep(1)
