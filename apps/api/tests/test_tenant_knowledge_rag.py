import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import pytest

from app.auth.dependencies import ensure_tenant
from app.db.session import set_tenant_context
from app.knowledge.service import KnowledgeError, KnowledgeService
from app.models import Base, KnowledgeChunk, KnowledgeDocument, KnowledgeQuery, LedgerRecord, Tenant


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _provision(db, tenant_id: str):
    ensure_tenant(db, tenant_id, tenant_id.replace("-", " ").title())
    db.commit()
    set_tenant_context(db, tenant_id, "assisted-operator")


def test_five_client_knowledge_bases_do_not_share_documents_or_results(db):
    service = KnowledgeService()
    bases = {}
    canaries = {}

    for index in range(1, 6):
        tenant_id = f"client-{index}"
        canary = f"canarioexclusivo{index}"
        _provision(db, tenant_id)
        base = service.create_base(db, tenant_id, "assisted-operator", "Conhecimento do cliente")
        service.add_document(
            db,
            tenant_id,
            "assisted-operator",
            base.id,
            title=f"Política privada {index}",
            content=f"O código confidencial deste cliente é {canary}. Nunca use conhecimento de outro cliente.",
        )
        db.commit()
        bases[tenant_id] = base.id
        canaries[tenant_id] = canary

    for tenant_id, base_id in bases.items():
        set_tenant_context(db, tenant_id, "assisted-operator")
        result = service.query(
            db,
            tenant_id,
            "assisted-operator",
            base_id,
            f"Qual é o código {canaries[tenant_id]}?",
        )
        db.commit()
        assert result["results"]
        combined = " ".join(item["content"] for item in result["results"])
        assert canaries[tenant_id] in combined
        assert all(other not in combined for other_tenant, other in canaries.items() if other_tenant != tenant_id)
        assert db.query(KnowledgeDocument).filter_by(tenant_id=tenant_id).count() == 1
        assert db.query(KnowledgeQuery).filter_by(tenant_id=tenant_id).count() == 1


def test_known_cross_tenant_base_id_is_not_queryable(db):
    service = KnowledgeService()
    _provision(db, "client-a")
    base_a = service.create_base(db, "client-a", "operator", "Base A")
    service.add_document(
        db,
        "client-a",
        "operator",
        base_a.id,
        title="Segredo A",
        content="A senha operacional fictícia é orquidea-verde.",
    )
    db.commit()

    _provision(db, "client-b")
    with pytest.raises(KnowledgeError) as exc:
        service.query(db, "client-b", "operator", base_a.id, "Qual é a senha?")
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "KNOWLEDGE_BASE_NOT_FOUND"


def test_relational_constraint_rejects_cross_tenant_document_parent(db):
    service = KnowledgeService()
    _provision(db, "client-parent-a")
    base_a = service.create_base(db, "client-parent-a", "operator", "Base A")
    base_a_id = base_a.id
    db.commit()
    _provision(db, "client-parent-b")
    forged = KnowledgeDocument(
        id=str(uuid.uuid4()),
        tenant_id="client-parent-b",
        knowledge_base_id=base_a_id,
        title="Forged cross tenant row",
        content="must fail",
        checksum=uuid.uuid4().hex,
    )
    db.add(forged)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_retrieval_ledger_uses_hash_instead_of_question_or_document_content(db):
    service = KnowledgeService()
    _provision(db, "client-ledger")
    base = service.create_base(db, "client-ledger", "operator", "Base auditável")
    secret = "conteudo-ultrassecreto-cliente"
    question = "Onde está o conteudo-ultrassecreto-cliente?"
    service.add_document(
        db,
        "client-ledger",
        "operator",
        base.id,
        title="Manual interno",
        content=secret,
    )
    result = service.query(db, "client-ledger", "operator", base.id, question)
    db.commit()

    event = db.query(LedgerRecord).filter_by(
        tenant_id="client-ledger",
        aggregate_id=result["query_id"],
        event_type="knowledge.retrieval_completed",
    ).one()
    serialized = str(event.payload_json)
    assert secret not in serialized
    assert question not in serialized
    assert len(event.payload_json["question_hash"]) == 64


def test_archiving_document_removes_it_from_retrieval_index(db):
    service = KnowledgeService()
    _provision(db, "client-archive")
    base = service.create_base(db, "client-archive", "operator", "Base")
    document = service.add_document(
        db,
        "client-archive",
        "operator",
        base.id,
        title="Documento",
        content="A palavra de busca exclusiva é heliotropiointerno.",
    )
    db.commit()
    assert db.query(KnowledgeChunk).filter_by(document_id=document.id).count() == 1

    service.archive_document(db, "client-archive", "operator", base.id, document.id)
    result = service.query(db, "client-archive", "operator", base.id, "heliotropiointerno")
    db.commit()
    assert result["results"] == []
    assert db.query(KnowledgeChunk).filter_by(document_id=document.id).count() == 0


def test_generative_rag_requires_explicit_tenant_opt_in(db):
    service = KnowledgeService()
    _provision(db, "client-no-llm")
    base = service.create_base(db, "client-no-llm", "operator", "Base")
    service.add_document(
        db,
        "client-no-llm",
        "operator",
        base.id,
        title="Documento",
        content="O prazo contratual fictício é 30 dias.",
    )
    with pytest.raises(KnowledgeError) as exc:
        service.query(
            db,
            "client-no-llm",
            "operator",
            base.id,
            "Qual é o prazo?",
            generate_answer=True,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "RAG_GENERATION_NOT_ENABLED"


def test_generative_rag_receives_only_current_tenant_sources_and_requires_citation(db):
    captured = []

    class FakeGateway:
        def call(self, **kwargs):
            captured.extend(kwargs["messages"])
            return {"id": "model-call-1", "content": {"parsed": {"answer": "Prazo confirmado. [SOURCE 1]"}}}

    service = KnowledgeService(gateway=FakeGateway())
    _provision(db, "client-gen-a")
    tenant_a = db.query(Tenant).filter_by(id="client-gen-a").one()
    tenant_a.runtime_configuration_json = {"llm_real": "enabled", "rag_generation": "enabled"}
    base_a = service.create_base(db, "client-gen-a", "operator", "Base A")
    service.add_document(
        db,
        "client-gen-a",
        "operator",
        base_a.id,
        title="Contrato A",
        content="O prazo exclusivo do cliente A é quarenta e dois dias. marcador-a-privado.",
    )
    db.commit()

    _provision(db, "client-gen-b")
    base_b = service.create_base(db, "client-gen-b", "operator", "Base B")
    service.add_document(
        db,
        "client-gen-b",
        "operator",
        base_b.id,
        title="Contrato B",
        content="O prazo exclusivo do cliente B é noventa dias. marcador-b-privado.",
    )
    db.commit()

    set_tenant_context(db, "client-gen-a", "operator")
    result = service.query(
        db,
        "client-gen-a",
        "operator",
        base_a.id,
        "Qual é o prazo exclusivo do cliente A?",
        generate_answer=True,
    )
    prompt = "\n".join(message["content"] for message in captured)
    assert result["answer"] == "Prazo confirmado. [SOURCE 1]"
    assert "marcador-a-privado" in prompt
    assert "marcador-b-privado" not in prompt
