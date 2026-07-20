"""tenant-isolated knowledge and RAG storage

Revision ID: 0004_tenant_knowledge_rag
Revises: 0003_temporal_transactional_outbox
Create Date: 2026-07-14 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_tenant_knowledge_rag"
down_revision: Union[str, None] = "0003_temporal_transactional_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = ["knowledge_bases", "knowledge_documents", "knowledge_chunks", "knowledge_queries"]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "knowledge_bases" not in tables:
        op.create_table(
            "knowledge_bases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("retrieval_version", sa.String(), nullable=False, server_default="hybrid-hashing-bm25-v1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_base_tenant_id"),
        )
        op.create_index("ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"])
        op.create_index("ix_knowledge_bases_status", "knowledge_bases", ["status"])

    tables = set(sa.inspect(bind).get_table_names())
    if "knowledge_documents" not in tables:
        op.create_table(
            "knowledge_documents",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("knowledge_base_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=False, server_default="operator"),
            sa.Column("source_ref", sa.String(), nullable=False, server_default=""),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("checksum", sa.String(), nullable=False),
            sa.Column("storage_key", sa.String(), nullable=False, server_default=""),
            sa.Column("status", sa.String(), nullable=False, server_default="ready"),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_by_user_id", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "knowledge_base_id",
                "checksum",
                name="uq_knowledge_document_tenant_base_checksum",
            ),
            sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_document_tenant_id"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "knowledge_base_id"],
                ["knowledge_bases.tenant_id", "knowledge_bases.id"],
                name="fk_knowledge_document_tenant_base",
            ),
        )
        op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])
        op.create_index("ix_knowledge_documents_knowledge_base_id", "knowledge_documents", ["knowledge_base_id"])
        op.create_index("ix_knowledge_documents_checksum", "knowledge_documents", ["checksum"])
        op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
        op.create_index("ix_knowledge_documents_created_by_user_id", "knowledge_documents", ["created_by_user_id"])

    tables = set(sa.inspect(bind).get_table_names())
    if "knowledge_chunks" not in tables:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("knowledge_base_id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("embedding_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_document_index"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "knowledge_base_id"],
                ["knowledge_bases.tenant_id", "knowledge_bases.id"],
                name="fk_knowledge_chunk_tenant_base",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "document_id"],
                ["knowledge_documents.tenant_id", "knowledge_documents.id"],
                name="fk_knowledge_chunk_tenant_document",
            ),
        )
        op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])
        op.create_index("ix_knowledge_chunks_knowledge_base_id", "knowledge_chunks", ["knowledge_base_id"])
        op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
        op.create_index("ix_knowledge_chunk_tenant_base", "knowledge_chunks", ["tenant_id", "knowledge_base_id"])

    tables = set(sa.inspect(bind).get_table_names())
    if "knowledge_queries" not in tables:
        op.create_table(
            "knowledge_queries",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("knowledge_base_id", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), nullable=False, server_default=""),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("question_hash", sa.String(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False, server_default=""),
            sa.Column("answer_mode", sa.String(), nullable=False, server_default="extractive"),
            sa.Column("top_k", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("result_refs_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id", "knowledge_base_id"],
                ["knowledge_bases.tenant_id", "knowledge_bases.id"],
                name="fk_knowledge_query_tenant_base",
            ),
        )
        op.create_index("ix_knowledge_queries_tenant_id", "knowledge_queries", ["tenant_id"])
        op.create_index("ix_knowledge_queries_knowledge_base_id", "knowledge_queries", ["knowledge_base_id"])
        op.create_index("ix_knowledge_queries_actor_user_id", "knowledge_queries", ["actor_user_id"])
        op.create_index("ix_knowledge_queries_question_hash", "knowledge_queries", ["question_hash"])

    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            sa.text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema() "
                f"AND tablename = '{table}' AND policyname = 'asf_tenant_isolation') THEN "
                f"CREATE POLICY asf_tenant_isolation ON \"{table}\" "
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')) "
                "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')); "
                "END IF; END $$;"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if bind.dialect.name == "postgresql":
        for table in reversed(TENANT_TABLES):
            if table in tables:
                op.execute(f'DROP POLICY IF EXISTS asf_tenant_isolation ON "{table}"')
                op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
                op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table in ["knowledge_queries", "knowledge_chunks", "knowledge_documents", "knowledge_bases"]:
        if table in set(sa.inspect(bind).get_table_names()):
            op.drop_table(table)
