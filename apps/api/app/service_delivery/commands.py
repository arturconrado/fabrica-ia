import hashlib
import json
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.ids import new_id
from app.models import CommandReceipt, utcnow
from app.service_delivery.service import DomainError


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def begin_command(
    db: Session,
    *,
    tenant_id: str,
    command_name: str,
    idempotency_key: str,
    request_payload: Dict[str, Any],
) -> tuple[CommandReceipt, Optional[Dict[str, Any]]]:
    """Start an idempotent command or return its previously committed result."""
    key = idempotency_key.strip()
    if not key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required for this command")
    request_hash = hashlib.sha256(_canonical(request_payload).encode("utf-8")).hexdigest()
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 1))"),
            {"lock_key": f"{tenant_id}:{command_name}:{key}"},
        )
    receipt = (
        db.query(CommandReceipt)
        .filter_by(tenant_id=tenant_id, command_name=command_name, idempotency_key=key)
        .with_for_update()
        .first()
    )
    if receipt:
        if receipt.request_hash != request_hash:
            raise DomainError(
                409,
                "IDEMPOTENCY_PAYLOAD_MISMATCH",
                "The idempotency key was already used with a different payload",
            )
        if receipt.status == "completed":
            return receipt, receipt.response_json
        now = utcnow()
        if receipt.lease_expires_at and receipt.lease_expires_at <= now:
            receipt.lease_expires_at = now + timedelta(minutes=30)
            receipt.attempt_count += 1
            db.flush()
            return receipt, None
        raise DomainError(409, "COMMAND_IN_PROGRESS", "The command is already in progress")
    now = utcnow()
    receipt = CommandReceipt(
        id=new_id(),
        tenant_id=tenant_id,
        command_name=command_name,
        idempotency_key=key,
        request_hash=request_hash,
        status="started",
        response_json={},
        lease_expires_at=now + timedelta(minutes=30),
        attempt_count=1,
    )
    db.add(receipt)
    db.flush()
    return receipt, None


def complete_command(
    db: Session,
    receipt: CommandReceipt,
    *,
    response: Dict[str, Any],
    resource_type: str,
    resource_id: str,
) -> Dict[str, Any]:
    receipt.status = "completed"
    receipt.resource_type = resource_type
    receipt.resource_id = resource_id
    receipt.response_json = response
    receipt.completed_at = utcnow()
    receipt.lease_expires_at = None
    db.flush()
    return response
