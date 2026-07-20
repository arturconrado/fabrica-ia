from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, require_roles
from app.db.session import get_db
from app.knowledge.service import KnowledgeService
from app.service_delivery.commands import begin_command, complete_command
from app.service_delivery.service import DomainError
from app.services.serialization import model_to_dict


router = APIRouter(prefix="/api/v1", tags=["knowledge"])
service = KnowledgeService()


class KnowledgeBasePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2_000)


class KnowledgeDocumentPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    source_type: str = Field(default="operator", max_length=50)
    source_ref: str = Field(default="", max_length=1_000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeQueryPayload(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)
    generate_answer: bool = False


def _correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or "knowledge-api"


def _idempotency_key(request: Request) -> str:
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
    return key


def _base_response(base) -> Dict[str, Any]:
    value = model_to_dict(base)
    return value


def _document_summary(document) -> Dict[str, Any]:
    return {
        "id": document.id,
        "tenant_id": document.tenant_id,
        "knowledge_base_id": document.knowledge_base_id,
        "title": document.title,
        "source_type": document.source_type,
        "source_ref": document.source_ref,
        "checksum": document.checksum,
        "storage_key": document.storage_key,
        "status": document.status,
        "metadata_json": document.metadata_json,
        "created_by_user_id": document.created_by_user_id,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _document_detail(document) -> Dict[str, Any]:
    return {**_document_summary(document), "content": document.content}


@router.get("/knowledge-bases")
def list_knowledge_bases(
    principal: Principal = Depends(require_roles("admin", "operator", "viewer", "tenant_admin", "engagement_manager", "consultant", "auditor")),
    db: Session = Depends(get_db),
):
    return [_base_response(base) for base in service.list_bases(db, principal.tenant_id)]


@router.post("/knowledge-bases")
def create_knowledge_base(
    payload: KnowledgeBasePayload,
    request: Request,
    principal: Principal = Depends(require_roles("admin", "operator", "tenant_admin", "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = payload.model_dump()
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="knowledge.create_base",
        idempotency_key=_idempotency_key(request),
        request_payload=request_payload,
    )
    if cached is not None:
        return cached
    base = service.create_base(
        db,
        principal.tenant_id,
        principal.user_id,
        payload.name,
        payload.description,
        _correlation_id(request),
    )
    response = _base_response(base)
    complete_command(db, receipt, response=response, resource_type="knowledge_base", resource_id=base.id)
    db.commit()
    return response


@router.get("/knowledge-bases/{knowledge_base_id}/documents")
def list_knowledge_documents(
    knowledge_base_id: str,
    principal: Principal = Depends(require_roles("admin", "operator", "viewer", "tenant_admin", "engagement_manager", "consultant", "auditor")),
    db: Session = Depends(get_db),
):
    return [
        _document_summary(document)
        for document in service.list_documents(db, principal.tenant_id, knowledge_base_id)
    ]


@router.post("/knowledge-bases/{knowledge_base_id}/documents")
def add_knowledge_document(
    knowledge_base_id: str,
    payload: KnowledgeDocumentPayload,
    request: Request,
    principal: Principal = Depends(require_roles("admin", "operator", "tenant_admin", "engagement_manager", "consultant")),
    db: Session = Depends(get_db),
):
    request_payload = {"knowledge_base_id": knowledge_base_id, **payload.model_dump()}
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="knowledge.add_document",
        idempotency_key=_idempotency_key(request),
        request_payload=request_payload,
    )
    if cached is not None:
        return cached
    document = service.add_document(
        db,
        principal.tenant_id,
        principal.user_id,
        knowledge_base_id,
        title=payload.title,
        content=payload.content,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        metadata=payload.metadata,
        correlation_id=_correlation_id(request),
    )
    response = _document_summary(document)
    complete_command(db, receipt, response=response, resource_type="knowledge_document", resource_id=document.id)
    db.commit()
    return response


@router.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
def get_knowledge_document(
    knowledge_base_id: str,
    document_id: str,
    principal: Principal = Depends(require_roles("admin", "operator", "viewer", "tenant_admin", "engagement_manager", "consultant", "auditor")),
    db: Session = Depends(get_db),
):
    document = service.get_document(db, principal.tenant_id, knowledge_base_id, document_id)
    return _document_detail(document)


@router.post("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/archive")
def archive_knowledge_document(
    knowledge_base_id: str,
    document_id: str,
    request: Request,
    principal: Principal = Depends(require_roles("admin", "operator", "tenant_admin", "engagement_manager")),
    db: Session = Depends(get_db),
):
    request_payload = {"knowledge_base_id": knowledge_base_id, "document_id": document_id}
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="knowledge.archive_document",
        idempotency_key=_idempotency_key(request),
        request_payload=request_payload,
    )
    if cached is not None:
        return cached
    document = service.archive_document(
        db,
        principal.tenant_id,
        principal.user_id,
        knowledge_base_id,
        document_id,
        _correlation_id(request),
    )
    response = _document_summary(document)
    complete_command(db, receipt, response=response, resource_type="knowledge_document", resource_id=document.id)
    db.commit()
    return response


@router.post("/knowledge-bases/{knowledge_base_id}/query")
def query_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeQueryPayload,
    request: Request,
    principal: Principal = Depends(require_roles("admin", "operator", "viewer", "tenant_admin", "engagement_manager", "consultant", "auditor")),
    db: Session = Depends(get_db),
):
    request_payload = {"knowledge_base_id": knowledge_base_id, **payload.model_dump()}
    receipt, cached = begin_command(
        db,
        tenant_id=principal.tenant_id,
        command_name="knowledge.query",
        idempotency_key=_idempotency_key(request),
        request_payload=request_payload,
    )
    if cached is not None:
        return cached
    response = service.query(
        db,
        principal.tenant_id,
        principal.user_id,
        knowledge_base_id,
        payload.question,
        top_k=payload.top_k,
        generate_answer=payload.generate_answer,
        correlation_id=_correlation_id(request),
    )
    complete_command(db, receipt, response=response, resource_type="knowledge_query", resource_id=response["query_id"])
    db.commit()
    return response
