"""Initial relational schema. No existing SQLite files are read or changed."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0001_relational'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sessions',
        sa.Column('session_id', sa.String(32), primary_key=True),
        sa.Column('document_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("session_id ~ '^[a-f0-9]{32}$'", name='session_id_format'),
        sa.CheckConstraint('document_count >= 0', name='session_pages_nonnegative'))
    op.create_index('ix_sessions_updated_at', 'sessions', ['updated_at'])
    op.create_table('session_messages',
        sa.Column('session_id', sa.String(32), sa.ForeignKey('sessions.session_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('ordinal', sa.BigInteger(), primary_key=True),
        sa.Column('payload', pg.JSONB(), nullable=False),
        sa.Column('batch_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('batch_ordinal', sa.Integer(), nullable=False),
        sa.UniqueConstraint('session_id', 'batch_id', 'batch_ordinal', name='uq_message_batch'),
        sa.CheckConstraint('ordinal >= 0 AND batch_ordinal >= 0', name='message_order_nonnegative'),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name='message_payload_object'))
    op.create_table('session_documents',
        sa.Column('session_id', sa.String(32), sa.ForeignKey('sessions.session_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('document_id', sa.Integer(), primary_key=True),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('page_count', sa.Integer()), sa.Column('chunk_count', sa.Integer()),
        sa.Column('size_bytes', sa.BigInteger()), sa.Column('sha256', sa.String(64)),
        sa.Column('uploaded_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('session_id', 'filename', name='uq_session_filename'),
        sa.CheckConstraint('document_id >= 0 AND page_count >= 0 AND chunk_count >= 0 AND size_bytes >= 0', name='document_counts_nonnegative'))


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; restore a verified backup instead.')
