"""Add session-scoped dense vectors without replacing relational rows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from pgvector.sqlalchemy import VECTOR

revision = '0002_vectors'
down_revision = '0001_relational'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('document_chunks',
        sa.Column('chunk_id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', sa.String(32), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chunk_ordinal', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', pg.JSONB(), nullable=False),
        sa.Column('embedding', VECTOR(1024), nullable=False),
        sa.Column('embedding_profile_id', sa.String(64), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('import_source_id', sa.String(64)),
        sa.ForeignKeyConstraint(['session_id', 'document_id'], ['session_documents.session_id', 'session_documents.document_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('session_id', 'document_id', 'chunk_ordinal', name='uq_document_chunk_order'),
        sa.CheckConstraint('chunk_ordinal >= 0', name='chunk_order_nonnegative'),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name='chunk_metadata_object'),
        sa.CheckConstraint('vector_norm(embedding) > 0', name='chunk_vector_nonzero'))
    op.create_index('ix_chunk_scope_profile', 'document_chunks', ['session_id', 'embedding_profile_id'])


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; preserve vectors and restore a verified backup.')
