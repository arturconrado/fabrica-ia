import gzip
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes_service_delivery_os import _projection_cache, _tenant_projection
from app.auth.dependencies import ensure_tenant
from app.models import Base
from app.service_delivery.ledger import append_ledger_event


def test_tenant_projection_cache_tracks_the_append_only_ledger_head() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    calls = 0
    try:
        ensure_tenant(db, "tenant-a", "Tenant A")
        db.commit()

        def build():
            nonlocal calls
            calls += 1
            return {"revision": calls}

        first = _tenant_projection(
            db, tenant_id="tenant-a", projection="test", build=build
        )
        second = _tenant_projection(
            db, tenant_id="tenant-a", projection="test", build=build
        )
        assert json.loads(first.body) == {"revision": 1}
        assert json.loads(second.body) == {"revision": 1}
        assert second.headers["x-asf-projection-cache"] == "hit"
        assert calls == 1

        append_ledger_event(
            db,
            tenant_id="tenant-a",
            aggregate_type="test",
            aggregate_id="one",
            event_type="test.changed",
        )
        db.commit()
        third = _tenant_projection(
            db,
            tenant_id="tenant-a",
            projection="test",
            build=build,
            accepts_gzip=True,
        )
        assert json.loads(gzip.decompress(third.body)) == {"revision": 2}
        assert third.headers["content-encoding"] == "gzip"
        assert third.headers["vary"] == "Accept-Encoding"
        assert third.headers["x-asf-projection-cache"] == "miss"
        assert calls == 2
    finally:
        _projection_cache.clear()
        db.close()
        engine.dispose()
