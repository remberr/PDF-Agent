"""Bounded request leases; additive, no rewrite of existing session/vector data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0003_request_leases'
down_revision = '0002_vectors'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('session_request_leases',
        sa.Column('lease_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', sa.String(32), sa.ForeignKey('sessions.session_id', ondelete='CASCADE'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_request_lease_session_expiry', 'session_request_leases', ['session_id', 'expires_at'])


def downgrade():
    # Operational downgrade requires draining active requests first; never run
    # automatically. Relational history/documents/vectors are not modified.
    op.drop_table('session_request_leases')
